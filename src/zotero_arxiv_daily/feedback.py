from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from loguru import logger

from .protocol import Paper


MARKER_START = "<!-- zotero-arxiv-daily-feedback"
MARKER_END = "-->"


def make_paper_id(paper: Paper) -> str:
    raw = paper.url or paper.pdf_url or paper.title
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _clean_repo(repo: str | None) -> str | None:
    if not repo:
        return None
    repo = str(repo).strip()
    if repo.lower() in {"none", "null", "false"}:
        return None
    return repo.strip("/")


def build_feedback_issue_url(
    repo: str,
    paper: Paper,
    action: str,
    run_id: str,
    label: str | None = "paper-feedback",
) -> str:
    paper_id = paper.paper_id or make_paper_id(paper)
    action_label = {"interested": "Interested", "like": "Like"}.get(action, action)
    payload = {
        "paper_id": paper_id,
        "action": action,
        "run_id": run_id,
    }
    body = (
        f"{MARKER_START}\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        f"{MARKER_END}\n\n"
        "This issue was generated from the daily paper recommendation email.\n\n"
        f"Paper: [{paper.title}]({paper.url or paper.pdf_url or ''})\n"
        f"Feedback: {action_label}\n"
    )
    title = f"Paper feedback: {action_label} - {paper.title[:80]}"
    query_fields = {"title": title, "body": body}
    if label:
        query_fields["labels"] = label
    query = urlencode(query_fields)
    return f"https://github.com/{repo}/issues/new?{query}"


def parse_feedback_body(body: str | None) -> dict[str, Any] | None:
    if not body:
        return None
    start = body.find(MARKER_START)
    if start < 0:
        return None
    payload_start = start + len(MARKER_START)
    end = body.find(MARKER_END, payload_start)
    if end < 0:
        return None
    raw_payload = body[payload_start:end].strip()
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse feedback payload: {raw_payload[:200]}")
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("action") not in {"interested", "like"}:
        return None
    if not payload.get("paper_id"):
        return None
    return payload


class GitHubFeedbackClient:
    def __init__(
        self,
        repo: str | None,
        token: str | None,
        *,
        auto_close: bool = True,
    ):
        self.repo = _clean_repo(repo)
        self.token = token
        self.auto_close = auto_close

    @classmethod
    def from_config(cls, config) -> "GitHubFeedbackClient":
        feedback_config = config.get("feedback", {})
        repo = feedback_config.get("github_repo") or os.environ.get("GITHUB_REPOSITORY")
        token = feedback_config.get("github_token") or os.environ.get("GITHUB_TOKEN")
        auto_close = bool(feedback_config.get("auto_close_issues", True))
        return cls(repo=repo, token=token, auto_close=auto_close)

    def enabled(self) -> bool:
        return bool(self.repo and self.token)

    def fetch_feedback(self) -> list[dict[str, Any]]:
        if not self.enabled():
            logger.info("GitHub feedback collection is disabled because repo or token is missing.")
            return []

        feedback: list[dict[str, Any]] = []
        for page in range(1, 6):
            issues = self._request_json(
                f"/repos/{self.repo}/issues?state=open&per_page=100&page={page}&sort=created&direction=asc"
            )
            if not issues:
                break
            for issue in issues:
                if "pull_request" in issue:
                    continue
                payload = parse_feedback_body(issue.get("body"))
                if payload is None:
                    continue
                payload["issue_number"] = issue.get("number")
                payload["issue_url"] = issue.get("html_url")
                payload["created_at"] = issue.get("created_at")
                feedback.append(payload)
            if len(issues) < 100:
                break

        logger.info(f"Collected {len(feedback)} feedback issue(s)")
        return feedback

    def close_feedback_issues(self, feedback: list[dict[str, Any]]) -> None:
        if not self.enabled() or not self.auto_close:
            return
        seen: set[int] = set()
        for item in feedback:
            issue_number = item.get("issue_number")
            if not isinstance(issue_number, int) or issue_number in seen:
                continue
            seen.add(issue_number)
            try:
                self._request_json(
                    f"/repos/{self.repo}/issues/{issue_number}",
                    method="PATCH",
                    payload={"state": "closed", "state_reason": "completed"},
                )
            except RuntimeError as exc:
                logger.warning(f"Failed to close feedback issue #{issue_number}: {exc}")

    def _request_json(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None):
        if not self.repo or not self.token:
            raise RuntimeError("GitHub repo and token must be set before making API requests.")
        url = f"https://api.github.com{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {method} {path} failed with HTTP {exc.code}: {body[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"GitHub API {method} {path} failed: {exc}") from exc

        if not body:
            return None
        return json.loads(body)
