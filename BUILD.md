# Chompers — What Was Built

Companion to `PLAN.md`. That file is the intent; this file is the delivery,
including what is verified and what is not.

---

## Status

| Area | State |
|---|---|
| Backend (models, matching, services, API) | Complete |
| Frontend (React + Vite + TypeScript) | Complete, **installed and builds clean** |
| Quick search + routed results page | Complete |
| Full test suite | **93 tests passing** (5 files, includes 7 API-level tests) |
| TypeScript compilation | **Passing** under `strict` + `noUnusedLocals` |
| Production bundle | **Builds** — 180.14 kB JS (58.60 kB gzip), 10.85 kB CSS |
| End-to-end against real Google data | **Not yet run** — needs the setup below |

---

## File map

```
Chompers/
├─ .env                      your key (gitignored, verified untracked)
├─ .env.example              template
├─ .gitignore                .env is line 2
├─ PLAN.md                   design and reasoning
├─ BUILD.md                  this file
│
├─ backend/
│  ├─ config.py              env loading; checks backend/.env AND root .env
│  ├─ main.py                FastAPI app, routes, middleware wiring
│  ├─ middleware.py          rate limit, size cap, security headers
│  ├─ translator.py          the ONLY frontend<->backend conversion point
│  ├─ schemas.py             Pydantic contracts + input sanitization
│  ├─ models/
│  │  ├─ guest.py            Guest + Restriction enum (8 restrictions)
│  │  ├─ party.py            Party, large-party threshold
│  │  └─ restaurant.py       provider-agnostic place + haversine distance
│  ├─ matching/
│  │  ├─ dietary_rules.py    47-cuisine knowledge table
│  │  └─ scorer.py           evidence tiers, group aggregation, ranking
│  ├─ services/
│  │  ├─ places_client.py    Google Places (New), cached
│  │  └─ geocoder.py         ZIP/city -> coordinates, cached
│  └─ tests/                 4 test files, 75 tests total
│
└─ frontend/src/
   ├─ App.tsx                route table + PartyProvider
   ├─ main.tsx               entry point, BrowserRouter
   ├─ types.ts               wire types mirroring schemas.py
   ├─ searchParams.ts        URL <-> search-state helpers
   ├─ api/client.ts          the only module that calls the backend
   ├─ context/
   │  └─ PartyContext.tsx    guests shared across routes + sessionStorage
   ├─ styles.css             warm palette, light + dark aware
   ├─ pages/
   │  ├─ HomePage.tsx        quick search + group planner
   │  └─ SearchResultsPage.tsx   results screen, driven by the URL
   └─ components/
      ├─ SearchBar.tsx       quick search (large on home, compact on results)
      ├─ PartyForm.tsx       headcount, guests, location, filters
      ├─ GuestRow.tsx        one guest's restriction chips
      ├─ LocationPicker.tsx  geolocation + ZIP fallback
      ├─ ResultCard.tsx      one ranked restaurant
      └─ MatchBadge.tsx      per-guest "can eat here" indicator
```

---

## Quick search and routing

Two screens, separated by real URLs via `react-router-dom`:

| Route | Screen |
|---|---|
| `/` | Home — quick search bar, group planner, explainer panel |
| `/search?q=sushi&loc=92093` | Results — compact search bar, ranked cards |

**No new endpoint.** `SearchRequest` gained an optional `query` field. When
present, `main.py` routes to Places **Text Search**; when absent, **Nearby
Search**. Same Translator, same scorer, same one-call-per-search cost.

Text Search uses `locationBias` rather than `locationRestriction`, so a strong
keyword match just outside the radius still appears — the right behavior when
someone explicitly typed "sushi".

**Restrictions carry over.** Quick searching with guests already added still
ranks by group fit; the results page says which mode it used. Guests live in
context plus `sessionStorage` rather than the URL, since a restriction list is
too personal to put in a shareable link. Location and filters do live in the
URL, so results are shareable, bookmarkable, and survive a refresh.

The query is sanitized by the same `reject_code_like` rule as every other free
text field, whitespace-collapsed for cache efficiency, and capped at 120 chars.

---

## What the matching engine actually does

**`dietary_rules.py`** — 47 Google place types scored against all 8
restrictions. Stored as a validated tuple table with a documented column order;
`_validate_table()` runs at import and raises if any row is the wrong width or
holds a value outside `[0, 1]`.

**Allergies scored separately from diets.** Thai is `0.85` vegetarian but
`0.20` for nut allergy. Buffets score well on breadth, badly on every allergy
(shared utensils). Where a place has several cuisine types, allergies take the
**minimum** prior and diets take the **maximum** — implemented in
`_cuisine_confidence()`.

**Halal and kosher are never assumed.** Both default to `< 0.2` for unknown
restaurants, because certification cannot be inferred from silence.

**Group aggregation** (`group_fit_score`):
`0.6 * min + 0.4 * mean`. The worst-served guest dominates. `HARD_FLOOR = 0.25`
disqualifies outright — but if that empties the list, the app falls back to
showing the closest matches with warnings rather than an empty page.

**Explainability.** Every result carries per-guest badges naming the limiting
restriction and its evidence. Only tier-1 provider flags render as verified;
everything else is marked *(inferred)*.

---

## Cost design

**One user search = one Google API call.** The ~20 returned places are ranked
locally, and responses are cached 15 minutes by rounded coordinates.

Enterprise dietary fields (`servesVegetarianFood`) are **opt-in via
`INCLUDE_DIETARY_FLAGS`, default off** — requesting them drops the free
allowance from 5,000 to 1,000 calls/month, and the cuisine priors cover the
same ground. Leave it off.

---

## Security, verified

| Control | Status |
|---|---|
| `.env` gitignored | **Verified** — `git check-ignore` matches `.gitignore:2` |
| `.env` untracked | **Verified** — absent from `git ls-files` and `git status` |
| No key in frontend source | **Verified** — zero matches for `AIza`, key name, or `googleapis.com` in `frontend/src/` |
| No key in compiled bundle | **Verified** — `frontend/dist/` scanned after a real production build, zero matches |
| Key confined to backend | `config.py` reads it; only `places_client.py:158` and `geocoder.py:43` send it |
| Single auth point | Both search modes funnel through one `_post_search()`, so the key is attached in exactly one place |
| Rate limiting | Per-IP, 10/min default — protects the Google quota |
| Input sanitization | Code-like input rejected, not escaped (`CODE_LIKE_PATTERN`) |
| Bounds | Guests 1–20, radius 500–50,000 m, coordinates range-checked |
| Security headers | `nosniff`, `DENY` framing, `no-referrer`, restrictive `Permissions-Policy` |

---

## Test coverage — 93 passing

**The headline test passes:** `test_one_vegan_outweighs_four_omnivores_and_a_better_rating`
— 4 omnivores + 1 vegan rank a 4.2★ Indian restaurant above a 4.9★ steakhouse.
The complement also passes: with no restrictions, the steakhouse wins on rating.

Also covered: hard-floor disqualification, non-empty fallback, allergy-vs-diet
asymmetry, evidence-tier precedence, Bayesian rating damping, and edge cases —
empty candidate list, zero guests, one guest holding **every** restriction,
restaurants missing rating/price/types, and hostile input rejection.

**Quick search** (`test_quick_search.py`, 18 tests): query optional so Nearby
Search still works, blank queries normalize to `None`, whitespace collapsed,
overlong queries rejected, and hostile input blocked — including
`<script>`, SQL injection, `${GOOGLE_MAPS_API_KEY}`, and `javascript:` URIs.
Cache keys are verified to separate different queries at the same coordinates
while still collapsing case and padding onto one entry.

---

## Remaining setup (needs your approval to run)

**1. Google Cloud, one time:**
- Enable **Places API (New)** and **Geocoding API**
- Create a key, restrict it to those two APIs
- **Set a ~100/day quota cap** — this is what makes overage impossible
- Confirm `GOOGLE_MAPS_API_KEY=...` is in your `.env`

**2. Run the app** (dependencies are already installed):

```bash
# Terminal 1 - backend
python -m uvicorn backend.main:app --reload

# Terminal 2 - frontend
cd frontend && npm run dev
```

Then open `http://localhost:5173`.

**3. Verify end-to-end:**
- `http://127.0.0.1:8000/api/health` → `api_key_configured: true`
- Quick search "sushi" from the home page → lands on `/search?q=sushi`
- Refresh that results page → the search reruns from the URL
- Browser Back → returns to home, party intact
- Add a vegan guest, then search; confirm steakhouses are excluded
- Check Cloud Console shows only a handful of calls consumed

---

## Honest caveats

- **Dietary priors are informed estimates, not measurements.** They are my
  judgments about cuisines and will need tuning against real results. All 47
  rows live in one table, so adjusting them is cheap.
- **Party size is not verified.** Google has no capacity field; large parties
  get a call-ahead warning instead.
- **The app has never made a real Google API call.** Every test uses synthetic
  data. `places_client.search_nearby()` and `Geocoder.resolve()` are written
  against the documented API shape but have not been exercised against the live
  service — the most likely place for a first-run surprise.
- **The UI has been compiled but never rendered in a browser.** The build
  passes; visual layout, the geolocation prompt, and the Back-button behavior
  are unverified.
- **Text Search returns different results than Nearby Search.** It uses
  `locationBias` instead of `locationRestriction`, so a quick search can
  surface a place slightly outside your radius. That is intentional for
  keyword searches, but it means the radius filter is a preference there
  rather than a hard boundary.
- **A shared `/search` link does not carry guests.** Restrictions live in
  `sessionStorage`, not the URL, so someone opening your link gets the same
  query and location but ranked with no restrictions. This was deliberate —
  a friend's allergy list does not belong in a URL — but it does mean shared
  links rank differently than what you saw.
