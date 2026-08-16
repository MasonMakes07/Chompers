# Chompers — Plan

The design decided before implementation. `BUILD.md` records what was actually
built; this file records what was intended and why.

---

## Problem

Picking a restaurant for a group is a constraint-satisfaction problem that
people solve badly by hand. One friend is vegan, another has a nut allergy,
someone keeps halal — and the group defaults to whatever is easiest, which
usually means one person eats a side salad.

**Goal:** take a guest list, each person's restrictions, and a location, then
return the **top 5 nearby restaurants where everyone can actually eat**.

---

## Decisions made before building

| Decision | Choice | Why |
|---|---|---|
| Data source | **Google Places API (New)** | See the research below — it is the only free option with ratings |
| Group input | One person enters everyone | No accounts, no database, no shareable-link infrastructure |
| Location | Geolocation first, typed ZIP fallback | Fastest common path, with an override that always works |
| Backend | Python + FastAPI | Async, auto-generated `/docs`, matches existing project conventions |
| Frontend | React + Vite + TypeScript | Type-safe wire contracts against the Pydantic schemas |

### Data source research

The first choice was Yelp, because Yelp has real `vegan` / `gluten_free` /
`halal` / `kosher` category filters. That turned out to be impossible:

| Provider | Real cost at this volume | Verdict |
|---|---|---|
| **Google Places** | **$0** — 5,000 free Nearby Search calls/month | **Chosen.** Card required, neutralized by a quota cap |
| Yelp Fusion | 30-day trial, then **$229/month minimum** | Rejected. Free tier discontinued |
| Foursquare | Ratings/hours are Premium, **$18.75/1,000, no free tier** | Rejected |
| OpenStreetMap | $0, no signup at all | Rejected. No ratings; `diet:*` tags on only ~7.6% of places |

Sources: [Google pricing](https://developers.google.com/maps/billing-and-pricing/pricing),
[Yelp pricing](https://business.yelp.com/data/products/fusion/),
[OSM diet tags](https://wiki.openstreetmap.org/wiki/Key:diet)

**Cost control:** one user search = **one** Google API call. The ~20 places it
returns are ranked locally. Burning the free tier would take ~165 searches per
day, every day. Combined with a Cloud Console quota cap, overage is impossible
rather than merely unlikely.

---

## Known limitation, designed around rather than hidden

Google exposes **no party-size or capacity field**. Guest count therefore
cannot genuinely filter results.

Rather than fake it, guest count is used honestly:
- it triggers a "call ahead for a party of N" warning at 6+ guests, and
- the UI never claims seating was verified.

---

## The matching algorithm

Everything else is plumbing. This is the product.

### 1. Evidence tiers

For a restaurant and one restriction, confidence comes from the strongest
available evidence:

| Tier | Signal | Example |
|---|---|---|
| 1 `EXPLICIT` | Provider flag | `servesVegetarianFood: true` |
| 2 `KEYWORD` | Name self-declaration | "Halal Grill House" |
| 3 `CUISINE` | Knowledge-table prior | `indian_restaurant` → vegetarian 0.95 |
| 4 `DEFAULT` | Nothing known | neutral 0.5, flagged as uncertain |

Only tier 1 is shown to the user as verified. Everything else is labeled an
inference.

### 2. Allergies are not diets

A diet asks *"is there something on the menu for me"*. An allergy asks *"will
this kitchen make me sick"*. They must be scored differently:

- Thai scores **0.85 vegetarian** but **0.20 nut allergy** — peanut-heavy
  kitchen, cross-contamination risk.
- Buffets score well on menu breadth but poorly on every allergy, because
  serving utensils are shared.
- When a restaurant has several cuisine types, **allergies take the most
  cautious prior; diets take the most generous one.**

Halal and kosher require active certification, so they get a low default and
are never assumed from silence.

### 3. Group aggregation — "no one left behind"

The central design choice. A plain average lets four happy diners drown out one
who cannot eat, which is exactly the failure this app exists to prevent:

```
group_fit = 0.6 * min(guest confidences) + 0.4 * mean(guest confidences)
```

The `min` term dominates. Any guest below `HARD_FLOOR = 0.25` disqualifies the
restaurant outright.

### 4. Final score

```
score = 0.55 * group_fit
      + 0.20 * rating          (Bayesian-damped by review count)
      + 0.10 * distance_decay
      + 0.10 * cuisine_preference
      + 0.05 * price_fit
```

---

## Security requirements

- API key **server-side only** — the browser never calls Google directly.
- `.env` gitignored from the first commit; `.env.example` documents the shape.
- Fail fast at startup if the key is missing.
- Middleware layer: per-IP rate limit (protects the Google quota), request-size
  cap, strict CORS allowlist, security headers.
- Every input bounded by Pydantic; restrictions constrained to an enum.
- Free text matching code-like patterns is **rejected, not escaped**.

---

## Build order

Steps 1–4 need no API key, so the core is testable before any Google setup.

1. Scaffold, `.gitignore`, `.env.example`
2. Models — `Guest`, `Party`, `Restaurant` (pure data, no I/O)
3. `dietary_rules.py` — the knowledge table
4. `scorer.py` — ranking, tested against synthetic restaurants, **no network**
5. `places_client.py` + `geocoder.py` — real Google calls, cached
6. `translator.py` + `middleware.py` + `main.py`
7. Frontend
8. Polish — loading, empty, and error states

---

## Verification plan

- **The headline test:** a party of 4 omnivores + 1 vegan must rank an Indian
  restaurant above a *higher-rated* steakhouse. If that fails, the `min`
  weighting is wrong and the whole premise is broken.
- Edge cases: zero guests, one guest with every restriction, all candidates
  disqualified, missing rating/price/type fields, empty candidate list.
- Security: confirm the key appears in no frontend file, and `.env` is
  untracked before any commit.
- End-to-end: real location, 5 results with per-guest badges.
