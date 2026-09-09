"""Record upstream cache evidence without confusing transport errors with empty feeds."""
import json
import urllib.request
from urllib.error import HTTPError


fetches = []


def fetch_text(url, timeout=30):
    evidence = {"url": url}
    fetches.append(evidence)
    request = urllib.request.Request(url, headers={
        "User-Agent": "arXivDaily/1.0", "Cache-Control": "no-cache, max-age=0", "Pragma": "no-cache",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = getattr(response, "headers", {})
            evidence.update(status=getattr(response, "status", 200),
                            response_date=headers.get("Date"), cache_age_seconds=headers.get("Age"),
                            cache_status=headers.get("X-Cache"))
            return response.read().decode("utf-8"), evidence
    except Exception as exc:
        evidence["error"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            evidence.update(status=exc.code, retry_after=exc.headers.get("Retry-After"))
        raise
    finally:
        print("[SOURCE] " + json.dumps(evidence, ensure_ascii=False))
