# Keyword Feedback Deployment

This fork is configured to run in keyword-profile mode. It keeps the original paper retrieval, LLM TLDR, affiliation extraction, SMTP email, and reranker integrations, but recommendation no longer requires a Zotero library.

## What It Sends

Each daily email contains:

- 50 papers ranked against the current top keyword profile, then diversified with MMR so near-duplicate topics do not dominate one issue.
- 10 exploratory papers ranked against guessed adjacent keywords.
- Paper title, authors, affiliations, TLDR, extracted abstract keywords, similarity score, PDF/abstract links, and feedback buttons.
- `Interested`, `Like`, and `少推荐此类` feedback buttons. The buttons open pre-filled GitHub issues. Positive actions strengthen matching topics; `少推荐此类` adds them to a separate negative profile that is applied as a ranking penalty.
- A short recommendation reason with the matched interest topics.

## Initial Keywords

The checked-in initial profile is:

- `world model`
- `unified model`
- `generation model`

The workflow keeps at most 10 active top keywords and 10 suppressed keywords. Feedback on a liked paper has a stronger weight than feedback on an interested paper. A later positive action reduces an earlier negative signal for the same keyword, so the profile can correct itself.

Both delivery surfaces consume this state: `Send emails daily` uses it to build the daily email, and `Daily ArXiv Paper Fetch` reads the same `data/interest_profile.json` before producing GitHub Pages' `papers.json`.

## Required GitHub Secrets

Set these in `Settings -> Secrets and variables -> Actions -> Secrets`:

- `SENDER`: SMTP sender email address.
- `SENDER_PASSWORD`: SMTP password or app password.
- `RECEIVER`: destination email address.
- `OPENAI_API_KEY`: OpenAI-compatible LLM API key (optional when the SiliconFlow key is used as the LLM fallback).
- `OPENAI_API_BASE`: OpenAI-compatible API base URL (defaults to SiliconFlow when only `SILICONFLOW_API_KEY` is configured).
- `SILICONFLOW_API_KEY`: SiliconFlow rerank API key.

`ZOTERO_ID` and `ZOTERO_KEY` are optional in keyword mode. They are only needed if you disable `interest.enabled` and return to the original Zotero mode.

If `SENDER`, `SENDER_PASSWORD`, or `RECEIVER` is absent, the scheduled email job records a notice and skips cleanly. The separate GitHub Pages workflow continues to run. Feedback does not depend on SMTP: `Sync paper feedback` runs when a feedback issue is opened, every six hours as a safety net, or manually from Actions.

## Repository Variables

The checked-in `config/custom.yaml` is already usable. If you prefer repository variables, set `CUSTOM_CONFIG` to the contents of `config/custom.yaml`.

## Action Permissions

The workflow declares:

- `contents: write`, so it can commit `data/interest_profile.json`.
- `issues: write`, so it can read and close feedback issues.

Also confirm the repository setting `Settings -> Actions -> General -> Workflow permissions` allows read and write permissions.

## Schedule

`.github/workflows/main.yml` runs every day at `22:00 UTC`. You can also run `.github/workflows/test.yml` manually with debug mode enabled. `.github/workflows/sync-feedback.yml` is the lightweight profile-only workflow; it needs GitHub's built-in `GITHUB_TOKEN` permissions but no mail secret.

## State File

`data/interest_profile.json` stores:

- current keyword scores,
- negative/suppressed keyword scores,
- processed feedback issue IDs,
- feedback history,
- the previous run's recommended papers.

Do not delete this file unless you want to reset both positive and negative interests back to the defaults.

## Recommendation controls

The following `interest` settings in `config/custom.yaml` tune the first-stage recommender without replacing the configured Qwen reranker:

- `not_interested_weight` controls how strongly a `少推荐此类` action adds a negative keyword.
- `negative_match_penalty` is deducted for each negative phrase represented in a candidate after reranking.
- `mmr_diversity_lambda` controls the final MMR reorder. `1.0` keeps pure relevance ordering; the default `0.65` preserves relevance while spreading the selected papers across topics.

The current implementation intentionally leaves `executor.reranker: siliconflow` in place as the precision ranker. Future embedding-model or multi-prototype experiments can be evaluated against the explicit feedback history without changing this stable feedback loop.
