# Deploying Chompers to Vercel (private)

One Vercel project serves the React frontend (static) and runs the FastAPI backend
as a Python serverless function under `/api`, on the **same origin** — so there's no
CORS to configure and the frontend needs no changes. The site is kept **private**
with Vercel Authentication so only you can use it (and trigger Google API calls).

---

## 1. Prerequisites

- The repo pushed to GitHub (Vercel deploys from it).
- A Vercel account (Hobby/free is fine).
- A Google Cloud API key with **Places API (New)** and **Geocoding API** enabled,
  restricted to just those two APIs. (This is the key already in your local `.env`.)

## 2. Import the project

1. Vercel dashboard → **Add New… → Project** → import the Chompers GitHub repo.
2. Framework preset: **Other** (the included `vercel.json` already sets the build
   command and output directory — leave them as detected).
3. Don't deploy yet — add the environment variables first (next step).

## 3. Environment variables

Project → **Settings → Environment Variables** (set for Production and Preview):

| Name | Value |
|------|-------|
| `GOOGLE_MAPS_API_KEY` | your Google key |
| `PLACES_PROVIDER` | `google` |
| `GEOCODE_COUNTRY_CODES` | `us` (or leave unset for international) |

You do **not** need `ALLOWED_ORIGINS` (same origin) or `CACHE_DIR` (auto-defaults to
`/tmp` on Vercel). Leave `TRUSTED_PROXY_COUNT` unset.

Then **Deploy**.

## 4. Make it private (the main cost control)

After the first deploy: Project → **Settings → Deployment Protection → Vercel
Authentication** → enable it for **All Deployments**.

Now the whole site *and* the `/api` functions require a Vercel login you control, so
no bot or stranger can reach it or spend your Google quota. To let a specific person
in, invite them to the project.

## 5. Verify

- Open the deployment URL (logged into Vercel) → the app loads.
- `https://<your-app>.vercel.app/api/health` → `{"provider": "google", ...}`.
  - If this returns `{"detail":"Not Found"}`, the request reached FastAPI but the
    path was wrong. The backend lives at `api/[...path].py` — a **catch-all**, so
    Vercel preserves the real path. Do **not** rename it to `index.py` and do
    **not** add an `/api/(.*)` rewrite: rewrite destinations are fixed strings that
    discard the path, so every route would 404.
  - If the **frontend** 404s, check that no `requirements.txt` has reappeared at the
    repo root — that makes Vercel treat the project as a backend framework and route
    static requests into Python. Python deps belong in `api/requirements.txt`.
- Run a search; try a misspelled city like `San Fransisco CA` → resolves to
  California (confirms both Google APIs work).
- Open the URL in a **private/incognito window** (logged out) → you should hit the
  Vercel login wall. That confirms it's truly private.

---

## Cost controls & kill switches

The site is private, so only your own searches ever hit Google — spend should be ~$0
and well within Google Maps' monthly free allotment. Extra safety:

- **Budget alert (optional):** Google Cloud → Billing → **Budgets & alerts** → a $5
  budget with email alerts.
- **Instant "stop paying Google," site stays up:** set
  `PLACES_PROVIDER=openstreetmap` in Vercel env → redeploy → runs free on OSM
  (no ratings; occasional slow-query timeouts on Vercel's 10s limit).

## Teardown after ~1 week

1. Vercel → project → **Settings → Delete Project** (or pause) — site goes offline.
2. Google Cloud → **APIs & Services → Enabled APIs** → disable *Places API (New)* and
   *Geocoding API*, or delete the API key.
3. (Optional) Delete the Google Cloud project so nothing can ever bill.

---

## Notes / caveats (serverless)

- **Rate limiting** is in-memory and doesn't persist across serverless invocations,
  so it's ineffective on Vercel — which is fine because the site is private.
- **The response cache** lives in `/tmp` and is per-instance and ephemeral (resets on
  cold start). Purely an optimization; the app works without it.
- **10s function limit (Hobby):** Google responds in ~1s so this is comfortable.
  Overpass/OSM can exceed 10s, which is the other reason to run Google here.
- If you later want the stateful bits to work properly (shared rate limiting,
  persistent cache, long OSM timeouts), host the backend on a container platform
  (Fly/Render) and keep the frontend on Vercel.
