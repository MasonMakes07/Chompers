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

## Stack

Python + FastAPI backend, React + Vite + TypeScript frontend, Google Places
API (New) for restaurant data.

## Setup

1. Enable **Places API (New)** and **Geocoding API** in Google Cloud, create a
   restricted key, and **set a ~100/day quota cap**.
2. Copy `.env.example` to `.env` and add `GOOGLE_MAPS_API_KEY`.
3. Install and run:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload

cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`.

## Cost

One search = one Google API call, and 5,000 are free per month. At normal use
this costs nothing; the quota cap makes overage impossible rather than merely
unlikely.

## Tests

```bash
python -m pytest backend/tests -q
```

The API key is never needed for tests and never reaches the browser.
