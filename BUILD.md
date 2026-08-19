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
| Data provider | **OpenStreetMap** — no API key, no billing, no account |
| Full test suite | **126 tests passing** (6 files, includes API-level tests) |
| TypeScript compilation | **Passing** under `strict` + `noUnusedLocals` |
| Production bundle | **Builds** — 180.37 kB JS (58.69 kB gzip), 10.98 kB CSS |
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
│  │  ├─ places_client.py    OpenStreetMap via Overpass, cached and paced
│  │  ├─ osm_tags.py         OSM tags -> the scorer's existing vocabulary
│  │  └─ geocoder.py         ZIP/city -> coordinates via Nominatim, cached
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
      ├─ SearchBar.tsx       pill quick search in the brand bar
      ├─ PartyForm.tsx       stepper, guests, location, filters
      ├─ GuestRow.tsx        avatar, restriction summary, expandable chips
      └─ ResultCard.tsx      ranked row: rank, score badge, guest badges
```

Two files are **orphaned by the redesign** and safe to delete:
`components/LocationPicker.tsx` (absorbed into `PartyForm`) and
`components/MatchBadge.tsx` (absorbed into `ResultCard`). Both are
unreferenced and still target CSS classes that no longer exist.

### Visual design

Sage-to-mint gradient page, off-white cards with soft shadows, forest green
primary, Poppins via Google Fonts. Group-fit scores render as a colored badge
banded by value — forest ≥96, gold ≥86, rose below.

**The design mockups showed star ratings and price levels, which
OpenStreetMap does not have.** Those elements are built and will render if a
provider ever supplies them, but they collapse cleanly on live OSM data, so
result rows show cuisine and distance rather than `★ 4.8 · $$`.

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

## The provider swap: Google → OpenStreetMap

Google billing could not be enabled (`OR_BACR2_44`, no self-service fix), so
the app now runs on **OpenStreetMap**. It needs no key, no card, and no
account — clone and run.

**The swap touched three files.** `Restaurant` was provider-agnostic by
design, so the scorer, translator, schemas, middleware, and the entire
frontend were untouched:

| File | Change |
|---|---|
| `services/places_client.py` | Google Places → Overpass API |
| `services/geocoder.py` | Google Geocoding → Nominatim |
| `services/osm_tags.py` | **New.** Maps OSM tags into the existing vocabulary |

**`osm_tags.py` is what made this cheap.** OSM describes a restaurant with
`amenity` and `cuisine` tags; `dietary_rules.py` is written against
Google-style types like `indian_restaurant`. Mapping one to the other means
the 47-cuisine knowledge table kept working with **zero changes**. A test
(`test_every_mapped_type_is_known_to_the_rules_table`) asserts every mapped
type actually exists in that table, so a typo can't silently score neutral.

### Dietary evidence got better

Google exposed exactly one dietary field: a vegetarian boolean. OSM publishes
structured `diet:*` tags covering **six of our eight restrictions**
(vegetarian, vegan, gluten-free, dairy-free, halal, kosher) with values
`only` / `yes` / `limited` / `no`. All become tier-1 `EXPLICIT` evidence.

Nut and shellfish allergies have no OSM tag and stay on cuisine priors —
which is where they were under Google anyway.

### What was lost, and how it was handled

OSM has **no ratings and no price levels**. Rather than leave `rating_score()`
returning a neutral `0.5` for every candidate — a dead constant that
compresses the spread while contributing nothing — `score_restaurant()` now
builds only the components with real data and **renormalizes by the weights
actually used**. The missing 20% redistributes onto group fit and distance.

A test asserts distance still meaningfully separates results
(`test_missing_ratings_do_not_flatten_the_spread`).

### Being a good citizen

Overpass and Nominatim are free volunteer services, so the cost here is
politeness rather than money:

- An identifying `User-Agent` on every request, as both policies require
- Requests serialized behind a lock with a **1 req/sec floor** — Nominatim's
  hard limit
- Results cached 15 minutes; geocodes cached permanently (a ZIP's
  coordinates never change)
- Result count and query timeout bounded in the Overpass QL itself

---

## Security, verified

| Control | Status |
|---|---|
| **No secrets at all** | The app now uses no API key, so there is nothing to leak |
| `.env` gitignored | **Verified** — `git check-ignore` matches `.gitignore:2` |
| `.env` untracked | **Verified** — absent from `git ls-files` and `git status` |
| No key in compiled bundle | **Verified** — `frontend/dist/` scanned after a real production build, zero matches |
| **Overpass injection** | User queries are stripped to `[A-Za-z0-9 ]`, capped at 4 words, and joined into an alternation — no quote, backslash, bracket, or semicolon can survive into the query |
| Rate limiting | Per-IP, 10/min default — protects the Google quota |
| Input sanitization | Code-like input rejected, not escaped (`CODE_LIKE_PATTERN`) |
| Bounds | Guests 1–20, radius 500–50,000 m, coordinates range-checked |
| Security headers | `nosniff`, `DENY` framing, `no-referrer`, restrictive `Permissions-Policy` |

---

## Test coverage — 126 passing

**The headline test passes:** `test_one_vegan_outweighs_four_omnivores_and_a_better_rating`
— 4 omnivores + 1 vegan rank a 4.2★ Indian restaurant above a 4.9★ steakhouse.
The complement also passes: with no restrictions, the steakhouse wins on rating.

Also covered: hard-floor disqualification, non-empty fallback, allergy-vs-diet
asymmetry, evidence-tier precedence, Bayesian rating damping, and edge cases —
empty candidate list, zero guests, one guest holding **every** restriction,
restaurants missing rating/price/types, and hostile input rejection.

**Quick search** (`test_quick_search.py`, 18 tests): query optional so plain
nearby search still works, blank queries normalize to `None`, whitespace
collapsed, overlong queries rejected, and hostile input blocked — including
`<script>`, SQL injection, `${GOOGLE_MAPS_API_KEY}`, and `javascript:` URIs.
Cache keys are verified to separate different queries at the same coordinates
while still collapsing case and padding onto one entry.

**OpenStreetMap layer** (`test_osm.py`, 24 tests): cuisine→type mapping,
including an assertion that *every* mapped type exists in the dietary rules
table; `diet:*` extraction with conflict resolution and the vegan→vegetarian
implication; explicit tags outranking cuisine priors; and Overpass injection
safety, checking that payloads like `sushi"];out;//` and `sushi[amenity=bar]`
survive sanitization with no syntax characters intact. Ranking is verified to
still work, and still spread, with no ratings present anywhere.

---

## Running it

**No setup at all.** No API key, no billing account, no `.env` required.
Dependencies are already installed:

```bash
# Terminal 1 - backend
python -m uvicorn backend.main:app --reload

# Terminal 2 - frontend
cd frontend && npm run dev
```

Then open `http://localhost:5173`.

**Verify end-to-end:**
- `http://127.0.0.1:8000/api/health` → `provider: openstreetmap`
- Quick search "sushi" from the home page → lands on `/search?q=sushi`
- Refresh that results page → the search reruns from the URL
- Browser Back → returns to home, party intact
- Add a vegan guest, then search; confirm steakhouses are excluded

---

## Honest caveats

- **Dietary priors are informed estimates, not measurements.** They are my
  judgments about cuisines and will need tuning against real results. All 47
  rows live in one table, so adjusting them is cheap.
- **Party size is not verified.** No provider has a capacity field; large
  parties get a call-ahead warning instead.
- **No ratings, at all.** OSM has none, so nothing here reflects whether a
  restaurant is actually any *good* — only whether the group can eat there.
  This is the real cost of the provider swap, and it is not small.
- **OSM coverage is uneven.** Data is contributed by volunteers, so dense
  cities are well covered while some areas are sparse or stale. A restaurant
  that closed last year may still appear. Dietary tags exist on a minority of
  places — the cuisine priors carry most of the load, as designed.
- **The app has never made a real Overpass or Nominatim call.** Every test
  uses synthetic data. `search_nearby()`, `search_text()`, and
  `Geocoder.resolve()` are written against the documented API shapes but have
  not been exercised live — the most likely place for a first-run surprise.
- **The UI has been compiled but never rendered in a browser.** The build
  passes; visual layout, the geolocation prompt, and the Back-button behavior
  are unverified.
- **Overpass is a shared volunteer service.** It can be slow or rate-limit us
  under load, and a large radius may time out. Errors are surfaced with plain
  explanations rather than raw status codes.
- **A shared `/search` link does not carry guests.** Restrictions live in
  `sessionStorage`, not the URL, so someone opening your link gets the same
  query and location but ranked with no restrictions. This was deliberate —
  a friend's allergy list does not belong in a URL — but it does mean shared
  links rank differently than what you saw.
