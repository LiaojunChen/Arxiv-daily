"""Client for the private Cloudflare Worker feedback-sync endpoints."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from loguru import logger


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"none", "null", "false"}:
        return None
    return cleaned


class CloudflareFeedbackClient:
    """Fetch pending Worker events and acknowledge only durable profile updates."""

    def __init__(self, api_url: str | None, sync_token: str | None, *, batch_size: int = 100):
        self.api_url = _clean_value(api_url)
        self.sync_token = _clean_value(sync_token)
        self.batch_size = max(1, min(int(batch_size), 200))

    @classmethod
    def from_config(cls, config) -> "CloudflareFeedbackClient":
        feedback_config = config.get("feedback", {})
        cloudflare_config = feedback_config.get("cloudflare", {})
        enabled = bool(cloudflare_config.get("enabled", False))
        api_url = cloudflare_config.get("api_url") or os.environ.get("CLOUDFLARE_FEEDBACK_API_URL")
        sync_token = cloudflare_config.get("sync_token") or os.environ.get("CLOUDFLARE_FEEDBACK_SYNC_TOKEN")
        if not enabled:
            api_url = None
            sync_token = None
        return cls(
            api_url=api_url,
            sync_token=sync_token,
            batch_size=cloudflare_config.get("batch_size", 100),
        )

    def enabled(self) -> bool:
        return bool(self.api_url and self.sync_token)

    def fetch_feedback(self) -> list[dict[str, Any]]:
        if not self.enabled():
            logger.info("Cloudflare feedback collection is disabled because API URL or sync token is missing.")
            return []

        payload = self._request_json(
            f"/v1/internal/feedback?{urlencode({'limit': self.batch_size})}",
        )
        events = payload.get("events", []) if isinstance(payload, dict) else []
        if not isinstance(events, list):
            raise RuntimeError("Cloudflare feedback API returned an invalid events payload.")
        feedback = [event for event in events if isinstance(event, dict)]
        logger.info(f"Collected {len(feedback)} pending Cloudflare feedback event(s)")
        return feedback

    def acknowledge_feedback(self, feedback: list[dict[str, Any]]) -> None:
        if not self.enabled():
            return
        feedback_ids = [
            item["feedback_id"]
            for item in feedback
            if isinstance(item.get("feedback_id"), int) and item["feedback_id"] > 0
        ]
        if not feedback_ids:
            return
        self._request_json("/v1/internal/ack", method="POST", payload={"feedback_ids": feedback_ids})

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not self.api_url or not self.sync_token:
            raise RuntimeError("Cloudflare feedback API URL and sync token must be set before making requests.")

        url = f"{self.api_url.rstrip('/')}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.sync_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Cloudflare feedback API {method} {path} failed with HTTP {exc.code}: {body[:500]}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Cloudflare feedback API {method} {path} failed: {exc}") from exc

        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Cloudflare feedback API returned invalid JSON.") from exc
