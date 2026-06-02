# Keyword Feedback Deployment

This fork is configured to run in keyword-profile mode. It keeps the original paper retrieval, LLM TLDR, affiliation extraction, SMTP email, and reranker integrations, but recommendation no longer requires a Zotero library.

## What It Sends

Each daily email contains:

- 40 papers ranked against the current top keyword profile.
- 10 exploratory papers ranked against guessed adjacent keywords.
- Paper title, authors, affiliations, TLDR, extracted abstract keywords, similarity score, PDF/abstract links, and feedback buttons.
- `Interested` and `Like` feedback buttons. The buttons open pre-filled GitHub issues. Submit the issue; the next workflow run reads it, updates `data/interest_profile.json`, and closes the issue automatically.

## Initial Keywords

The checked-in initial profile is:

- `world model`
- `unified model`
- `generation model`

The workflow keeps at most 10 active top keywords. Feedback on a liked paper has a stronger weight than feedback on an interested paper.

## Required GitHub Secrets

Set these in `Settings -> Secrets and variables -> Actions -> Secrets`:

- `SENDER`: SMTP sender email address.
- `SENDER_PASSWORD`: SMTP password or app password.
- `RECEIVER`: destination email address.
- `OPENAI_API_KEY`: OpenAI-compatible LLM API key.
- `OPENAI_API_BASE`: OpenAI-compatible API base URL.
- `SILICONFLOW_API_KEY`: SiliconFlow rerank API key.

`ZOTERO_ID` and `ZOTERO_KEY` are optional in keyword mode. They are only needed if you disable `interest.enabled` and return to the original Zotero mode.

## Repository Variables

The checked-in `config/custom.yaml` is already usable. If you prefer repository variables, set `CUSTOM_CONFIG` to the contents of `config/custom.yaml`.

## Action Permissions

The workflow declares:

- `contents: write`, so it can commit `data/interest_profile.json`.
- `issues: write`, so it can read and close feedback issues.

Also confirm the repository setting `Settings -> Actions -> General -> Workflow permissions` allows read and write permissions.

## Schedule

`.github/workflows/main.yml` runs every day at `22:00 UTC`. You can also run `.github/workflows/test.yml` manually with debug mode enabled.

## State File

`data/interest_profile.json` stores:

- current keyword scores,
- processed feedback issue IDs,
- feedback history,
- the previous run's recommended papers.

Do not delete this file unless you want to reset the profile back to the default keywords.
