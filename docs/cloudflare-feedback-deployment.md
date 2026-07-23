# Cloudflare Worker + D1 web-feedback deployment

This deployment gives the GitHub Pages dashboard direct `喜欢`, `感兴趣`, and `少推荐此类` actions. Browser events are written to Cloudflare D1, then the repository's `Sync paper feedback` workflow folds them into the versioned `data/interest_profile.json` file.

The public page never receives a GitHub token, Cloudflare API token, D1 database ID, or the Action-to-Worker synchronization token.

## 1. Create and deploy the Worker

Run the following from a local clone. The first `npm install` is intentionally scoped to the Worker folder.

```bash
cd cloudflare/feedback-worker
npm install
npx wrangler login
npx wrangler d1 create arxiv-daily-feedback
```

Copy `wrangler.toml.example` to `wrangler.toml`, then replace `REPLACE_WITH_D1_DATABASE_ID` with the `database_id` returned by the create command. Set `ALLOWED_ORIGINS` to the **origin** of the deployed Pages site. For this repository it is:

```toml
ALLOWED_ORIGINS = "https://liaojunchen.github.io"
```

The Pages path (`/Arxiv-daily/`) is not part of an HTTP Origin. If you also use a custom domain, add it as a comma-separated origin.

Create the D1 table and set the three Worker secrets:

```bash
npx wrangler d1 migrations apply arxiv-daily-feedback --remote
npx wrangler secret put FEEDBACK_ACCESS_CODE
npx wrangler secret put FEEDBACK_RATE_LIMIT_SALT
npx wrangler secret put SYNC_API_TOKEN
npx wrangler deploy
```

Use separate, high-entropy values for all three secrets. `FEEDBACK_ACCESS_CODE` is the private code you will enter once in the dashboard's Settings tab. `FEEDBACK_RATE_LIMIT_SALT` is an arbitrary random value used only to hash browser identifiers before rate limiting. `SYNC_API_TOKEN` authenticates the GitHub Action's internal pull/acknowledgement requests.

The deploy command prints an endpoint such as `https://arxiv-daily-feedback.<account>.workers.dev`. A basic deployment check is:

```bash
curl https://arxiv-daily-feedback.<account>.workers.dev/v1/health
```

It should return `{"ok":true}`.

## 2. Connect GitHub Actions and Pages

In `Settings -> Secrets and variables -> Actions`, add:

| Type | Name | Value |
| --- | --- | --- |
| Repository variable | `CLOUDFLARE_FEEDBACK_API_URL` | Worker URL, without a trailing slash |
| Repository secret | `CLOUDFLARE_FEEDBACK_SYNC_TOKEN` | Exactly the Worker `SYNC_API_TOKEN` value |

Do **not** put `FEEDBACK_ACCESS_CODE`, `SYNC_API_TOKEN`, Cloudflare API tokens, or D1 identifiers in `VITE_*` variables. `VITE_FEEDBACK_API_URL` is populated by the Pages workflow from the public repository variable above; it contains only the Worker URL.

Run `Daily ArXiv Paper Fetch` once after saving the variable so the static frontend includes the endpoint. The `Sync paper feedback` workflow runs hourly (and can also be started manually) to update the profile. It first commits the profile, then asks the Worker to mark only those persisted D1 events as processed.

## 3. Use the browser feedback controls

Open the Pages dashboard, select **Settings**, enter the value used for `FEEDBACK_ACCESS_CODE`, and save. The code is stored only in that browser's `localStorage`; it is sent as a request header when you click a feedback action, but it is not stored in D1.

Each paper card now has:

- `喜欢`: strongest positive topic signal.
- `感兴趣`: normal positive topic signal.
- `少推荐此类`: adds paper themes to the negative profile, so similar topics receive a ranking penalty.

The Worker deduplicates repeated clicks by browser, paper, recommendation run, and action. It also rate-limits each hashed browser identifier to 20 submissions per hour by default. These limits can be adjusted with `MAX_EVENTS_PER_HOUR` in `wrangler.toml`.

## Operational notes

- Email feedback links continue to use GitHub Issues as a fallback; web feedback no longer needs an Issue.
- Do not commit `cloudflare/feedback-worker/wrangler.toml` if it contains a real database ID or other local deployment details. The tracked `wrangler.toml.example` is the template.
- If a Worker request fails after the profile commit, its D1 row remains pending and will be safely retried. The profile records the Worker feedback ID, so retrying cannot apply the preference twice.
- To inspect events during debugging, use the Cloudflare D1 dashboard or `wrangler d1 execute`; do not expose `/v1/internal/*` endpoints to a browser because they require `SYNC_API_TOKEN`.
