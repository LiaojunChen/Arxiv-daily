# Interest profile storage

The daily pipeline previously appended full candidate-paper snapshots to
`data/interest_profile.json`. This exceeded GitHub's 100 MiB single-file limit
and blocked the state push, Pages deployment and email job.

The active profile now retains at most three recent runs within an 8 MiB run
budget. Older runs are stored losslessly as individual compressed JSON files in
`data/interest_profile.runs/`. The filename is the SHA-256 hash of the run ID,
so feedback-supplied IDs cannot escape the archive directory. Feedback looks
up archived runs when they are absent from the active profile; old email links
continue to work.

Preferences, processed feedback IDs, published-paper IDs and delivery metadata
remain in the active profile. No historical snapshots or permanent state are
deleted. The initial migration is checked against every original run and all
non-run fields.

Both profile writers use the same storage helper. It writes archives before
atomically replacing the profile, and rejects individual files at 50 MiB,
well before GitHub's limit. Daily publishing, feedback sync and the manual
email workflow commit the profile and archive directory together using
`.github/scripts/commit-interest-profile.sh`, before feedback acknowledgement.

Archives are durable repository data, not an Actions cache. Keep this directory
with the profile when copying or restoring state. The total history continues
to grow across separate files; moving it to object storage can be considered
later if repository size becomes an issue.
