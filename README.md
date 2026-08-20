# Chompers

Find a restaurant where **everyone** in your group can actually eat.

Enter your headcount and each friend's dietary restrictions, and Chompers ranks
the top 5 nearby restaurants by how well they serve the *whole* party — not the
average of it.

In a hurry? Use the quick search bar — type "sushi" or "vegan brunch" and get
ranked results without setting up a party first. If you have added guests,
their restrictions still apply.

## The idea

Most restaurant apps rank by stars, so a group of five with one vegan ends up
at the highest-rated steakhouse and one person eats a side salad. Chompers
weights the **worst-served guest** at 60% of the group score, so a restaurant
that fails one person cannot win on everyone else's behalf.

It also treats allergies differently from diets: a diet asks "is there
something on the menu for me", an allergy asks "will this kitchen make me
sick". Thai food scores well for vegetarians and badly for nut allergies.

## Docs

- **[PLAN.md](PLAN.md)** — the design and the reasoning behind it
- **[BUILD.md](BUILD.md)** — what was built, what is verified, what is not
- **[DEPLOY.md](DEPLOY.md)** — deploying to Vercel (private, Google provider)

## Stack

Python + FastAPI backend, React + Vite + TypeScript frontend. Restaurant data comes
from **Google Places** (ratings + prices; needs a key) or **OpenStreetMap** (Overpass
+ Nominatim; keyless fallback), selected by `PLACES_PROVIDER`.

## Setup

Runs **keyless out of the box** — with no key it falls back to OpenStreetMap. Clone
and run:

```bash
python -m pip install -r requirements-dev.txt
python -m uvicorn backend.main:app --reload

cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`.

To use **Google Places** instead (ratings, price levels, faster), copy
`.env.example` to `.env`, add `GOOGLE_MAPS_API_KEY`, and set `PLACES_PROVIDER=google`.

## Cost

Free, permanently. OpenStreetMap's Overpass and Nominatim are public,
keyless services. The app is a polite client: requests are paced to one per
second, results are cached, and every query is bounded.

The tradeoff is that OSM carries **no star ratings or price levels**, so
results are ranked on dietary fit, cuisine match, and distance rather than
popularity. In exchange, OSM publishes structured `diet:*` tags covering six
of the eight restrictions as first-party data — better dietary evidence than
the commercial APIs offer.

## Tests

```bash
python -m pytest backend/tests -q
```

126 tests, all on synthetic data — no network calls, nothing to configure.
