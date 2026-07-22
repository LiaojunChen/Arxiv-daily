"""LLM-based affiliation extraction for papers shown on the web page."""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
import unicodedata
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
LLM_REQUEST_TIMEOUT = (10, 25)
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MAX_CONTEXT_CHARS = 12000
USER_AGENT = "arXivDaily/1.0"
AFFILIATION_PATTERN = re.compile(
    r"(?:\b(?:university|institute|college|school|laboratory|laboratories|"
    r"research|researcher|academy|center|centre|department|inc|corp|ltd|"
    r"google|microsoft|meta|openai|deepmind|anthropic|nvidia|amazon|apple|"
    r"bytedance|mit|stanford|berkeley)\b|labs?\b)",
    flags=re.IGNORECASE,
)
GENERIC_AFFILIATIONS = {
    "academy",
    "center",
    "centre",
    "department",
    "institute",
    "lab",
    "laboratory",
    "research",
    "school",
}

LATEX_ACCENTS = {
    '"': "\u0308",
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "c": "\u0327",
    "k": "\u0328",
    "b": "\u0331",
    "d": "\u0323",
}


class _TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0
        self.affiliation_parts: list[str] = []
        self._affiliation_depth = 0
        self._affiliation_buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self._ignored_depth += 1

        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        starts_affiliation = "ltx_role_affiliation" in classes
        if self._affiliation_depth or starts_affiliation:
            self._affiliation_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"} and self._ignored_depth:
            self._ignored_depth -= 1
        if self._affiliation_depth:
            self._affiliation_depth -= 1
            if not self._affiliation_depth:
                affiliation = _clean_text(" ".join(self._affiliation_buffer))
                if affiliation:
                    self.affiliation_parts.append(affiliation)
                self._affiliation_buffer = []

    def handle_data(self, data):
        if not self._ignored_depth:
            text = data.strip()
            if text:
                self.parts.append(text)
                if self._affiliation_depth:
                    self._affiliation_buffer.append(text)

    def text(self) -> str:
        # Preserve explicit LaTeXML affiliation spans as synthetic commands so
        # the deterministic TeX parser can handle both source and HTML input.
        affiliation_commands = "\n".join(
            f"\\affiliation{{{affiliation}}}" for affiliation in self.affiliation_parts
        )
        body = _clean_text(" ".join(self.parts))
        return f"{affiliation_commands}\n{body}".strip()


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

            content_length = response.headers.get("Content-Length")
            try:
                content_length = int(content_length) if content_length else None
            except (TypeError, ValueError):
                content_length = None
            if content_length and content_length > MAX_DOWNLOAD_BYTES:
                print(
                    f"[WARN] Skipping oversized download ({content_length} bytes): {url}"
                )
                return None

            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    print(f"[WARN] Download exceeded size limit; using fallback: {url}")
                    return None
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


def _clean_latex_affiliation(value: str, strip_marker: bool = True) -> str:
    def replace_accent(match: re.Match) -> str:
        accent, letter = match.groups()
        return unicodedata.normalize("NFC", letter + LATEX_ACCENTS[accent])

    value = re.sub(r"%.*", " ", value)
    value = re.sub(r'''\\(["'`^~=\.])\s*\{?([A-Za-z])\}?''', replace_accent, value)
    value = re.sub(r"\\([uvHckbd])\s*\{([A-Za-z])\}", replace_accent, value)
    value = re.sub(r"\\(?:href|url)\{[^{}]*\}\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\(?:email|thanks|footnote|corref|fnref|textsuperscript)\*?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", " ", value)
    value = re.sub(r"\\[a-zA-Z]+\*?\s*(?:\[[^\]]*\])?", " ", value)
    value = re.sub(r"\[[^\]]*(?:ex|em|pt)[^\]]*\]", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b\d+(?:\.\d+)?(?:ex|em|pt)\b", " ", value, flags=re.IGNORECASE)
    value = value.replace("\\", " ")
    value = value.replace("~", " ").replace("^", " ")
    value = re.sub(r"[{}$*]", " ", value)
    value = _clean_text(value)

    # LaTeX packages such as authblk/acmart sometimes expose structured fields
    # as ``organization=..., addressline=..., city=...``. Keep institutional
    # fields and discard postal-address noise before showing the value.
    field_pattern = re.compile(
        r"\b(organization|institution|department|addressline|city|postcode|"
        r"postalcode|country|state)\s*=\s*",
        flags=re.IGNORECASE,
    )
    field_matches = list(field_pattern.finditer(value))
    if field_matches:
        institutional_values = []
        for idx, match in enumerate(field_matches):
            end = field_matches[idx + 1].start() if idx + 1 < len(field_matches) else len(value)
            field_name = match.group(1).casefold()
            field_value = value[match.end() : end].strip(" ,;:-")
            if field_name in {"organization", "institution", "department"} and field_value:
                institutional_values.append(field_value)
        if institutional_values:
            value = ", ".join(institutional_values)

    value = re.sub(
        r"\s+(?:equal\s+(?:contribution|advising)|project\s+lead|"
        r"corresponding\s+author|tabular\b|https?://\S+|\S+\.github\.io\S*).*$",
        "",
        value,
        flags=re.IGNORECASE,
    )

    if strip_marker:
        value = re.sub(r"^(?:\d+|[a-z])\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" ,;:-")


def _looks_like_affiliation(value: str) -> bool:
    normalized = _clean_text(value)
    canonical = re.sub(r"[^a-z]+", " ", normalized.casefold()).strip()
    if len(normalized) < 3 or "@" in normalized or canonical in GENERIC_AFFILIATIONS:
        return False
    return AFFILIATION_PATTERN.search(normalized) is not None


def _normalize_display_affiliation(value: str, author: str = "") -> str:
    """Return a safe, human-readable affiliation or an empty string.

    Source and HTML formats vary widely, and the bounded LLM fallback can
    occasionally copy author labels, email addresses, or homepage URLs into an
    affiliation field.  Apply the same quality gate to every source before the
    value reaches the JSON consumed by the web page.
    """

    value = _clean_text(value)
    if not value:
        return ""

    # ``Apple Author 2`` is a common LaTeXML author-label artefact.  Do not
    # reduce it to ``Apple``: that would turn a malformed field into a false
    # positive company affiliation.
    if re.search(r"\bauthor\s*(?:\d+|[ivxlcdm]+)\b", value, flags=re.IGNORECASE):
        return ""

    # Remove contact details without discarding a legitimate institution that
    # happens to be adjacent to one.  A value that was only a URL/email then
    # fails the affiliation check below.
    value = re.sub(r"(?:https?://|www\.)\S+|\b\S+\.github\.io\S*", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b[^\s@]+@[^\s@]+\b", " ", value)
    value = _clean_latex_affiliation(value)
    value = re.sub(
        r"^(?:(?:contact|corresponding)\s+)?(?:affiliation|address)\s*:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = _clean_text(value)

    # A leading conjunction means the parser has captured only the tail of a
    # multi-line author block, so its institution name is incomplete.
    if re.match(r"^(?:and|&)\b", value, flags=re.IGNORECASE):
        return ""

    # A known author embedded *between* two affiliation fragments is ambiguous
    # (for example, ``Labs, Huawei Yingxue Zhang Noah's Ark Lab``).  Suppress
    # it rather than publishing a reordered or partial institution.  An author
    # accidentally copied as a leading/trailing label can still be removed.
    author = _clean_text(author)
    if author:
        author_match = re.search(
            rf"(?<!\w){re.escape(author)}(?!\w)", value, flags=re.IGNORECASE
        )
        if author_match:
            if value[: author_match.start()].strip(" ,;:-") and value[
                author_match.end() :
            ].strip(" ,;:-"):
                return ""
            value = value[: author_match.start()] + value[author_match.end() :]

    value = re.sub(r"\s*,\s*", ", ", value)
    value = _clean_text(value).strip(" ,;:-")
    return value if _looks_like_affiliation(value) else ""


def _normalize_affiliation_candidate(value: str) -> str:
    value = re.sub(r"^.*?\bare with\b\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^.*?\bis with\b\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^.*?\bis the director of\b\s+", "", value, flags=re.IGNORECASE)
    return _normalize_display_affiliation(value)


def _extract_numbered_affiliations(value: str) -> list[str]:
    cleaned = _clean_latex_affiliation(value, strip_marker=False)
    # Superscript affiliation labels are short (``1``, ``2``, ...).  A four
    # digit number is far more likely to be part of an institution name, such
    # as ``2012 Labs, Huawei``; treating it as a marker used to drop the first
    # half of the affiliation and merge later authors into the remainder.
    marker = r"(?:[1-9]\d{0,2})"
    matches = re.findall(
        rf"(?:^|\s){marker}\s+([A-Z][^0-9]*?)(?=\s+{marker}\s+[A-Z]|$)",
        cleaned,
    )
    affiliations = []
    for match in matches:
        candidate = _normalize_affiliation_candidate(match)
        if _looks_like_affiliation(candidate):
            affiliations.append(candidate)
    return affiliations


def _split_affiliation_candidates(block: str, include_whole: bool = True) -> list[str]:
    # ``\\And`` is case-sensitive in TeX but semantically the same separator
    # as ``\\and``.  Supporting both prevents following author names from
    # being merged into the preceding institution.
    parts = re.split(r"\\\\|\\and|\n|;", block, flags=re.IGNORECASE)
    candidates = []
    for part in parts:
        numbered_affiliations = _extract_numbered_affiliations(part)
        if numbered_affiliations:
            candidates.extend(numbered_affiliations)
            continue
        if part.strip().endswith(","):
            continue
        cleaned = _normalize_affiliation_candidate(part)
        if _looks_like_affiliation(cleaned):
            candidates.append(cleaned)
    numbered_affiliations = _extract_numbered_affiliations(block)
    if numbered_affiliations:
        candidates.extend(numbered_affiliations)
        return candidates
    if include_whole:
        whole = _normalize_affiliation_candidate(block)
        if _looks_like_affiliation(whole):
            candidates.append(whole)
    return candidates


def extract_affiliations_from_paper_text(paper_text: str, authors: list[str]) -> list[dict]:
    if not paper_text:
        return []

    blocks = [
        (block, True)
        for block in _latex_command_blocks(
            paper_text[:MAX_CONTEXT_CHARS],
            ("affiliation", "affil", "institute", "address", "IEEEauthorblockA"),
        )
    ]

    author_blocks = _latex_command_blocks(paper_text[:8000], ("author",))
    blocks.extend((block, False) for block in author_blocks)

    affiliations = []
    seen = set()
    for block, include_whole in blocks:
        for candidate in _split_affiliation_candidates(block, include_whole=include_whole):
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
    except (tarfile.TarError, EOFError, OSError):
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
        affiliation = _normalize_display_affiliation(affiliation, author)
        if not affiliation or affiliation.lower() in {"unknown", "none", "n/a", "not found"}:
            continue

        key = (author.casefold(), affiliation.casefold())
        if key in seen:
            continue
        seen.add(key)
        affiliations.append({"author": author, "affiliation": affiliation})

    return affiliations


def _normalize_existing_affiliations(affiliations, authors: list[str]) -> list[dict]:
    normalized = _normalize_affiliation_response(affiliations, authors)
    if normalized:
        return normalized
    return []


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
            timeout=LLM_REQUEST_TIMEOUT,
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

    affiliations_by_id: dict[str, list[dict]] = {}
    for group in paper_groups:
        for paper in group:
            existing = _normalize_existing_affiliations(
                paper.get("affiliations"), paper.get("authors", [])
            )
            paper["affiliations"] = existing
            arxiv_id = _normalize_arxiv_id(
                paper.get("arxiv_id") or paper.get("abstract_url") or ""
            )
            if arxiv_id and existing:
                affiliations_by_id.setdefault(arxiv_id, existing)

    # Interleave groups so a finite budget cannot be consumed entirely by the
    # first tab (which previously left every Hugging Face paper untouched).
    candidates = []
    max_group_size = max((len(group) for group in paper_groups), default=0)
    for index in range(max_group_size):
        for group in paper_groups:
            if index < len(group):
                candidates.append(group[index])

    attempted_ids = set()
    enriched_ids = set()
    llm_attempted = 0
    for paper in candidates:
        arxiv_id = _normalize_arxiv_id(
            paper.get("arxiv_id") or paper.get("abstract_url") or ""
        )
        if not arxiv_id:
            continue

        cached = affiliations_by_id.get(arxiv_id)
        if cached:
            paper["affiliations"] = cached
            continue
        if arxiv_id in attempted_ids:
            continue
        if AFFILIATION_MAX_PAPERS > 0 and len(attempted_ids) >= AFFILIATION_MAX_PAPERS:
            break
        attempted_ids.add(arxiv_id)

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
        if (
            not affiliations
            and OPENAI_API_KEY
            and llm_attempted < AFFILIATION_MAX_LLM_PAPERS
        ):
            llm_attempted += 1
            affiliations = _call_llm_for_affiliations(paper, paper_text)
        if affiliations:
            paper["affiliations"] = affiliations
            affiliations_by_id[arxiv_id] = affiliations
            enriched_ids.add(arxiv_id)
            print(f"[INFO] Extracted affiliations for {arxiv_id}: {len(affiliations)} entries")

    # Copies of one paper can appear in multiple tabs. Propagate cached values
    # after extraction instead of letting the duplicate-id guard leave them empty.
    for group in paper_groups:
        for paper in group:
            arxiv_id = _normalize_arxiv_id(
                paper.get("arxiv_id") or paper.get("abstract_url") or ""
            )
            if arxiv_id in affiliations_by_id:
                paper["affiliations"] = affiliations_by_id[arxiv_id]

    return len(enriched_ids)
