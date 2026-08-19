// Results: a distinct screen driven entirely by the URL query string.

import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ResultCard } from "../components/ResultCard";
import { SearchBar } from "../components/SearchBar";
import { searchRestaurants } from "../api/client";
import { useParty } from "../context/PartyContext";
import { buildSearchPath, parseSearchParams } from "../searchParams";
import { RESTRICTIONS, type SearchResponse } from "../types";

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

  // The URL is the single source of truth, so a refresh reruns the search.
  const paramsKey = searchParams.toString();

  // The party is NOT in the URL, so changing a restriction and searching
  // again can produce an identical path. Without this key the effect would
  // not re-run and the page would show results for the old restrictions.
  const partyKey = JSON.stringify([
    guestCount,
    guests.map((guest) => [guest.name.trim(), [...guest.restrictions].sort()]),
  ]);

  useEffect(() => {
    const state = parseSearchParams(new URLSearchParams(paramsKey));
    const searchCoordinates = state.coordinates ?? coordinates;
    let isCurrent = true;

    // Runs the search described by the current URL and stores the outcome.
    const run = async () => {
      setIsSearching(true);
      setErrorMessage(null);

      if (!searchCoordinates && !state.locationQuery) {
        setErrorMessage("No location set. Go back and choose where to search.");
        setIsSearching(false);
        return;
      }

      try {
        const result = await searchRestaurants({
          query: state.query || undefined,
          guest_count: guestCount,
          guests: guests.map((guest) => ({
            name: guest.name.trim() || "Guest",
            restrictions: guest.restrictions,
          })),
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
          setErrorMessage(
            error instanceof Error ? error.message : "Something went wrong."
          );
          setResponse(null);
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
  }, [paramsKey, partyKey]);

  const state = parseSearchParams(searchParams);

  // Every distinct restriction in the party, for the summary chips.
  const activeRestrictions = RESTRICTIONS.filter((restriction) =>
    guests.some((guest) => guest.restrictions.includes(restriction.id))
  );

  // True only when no guest is poorly served by the top-ranked option.
  const everyoneFits =
    response !== null &&
    response.results.length > 0 &&
    response.results[0].guest_fits.every((fit) => fit.status === "good");

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
            {state.query ? `Results for “${state.query}”` : "Your top 5"}
          </h1>
          {response !== null && response.results.length > 0 && (
            <span
              className={`everyone-badge ${
                everyoneFits ? "" : "everyone-badge--partial"
              }`}
            >
              {everyoneFits ? "Everyone can eat here ✓" : "Some limits — see notes"}
            </span>
          )}
        </div>

        <div className="summary-chips">
          <span className="summary-chip">
            {guestCount} {guestCount === 1 ? "person" : "people"}
          </span>
          <span className="summary-chip">{radiusLabel(state.radiusMeters)}</span>
          {activeRestrictions.map((restriction) => (
            <span key={restriction.id} className="summary-chip">
              {restriction.label}
            </span>
          ))}
        </div>

        {errorMessage && (
          <div className="alert alert--error" style={{ marginTop: "1.5rem" }}>
            {errorMessage}
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
            <div className="result-list">
              {response.results.map((result, index) => (
                <ResultCard
                  key={result.place_id || result.name}
                  result={result}
                  rank={index + 1}
                />
              ))}
            </div>

            {response.results.length === 0 && (
              <div className="alert" style={{ marginTop: "1.5rem" }}>
                Nothing came back for that search. Try a wider radius or a
                broader term.
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
