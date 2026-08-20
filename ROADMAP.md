# Chompers — Roadmap / Aspects to Add

Feature ideas for Chompers (a group restaurant matcher that ranks nearby places
by whole-group dietary fit). Ordered by leverage. Each item notes rough effort
and the code it touches.

---

## Highest leverage — backend already supports these

### 1. Per-guest cuisine likes / dislikes
- **Why:** The backend already accepts and scores `liked_cuisines` /
  `disliked_cuisines` per guest, but the UI never sends them — a dead capability.
  Improves match quality when dietary restrictions alone don't separate options.
- **Effort:** Low.
- **Touches:** `frontend/src/components/GuestRow.tsx` (add like/dislike chips),
  `frontend/src/types.ts` + the search request in
  `frontend/src/pages/SearchResultsPage.tsx`. Backend: `schemas.py`,
  `matching/scorer.py` (already wired).

### 2. Dietary fit as a positive signal (not just warnings)
- **Why:** `guest_fits` are computed per restriction, but the card mostly shows
  warnings. Positive chips ("vegan options ✓", "halal") build trust — the point
  of a dietary-safety app.
- **Effort:** Low–Medium.
- **Touches:** `frontend/src/components/ResultCard.tsx`, styles.

---

## Core product — the "group" in group-matcher

### 3. Shareable session link
- **Why:** The party currently lives in `sessionStorage` and dies with the tab.
  Letting each friend add their own restrictions from their own phone is the
  defining feature of a *group* tool. MVP: serialize the party into a URL that
  can be texted.
- **Effort:** Medium.
- **Touches:** `frontend/src/context/PartyContext.tsx`,
  `frontend/src/searchParams.ts` (or a new share-token module).

### 4. Map view of results
- **Why:** Backend returns `latitude`/`longitude` + `maps_uri` for every result;
  Leaflet + OpenStreetMap tiles need no API key. "Where is this relative to us?"
  is a group's first question, and `coordinates` is already in context.
- **Effort:** Medium.
- **Touches:** new map component on the results page; `RestaurantResult` already
  carries the coordinates.

### 5. Voting / "let the group pick"
- **Why:** Once results are shared, let members thumbs-up options and surface the
  consensus pick. Turns a ranked list into an actual decision.
- **Effort:** Medium–High (needs shared state; pairs with #3).

---

## Trust & safety (this app's identity)

### 6. "Confirm with the restaurant" affordance
- **Why:** For serious restrictions (allergies), a one-tap call/website link on
  the card makes acting on the existing disclaimer easy.
- **Effort:** Low.
- **Touches:** `frontend/src/components/ResultCard.tsx` (needs a phone/website
  field surfaced from the provider).

### 7. Explain *why* a place fits
- **Why:** The backend already returns `restriction_fits` with
  `reason`/`evidence`/`verified`. Expandable per-guest reasoning separates a guess
  ("cuisine-inferred") from a guarantee ("explicitly listed").
- **Effort:** Low–Medium.
- **Touches:** `frontend/src/components/ResultCard.tsx` (data already present).

---

## UX polish (mostly cheap)

### 8. Sort / filter on results
- Open now, price, distance, group fit — pure client-side on the already-fetched
  pool, **zero extra API calls**.
- **Touches:** `frontend/src/pages/SearchResultsPage.tsx`.

### 9. 429 retry countdown
- Backend now sends `Retry-After` and CORS exposes it. Turn the message into an
  auto-retry with a visible timer.
- **Touches:** `frontend/src/api/client.ts`, results page.

### 10. First-run onboarding / empty states
- A visual hook on the text-only hero, and a clear CTA when someone lands on
  `/search` with no party set.
- **Touches:** `frontend/src/pages/HomePage.tsx`, `SearchResultsPage.tsx`.

---

## Technical / ops (not user-facing)

### 11. Bound the geocoder caches
- `Geocoder._cache` / `_reverse_cache` grow forever — a slow memory leak. Add an
  LRU bound.
- **Touches:** `backend/services/geocoder.py`.

### 12. Dependency audit + CI
- Pinned deps + `pip-audit`, plus lightweight error logging so upstream failures
  are visible.

### 13. Geocode confidence gate
- `San Fransisco` (no state) resolves to a Colorado mountain pass because
  Nominatim finds a low-quality literal US match before the Google fallback
  fires. Prefer Google when Nominatim's match looks low-confidence.
- **Touches:** `backend/services/geocoder.py`.

---

## Suggested next move

- **#1 (cuisine prefs)** — fastest win; the backend is already done.
- **#3 (shareable session)** — highest ceiling; it's what makes the product
  actually "group."
