# Personal recommendation pipeline

The shared snapshot powers Pages and email. A new arXiv announcement batch produces up to 50 recommendations (normally 40 primary plus up to 10 exploration). There is no new global relevance cutoff. If exploration is unsuitable, primary results fill its places; if fewer than 50 unseen eligible papers exist, the list is shorter instead of recycling papers.

## Ranking

Each of the top ten weighted interest themes gets its own rerank query. Up to eight liked/interested/bookmarked papers and eight recent Zotero papers provide additional example channels, even when explicit keywords exist. Positive channel scores are combined numerically: 65% weighted best channel plus 35% weighted mean, on a 0–10 scale. Weights are applied in code, not left as numbers in a prompt. Each result records its topic scores, leading topic, semantic score and follow boost. These scores are not calibrated probabilities.

Confirmed unwanted themes and their paper examples incur a bounded soft penalty. An author follow adds up to 15% of the semantic score; an institution follow up to 10%, with their combined addition capped at one point. Unknown affiliations are never guessed. Consequently institution boosts depend on metadata already available at selection time.

Exploration requires semantic relevance at least the larger of the candidate median and one quarter of the best score, no confirmed unwanted theme match, and an uncovered topic or at least two keywords not covered by the primary list. Its diversity penalty compares against the entire already selected list. Unused exploration slots return to the primary group.

Rerank calls use the existing cache, validation and one retry. Failure of any channel switches every channel to the deterministic fallback scale. Independent corpus phrase extraction supplies feedback keywords.

## New batches and permanent deduplication

New arXiv listings, including cross-lists and excluding replacements, define the recommendation batch. HF remains a supplementary view; older HF curation does not fill the new-paper recommendation quota. The seven-day candidate pool still supports follow searches independently of recommendation selection.

`interest_profile.json.recommended_papers` is a permanent canonical-ID ledger, separate from expiring caches. It is written after successful Pages publication. Startup also recovers the live snapshot before generating a new issue, covering a deployment that succeeded before its ledger commit failed. Transient recovery failures stop the job rather than silently lose publication history. Historical snapshots and retained legacy run selections have been backfilled where available; expired historical artifacts cannot be reconstructed.

The current batch is frozen: later runs enrich its metadata without replacing its selection or emailing it again. A new batch excludes every recorded recommendation, read paper and dismissed paper. Changing arXiv versions never makes a previously recommended paper eligible. Already published current-issue cards remain visible; that is a refresh of the existing issue, not another recommendation issue.

## Feedback and subscriptions

`read` and `bookmark` are separate explicit states. Reading does not create positive keyword evidence. Likes, interest and bookmarks provide positive examples. `dismiss` excludes only that paper. `not_interested` also gathers theme evidence, but a theme is suppressed only after two distinct papers support it. Duplicate events or repeated clicks are not extra votes. A positive correction withdraws that paper's negative evidence without repeatedly adding the same positive weight.

In Settings, Save stores local preferences and posts only author/institution lists to the authenticated Worker. AI credentials are never included. Empty lists explicitly clear server follows. The hourly feedback sync and daily generation import the latest preference revision into the owner's shared recommendation profile. Local follow filtering updates immediately; ranking changes apply to the next new batch. Each browser can retain its own local filter, while the last explicitly saved server list controls the shared feed.

The Worker retains existing public access-code and private sync-token authentication. Migration `0002_preferences.sql` adds columns and a preferences table without rewriting old events. New event types are exposed through `action_v2`; deploy the matching Worker before the new Pages frontend. Keep the v2 Worker when pending v2 events exist. GitHub Issue feedback continues to allow the repository owner by default and requires known run/paper metadata.

## Schedule and deployment

arXiv announces Sunday–Thursday at 20:00 America/New_York, subject to holidays/delays. The 20:05 run prioritizes publication using cached affiliations; the 00:10 run refreshes metadata with the normal 900-second extraction budget. GitHub handles DST. Open visible pages revalidate every minute and on focus. GitHub scheduling is best effort, not an exact-time delivery guarantee.

Deploy order: authenticate Wrangler, apply migration 0002 to the existing D1 binding, deploy the updated Worker preserving its existing secrets/origins, merge the application change, then run `daily-fetch.yml` with `quick=true`. Verify preferences/feedback endpoints, snapshot batch/ledger state, and the Pages deployment. A preview deployment without the Worker migration is not sufficient to enable the new feedback controls.

## Validation

Python regression tests cover explicit topic weights, corpus fusion, consistent fallback, follow boost, distinct negative evidence, corrections, separate reading/bookmark states, permanent version-independent deduplication, same-batch reuse and next-batch exclusion. Frontend tests cover allowlisted preference payloads, error reporting and refresh behavior. The Worker integration test executes both D1 migrations and authenticates, saves/clears preferences, preserves legacy events, and submits/acknowledges new actions. `scripts/evaluate_recommendations.py` remains available for manually labelled relevance evaluation.
