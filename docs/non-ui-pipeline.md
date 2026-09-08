# Subscription and recommendation pipeline

The scheduled `Daily ArXiv Paper Fetch` now owns feedback synchronization, candidate collection, ranking, snapshot registration and Pages deployment. Its email job consumes the same `papers.json` artifact. `Send emails daily` is a manual alias for that workflow; it no longer has a second schedule. The legacy CLI and manual debug workflow remain available for development.

## Subscriptions

The static site downloads `candidate_papers`, a rolling seven-day pool of RSS and HF candidates, independently of recommendation Top N. Browser subscriptions filter that pool immediately after saving. They remain local preferences; no credential or preference is uploaded. This fixes recall within the downloaded categories/date window without requiring a subscription server or changing the settings UI.

`data/config.json` provides the repository's defaults and precomputed follows. An explicitly saved browser list overrides those defaults, including an empty list. Changing browser preferences does not change the repository owner's email settings or another browser. Subscription coverage is reported in the snapshot's `coverage` and `pipeline_status` fields.

Author matching requires a normalized complete name. Institutional aliases live in `data/institution_aliases.json`, consumed by both Python and TypeScript. Add known aliases there; arbitrary abbreviation inference is deliberately avoided. Institution metadata has `resolved`, `unresolved` or `pending` status. No implementation can match an institution whose affiliation has not yet been extracted; such papers remain in the candidate pool rather than being discarded.

## Feedback and history

GitHub Issue feedback defaults to the repository owner's login only. Configure `feedback.allowed_users` with explicit GitHub logins to permit additional trusted submitters; `[]` disables all Issue submissions. Issue-provided paper metadata is discarded. Events must refer to a known run and paper. Cloudflare events continue to use the existing authenticated service, with old embedded snapshots supported for compatibility.

Published runs retain compact title/keyword snapshots in `interest_profile.json.runs`. The previous `last_run` is migrated on load. Existing links whose snapshots were already lost before this upgrade cannot be reconstructed automatically. Unknown events remain pending and are never acknowledged as applied, including when processed alongside valid feedback. Idempotency IDs are retained rather than truncated lexicographically.

New arXiv paper IDs are version-independent IDs on both surfaces; existing historical IDs remain queryable in their saved runs. Paper keywords are extracted independently of interest matches and submitted separately, allowing new topics to enter the profile. Profile decay now depends on elapsed days, not the number of sync batches.

Feedback button layout and whether separate button actions should be editable/undoable are not changed by this non-UI patch; distinct action events retain their existing meaning.

## Ranking and resource budgets

Reranker results must include exactly one finite score in [0,1] for each document. A failed batch gets one retry. If any batch still fails, the entire run uses the same deterministic fallback scale; missing scores are never silently treated as low relevance. Keyword matching uses word boundaries (and contiguous CJK phrases). Zero/nonfinite scores are excluded before diversity selection.

The shared snapshot contains primary and exploration groups within the total `MAX_PAPER_NUM` budget. Exploration cannot bypass relevance or negative-feedback filtering. Profile weights enter the model query and deterministic fallback. Previously recommended papers from the preceding seven days are downweighted. The existing UI continues to render the returned list.

`data/cache` stores candidate history, successful rerank scores and affiliation extraction outcomes. GitHub Actions restores this cache across runs. Successful affiliation results expire after 30 days and failures after six hours. Version/content changes invalidate cache entries. Requests are serialized with a three-second minimum start interval. `AFFILIATION_BUDGET_SECONDS` defaults to 900; the existing paper/LLM count limits still apply. Budget exhaustion leaves candidates marked pending for a later run. A cache miss reduces historical coverage and performance but cannot discard today's candidate list.

The scheduled workflow requires `interest.state_path: data/interest_profile.json` so the commit/ack sequence persists the file it actually updated. Local commands may use another path. Source failure, ranking degradation, profile version and coverage are included in JSON. Both sources returning no valid data aborts publication, preserving the previous deployment.

## Validation and evaluation

Run `PYTHONPATH=src pytest -m 'not slow'`; run `npm test`, `npm run lint`, and `npm run build` from frontend. CI includes the frontend checks. No paid API, email send or deployed feedback submission is needed by the new regression tests.

For ranking evaluation, label a fixed candidate set in JSON:

```json
{
  "2609.00001": {"relevance": 3, "topics": ["world model"], "negative": false},
  "2609.00002": {"relevance": 0, "topics": ["unrelated"], "negative": true}
}
```

Run `python scripts/evaluate_recommendations.py data/papers.json labels.json --k 10`. It reports Precision@K, NDCG@K, negative rate and topic count, and refuses to silently treat unlabeled returned results as irrelevant. Compare changes against the same labeled candidate set; passing regression tests alone is not evidence of better personal recommendation quality.
