"""LLM-based affiliation extraction for papers shown on the web page."""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from html.parser import HTMLParser

import requests

from config import (
    AFFILIATION_MAX_LLM_PAPERS,
    AFFILIATION_MAX_PAPERS,
    MODEL_NAME,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
)


REQUEST_TIMEOUT = (10, 45)
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MAX_CONTEXT_CHARS = 12000
USER_AGENT = "arXivDaily/1.0"
AFFILIATION_KEYWORDS = (
    "university",
    "institute",
    "college",
    "school",
    "laborator",
    "research",
    "academy",
    "center",
    "centre",
    "department",
    "google",
    "microsoft",
    "meta",
    "openai",
    "deepmind",
    "anthropic",
    "nvidia",
    "amazon",
    "apple",
    "mit",
    "stanford",
    "berkeley",
)


class _TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return _clean_text(" ".join(self.parts))


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _normalize_arxiv_id(arxiv_id: str) -> str:
    arxiv_id = (arxiv_id or "").strip()
    if "/abs/" in arxiv_id:
        arxiv_id = arxiv_id.rsplit("/abs/", 1)[-1]
    if "/pdf/" in arxiv_id:
        arxiv_id = arxiv_id.rsplit("/pdf/", 1)[-1].removesuffix(".pdf")
    arxiv_id = arxiv_id.removeprefix("arXiv:").removeprefix("arxiv:")
    return re.sub(r"v\d+$", "", arxiv_id)


def _download_limited(url: str) -> bytes | None:
    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            stream=True,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status_code == 404:
                return None
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    break
            return b"".join(chunks)
    except requests.RequestException as exc:
        print(f"[WARN] Failed to download {url}: {exc}")
        return None


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding, errors="ignore")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_text_from_html_bytes(data: bytes) -> str | None:
    parser = _TextHTMLParser()
    parser.feed(_decode_bytes(data))
    text = parser.text()
    return text if len(text) > 200 else None


def _score_source_text(text: str) -> int:
    lowered = text.lower()
    return (
        lowered.count("affiliation") * 5
        + lowered.count("institute") * 3
        + lowered.count("university") * 3
        + lowered.count("\\author") * 2
        + lowered.count("\\affil") * 5
    )


def _read_braced_content(text: str, open_brace_idx: int) -> str | None:
    depth = 0
    start = open_brace_idx + 1
    for idx in range(open_brace_idx, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx]
    return None


def _latex_command_blocks(text: str, commands: tuple[str, ...]) -> list[str]:
    command_pattern = "|".join(re.escape(command) for command in commands)
    pattern = re.compile(
        rf"\\(?:{command_pattern})\*?\s*(?:\[[^\]]*\])?\s*\{{",
        flags=re.IGNORECASE,
    )
    blocks = []
    for match in pattern.finditer(text):
        block = _read_braced_content(text, match.end() - 1)
        if block:
            blocks.append(block)
    return blocks


def _clean_latex_affiliation(value: str) -> str:
    value = re.sub(r"%.*", " ", value)
    value = re.sub(r"\\(?:href|url)\{[^{}]*\}\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\(?:email|thanks|footnote|corref|fnref|textsuperscript)\*?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", " ", value)
    value = re.sub(r"\\[a-zA-Z]+\*?\s*(?:\[[^\]]*\])?", " ", value)
    value = value.replace("~", " ").replace("^", " ")
    value = re.sub(r"[{}$]", " ", value)
    value = _clean_text(value)
    return value.strip(" ,;:-")


def _looks_like_affiliation(value: str) -> bool:
    lowered = value.lower()
    if len(value) < 4 or "@" in value:
        return False
    return any(keyword in lowered for keyword in AFFILIATION_KEYWORDS)


def _split_affiliation_candidates(block: str) -> list[str]:
    parts = re.split(r"\\\\|\\and|\n|;", block)
    candidates = []
    for part in parts:
        cleaned = _clean_latex_affiliation(part)
        if _looks_like_affiliation(cleaned):
            candidates.append(cleaned)
    whole = _clean_latex_affiliation(block)
    if _looks_like_affiliation(whole):
        candidates.append(whole)
    return candidates


def extract_affiliations_from_paper_text(paper_text: str, authors: list[str]) -> list[dict]:
    blocks = _latex_command_blocks(
        paper_text[:MAX_CONTEXT_CHARS],
        ("affiliation", "affil", "institute", "address", "IEEEauthorblockA"),
    )

    author_blocks = _latex_command_blocks(paper_text[:8000], ("author",))
    blocks.extend(author_blocks)

    affiliations = []
    seen = set()
    for block in blocks:
        for candidate in _split_affiliation_candidates(block):
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            author = authors[len(affiliations)] if len(affiliations) < len(authors) else ""
            affiliations.append({"author": author, "affiliation": candidate})

    return affiliations


def _extract_text_from_source_bytes(data: bytes) -> str | None:
    candidates: list[tuple[int, str]] = []

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = member.name.lower()
                if not name.endswith((".tex", ".bbl", ".ltx")):
                    continue
                file_obj = archive.extractfile(member)
                if file_obj is None:
                    continue
                text = _decode_bytes(file_obj.read(512000))
                candidates.append((_score_source_text(text), text))
    except tarfile.TarError:
        try:
            text = _decode_bytes(gzip.decompress(data))
        except (OSError, EOFError):
            text = _decode_bytes(data)
        candidates.append((_score_source_text(text), text))

    candidates = [(score, text) for score, text in candidates if text.strip()]
    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    combined = "\n\n".join(text for _, text in candidates[:3])
    return combined[:MAX_CONTEXT_CHARS]


def fetch_paper_text(arxiv_id: str) -> str | None:
    arxiv_id = _normalize_arxiv_id(arxiv_id)
    if not arxiv_id:
        return None

    source_bytes = _download_limited(f"https://arxiv.org/e-print/{arxiv_id}")
    if source_bytes:
        source_text = _extract_text_from_source_bytes(source_bytes)
        if source_text:
            return source_text

    for url in (
        f"https://arxiv.org/html/{arxiv_id}",
        f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
    ):
        html_bytes = _download_limited(url)
        if not html_bytes:
            continue
        html_text = _extract_text_from_html_bytes(html_bytes)
        if html_text:
            return html_text[:MAX_CONTEXT_CHARS]

    return None


def _extract_json_array(content: str):
    match = re.search(r"\[.*\]", content or "", flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _normalize_affiliation_response(raw, authors: list[str]) -> list[dict]:
    if not isinstance(raw, list):
        return []

    affiliations = []
    seen = set()
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            author = authors[idx] if idx < len(authors) else ""
            affiliation = item
        elif isinstance(item, dict):
            author = item.get("author") or item.get("name") or ""
            affiliation = item.get("affiliation") or item.get("institution") or item.get("org") or ""
        else:
            continue

        author = _clean_text(author)
        affiliation = _clean_text(affiliation)
        if not affiliation or affiliation.lower() in {"unknown", "none", "n/a", "not found"}:
            continue

        key = (author.casefold(), affiliation.casefold())
        if key in seen:
            continue
        seen.add(key)
        affiliations.append({"author": author, "affiliation": affiliation})

    return affiliations


def _call_llm_for_affiliations(paper: dict, paper_text: str) -> list[dict]:
    if not OPENAI_API_KEY:
        return []

    authors = paper.get("authors", [])
    prompt = (
        "Extract the author affiliations from the beginning/source of this paper.\n"
        "Return only a JSON array. Each item must be an object with keys "
        '"author" and "affiliation". Keep author order. Use only affiliations '
        "that are present in the paper text. If no affiliations are present, return [].\n\n"
        f"Title: {paper.get('title', '')}\n"
        f"Authors: {json.dumps(authors, ensure_ascii=False)}\n\n"
        f"Paper text:\n{paper_text[:MAX_CONTEXT_CHARS]}"
    )
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "You extract scientific paper author affiliations and return strict JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 1000,
    }
    url = f"{OPENAI_API_BASE.rstrip('/')}/chat/completions"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException) as exc:
        print(f"[WARN] LLM affiliation extraction failed for {paper.get('arxiv_id')}: {exc}")
        return []

    return _normalize_affiliation_response(_extract_json_array(content), authors)


def enrich_affiliations_for_display_papers(paper_groups: list[list[dict]]) -> int:
    if not OPENAI_API_KEY:
        print("[WARN] No LLM API key set; only deterministic TeX affiliation extraction will run.")

    enriched = 0
    attempted = 0
    llm_attempted = 0
    seen_ids = set()
    for group in paper_groups:
        for paper in group:
            if attempted >= AFFILIATION_MAX_PAPERS:
                return enriched
            if paper.get("affiliations"):
                continue

            arxiv_id = _normalize_arxiv_id(paper.get("arxiv_id") or paper.get("abstract_url") or "")
            if not arxiv_id or arxiv_id in seen_ids:
                continue
            seen_ids.add(arxiv_id)
            attempted += 1

            try:
                paper_text = fetch_paper_text(arxiv_id)
            except Exception as exc:
                print(f"[WARN] Failed to read source/html text for {arxiv_id}: {exc}")
                continue
            if not paper_text:
                print(f"[WARN] No source/html text available for affiliation extraction: {arxiv_id}")
                continue

            authors = paper.get("authors", [])
            affiliations = extract_affiliations_from_paper_text(paper_text, authors)
            if not affiliations and OPENAI_API_KEY and llm_attempted < AFFILIATION_MAX_LLM_PAPERS:
                llm_attempted += 1
                affiliations = _call_llm_for_affiliations(paper, paper_text)
            if affiliations:
                paper["affiliations"] = affiliations
                enriched += 1
                print(f"[INFO] Extracted affiliations for {arxiv_id}: {len(affiliations)} entries")

    return enriched
