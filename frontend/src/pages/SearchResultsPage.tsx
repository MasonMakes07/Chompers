// Results: a distinct screen driven entirely by the URL query string.

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ResultCard } from "../components/ResultCard";
import { SearchBar } from "../components/SearchBar";
import { RateLimitError, searchRestaurants } from "../api/client";
import { useParty } from "../context/PartyContext";
import { buildSearchPath, parseSearchParams } from "../searchParams";
import { RESTRICTIONS, type SearchResponse } from "../types";

// How many ranked results are shown before "Load more".
const SHORTLIST_SIZE = 5;

// How many are actually ranked and returned, so expanding needs no request.
// Google returns up to 20 per call at the same cost, so ranking all of them
// (not just 10) costs no extra API call and leaves a fuller shortlist when
// heavy dietary filtering excludes many candidates.
const RANKED_POOL_SIZE = 20;

// How many places a keyword browse returns.
const BROWSE_SIZE = 20;

// Turns a radius in meters into the same label the form offers.
function radiusLabel(meters: number): string {
  const miles = Math.round(meters / 1609.34);
  return `Within ${miles < 1 ? "1" : miles} mi`;
}

export function SearchResultsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { guestCount, guests, coordinates } = useParty();

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [isSearching, setIsSearching] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Ranks beyond the first five are fetched with them and held back, so
  // revealing them costs no network round trip. A second request would be slower.
  const [visibleCount, setVisibleCount] = useState(SHORTLIST_SIZE);
  // Sort and filter apply client-side to the already-fetched pool, so neither
  // control ever costs another API call.
  const [sortBy, setSortBy] = useState<"best" | "rating" | "distance">("best");
  const [openNowOnly, setOpenNowOnly] = useState(false);
  // Non-null while a 429 countdown is running; the nonce re-fires the search.
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  // The URL is the single source of truth, so a refresh reruns the search.
  const paramsKey = searchParams.toString();

  // The party is NOT in the URL, so changing a restriction and searching
  // again can produce an identical path. Without this key the effect would
  // not re-run and the page would show results for the old restrictions.
  const partyKey = JSON.stringify([
    guestCount,
    guests.map((guest) => [
      guest.name.trim(),
      [...guest.restrictions].sort(),
      [...guest.likedCuisines].sort(),
      [...guest.dislikedCuisines].sort(),
    ]),
  ]);

  // StrictMode double-invokes this effect in dev, firing two fetches. That is
  // fine: the `isCurrent` cleanup discards the stale first pass, and the
  // backend collapses the duplicate into a single upstream call. The live
  // pass renders. (A ref guard here instead would suppress the live pass and
  // leave the page stuck on the skeleton.)
  useEffect(() => {
    const state = parseSearchParams(new URLSearchParams(paramsKey));
    const searchCoordinates = state.coordinates ?? coordinates;
    let isCurrent = true;

    // Runs the search described by the current URL and stores the outcome.
    const run = async () => {
      setIsSearching(true);
      setErrorMessage(null);
      setRetrySeconds(null);
      // A new search starts collapsed again.
      setVisibleCount(SHORTLIST_SIZE);

      if (!searchCoordinates && !state.locationQuery) {
        setErrorMessage("No location set. Go back and choose where to search.");
        setIsSearching(false);
        return;
      }

      // A typed query is a generic browse: show plenty of nearby places and
      // do NOT rank them against the party. The group shortlist is what the
      // planner's "Find our top 5" is for, and mixing the two made a simple
      // "sushi" lookup silently drop places a guest could not eat at.
      const isBrowse = state.query.length > 0;

      try {
        const result = await searchRestaurants({
          query: state.query || undefined,
          guest_count: isBrowse ? 1 : guestCount,
          guests: isBrowse
            ? []
            : guests.map((guest) => ({
                name: guest.name.trim() || "Guest",
                restrictions: guest.restrictions,
                liked_cuisines: guest.likedCuisines,
                disliked_cuisines: guest.dislikedCuisines,
              })),
          limit: isBrowse ? BROWSE_SIZE : RANKED_POOL_SIZE,
          latitude: state.locationQuery
            ? undefined
            : searchCoordinates?.latitude,
          longitude: state.locationQuery
            ? undefined
            : searchCoordinates?.longitude,
          location_query: state.locationQuery || undefined,
          radius_meters: state.radiusMeters,
          max_price_level: state.maxPriceLevel,
        });
        if (isCurrent) setResponse(result);
      } catch (error) {
        if (isCurrent) {
          setResponse(null);
          // Throttling is recoverable: show a countdown and retry, rather than
          // surfacing it as a dead-end error the user has to act on.
          if (error instanceof RateLimitError) {
            setRetrySeconds(error.retryAfterSeconds);
          } else {
            setErrorMessage(
              error instanceof Error ? error.message : "Something went wrong."
            );
          }
        }
      } finally {
        if (isCurrent) setIsSearching(false);
      }
    };

    void run();

    // Guards against a slow earlier search overwriting a newer one.
    return () => {
      isCurrent = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey, partyKey, retryNonce]);

  // Ticks the rate-limit countdown once a second, then re-fires the search by
  // bumping the retry nonce when it reaches zero.
  useEffect(() => {
    if (retrySeconds === null) return;
    if (retrySeconds <= 0) {
      setRetrySeconds(null);
      setRetryNonce((nonce) => nonce + 1);
      return;
    }
    const timer = window.setTimeout(() => {
      setRetrySeconds((seconds) => (seconds === null ? null : seconds - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [retrySeconds]);

  const state = parseSearchParams(searchParams);

  // A typed query browses places; no query means rank the party's shortlist.
  const isBrowse = state.query.length > 0;

  // Every distinct restriction in the party, for the summary chips.
  const activeRestrictions = RESTRICTIONS.filter((restriction) =>
    guests.some((guest) => guest.restrictions.includes(restriction.id))
  );

  // Only meaningful for a group shortlist, and only when nobody is limited.
  const everyoneFits =
    !isBrowse &&
    response !== null &&
    response.results.length > 0 &&
    response.results[0].guest_fits.every((fit) => fit.status === "good");

  // Sort/filter the already-fetched pool. "best" keeps the backend's own score
  // order. Memoized so the once-a-second retry re-render does not re-sort.
  const processedResults = useMemo(() => {
    if (response === null) return [];
    const filtered = openNowOnly
      ? response.results.filter((result) => result.open_now === true)
      : response.results;
    const sorted = [...filtered];
    if (sortBy === "rating") {
      sorted.sort((first, second) => (second.rating ?? 0) - (first.rating ?? 0));
    } else if (sortBy === "distance") {
      sorted.sort(
        (first, second) => first.distance_meters - second.distance_meters
      );
    }
    return sorted;
  }, [response, sortBy, openNowOnly]);

  // Re-runs the search from the bar at the top of this page.
  const runSearch = (query: string, locationQuery: string) => {
    navigate(
      buildSearchPath({
        query,
        locationQuery,
        coordinates,
        radiusMeters: state.radiusMeters,
        maxPriceLevel: state.maxPriceLevel,
      })
    );
  };

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Chompers
        </Link>
        <div className="topbar__search">
          <SearchBar
            initialQuery={state.query}
            initialLocation={state.locationQuery}
            onSearch={runSearch}
          />
        </div>
      </header>

      <section className="results-card">
        <div className="results-head">
          <h1 className="results-title">
            {isBrowse
              ? `“${state.query}”`
              : // Say how many are actually on screen. With several
                // restrictions most nearby places get ruled out, and calling
                // one result a "top 5" is simply untrue.
                `Your top ${Math.min(
                  visibleCount,
                  processedResults.length || SHORTLIST_SIZE
                )}`}
          </h1>
          {everyoneFits && (
            <span className="everyone-badge">Everyone can eat here ✓</span>
          )}
        </div>

        <div className="summary-chips">
          {isBrowse ? (
            <>
              <span className="summary-chip">Places to eat</span>
              <span className="summary-chip">
                {radiusLabel(state.radiusMeters)}
              </span>
            </>
          ) : (
            <>
              <span className="summary-chip">
                {guestCount} {guestCount === 1 ? "person" : "people"}
              </span>
              <span className="summary-chip">
                {radiusLabel(state.radiusMeters)}
              </span>
              {activeRestrictions.map((restriction) => (
                <span key={restriction.id} className="summary-chip">
                  {restriction.label}
                </span>
              ))}
            </>
          )}
        </div>

        {isBrowse && (
          <p className="browse-note">
            Browsing all matches — not filtered for anyone's restrictions.{" "}
            <Link to="/">Plan for your group instead →</Link>
          </p>
        )}

        {errorMessage && (
          <div
            className="alert alert--error"
            role="alert"
            style={{ marginTop: "1.5rem" }}
          >
            {errorMessage}
          </div>
        )}

        {retrySeconds !== null && (
          <div
            className="alert alert--retry"
            role="status"
            style={{ marginTop: "1.5rem" }}
          >
            Too many searches — retrying in {retrySeconds}s…
          </div>
        )}

        {isSearching && (
          <div className="skeleton-list">
            {[0, 1, 2, 3, 4].map((index) => (
              <div key={index} className="skeleton" />
            ))}
          </div>
        )}

        {response && !isSearching && (
          <>
            {response.results.length > 0 && (
              <div className="results-toolbar">
                <label className="results-toolbar__sort">
                  <span>Sort</span>
                  <select
                    value={sortBy}
                    aria-label="Sort results"
                    onChange={(event) =>
                      setSortBy(
                        event.target.value as "best" | "rating" | "distance"
                      )
                    }
                  >
                    <option value="best">Best match</option>
                    <option value="rating">Rating</option>
                    <option value="distance">Distance</option>
                  </select>
                </label>
                <button
                  type="button"
                  className={`toolbar-toggle ${
                    openNowOnly ? "toolbar-toggle--on" : ""
                  }`}
                  aria-pressed={openNowOnly}
                  onClick={() => setOpenNowOnly((on) => !on)}
                >
                  Open now
                </button>
              </div>
            )}

            <div className="result-list">
              {processedResults.slice(0, visibleCount).map((result, index) => (
                <ResultCard
                  key={result.place_id || result.name}
                  result={result}
                  rank={index + 1}
                  showGroupFit={!isBrowse}
                />
              ))}
            </div>

            {processedResults.length > visibleCount && (
              <button
                type="button"
                className="load-more"
                onClick={() => setVisibleCount(processedResults.length)}
              >
                Load more
                <span className="load-more__count">
                  {processedResults.length - visibleCount} more already ranked
                </span>
              </button>
            )}

            {processedResults.length === 0 && (
              <div className="empty-state" role="status">
                <span className="empty-state__icon" aria-hidden="true">
                  🍽️
                </span>
                <p className="empty-state__title">
                  {openNowOnly && response.results.length > 0
                    ? "Nothing's open right now"
                    : "Nothing came back for that search"}
                </p>
                <p className="empty-state__body">
                  {openNowOnly && response.results.length > 0
                    ? "Turn off “Open now”, or widen your search."
                    : "Try a wider radius or a broader term."}
                </p>
                {openNowOnly && response.results.length > 0 ? (
                  <button
                    type="button"
                    className="empty-state__cta"
                    onClick={() => setOpenNowOnly(false)}
                  >
                    Show all places
                  </button>
                ) : (
                  <Link to="/" className="empty-state__cta">
                    Edit party &amp; search
                  </Link>
                )}
              </div>
            )}

            <ul className="notes">
              <li>
                Searched near {response.searched_location} —{" "}
                {response.candidates_considered} places considered.
              </li>
              {response.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </>
        )}

        <p className="results-footer">
          <Link to="/">← Edit party and search again</Link>
        </p>
      </section>
    </>
  );
}
