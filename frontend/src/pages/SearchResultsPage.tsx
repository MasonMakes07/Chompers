// Results: a distinct screen driven entirely by the URL query string.

import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ResultCard } from "../components/ResultCard";
import { SearchBar } from "../components/SearchBar";
import { searchRestaurants } from "../api/client";
import { useParty } from "../context/PartyContext";
import { buildSearchPath, parseSearchParams } from "../searchParams";
import type { SearchResponse } from "../types";

export function SearchResultsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { guestCount, guests, coordinates } = useParty();

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [isSearching, setIsSearching] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // The URL is the single source of truth, so a refresh reruns the search.
  const paramsKey = searchParams.toString();

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
  }, [paramsKey]);

  const state = parseSearchParams(searchParams);
  const restrictedGuestCount = guests.filter(
    (guest) => guest.restrictions.length > 0
  ).length;

  // Re-runs the search from the compact bar at the top of this page.
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
      <header className="resultsHeader">
        <Link to="/" className="resultsHeader__brand">
          Chompers
        </Link>
        <SearchBar
          size="compact"
          initialQuery={state.query}
          initialLocation={state.locationQuery}
          onSearch={runSearch}
        />
      </header>

      <div className="resultsPage">
        <div className="resultsPage__meta">
          <h1 className="resultsPage__title">
            {state.query ? `“${state.query}”` : "Best fits for your group"}
          </h1>
          {restrictedGuestCount > 0 ? (
            <p className="resultsPage__subtitle">
              Ranked for {guestCount} {guestCount === 1 ? "person" : "people"},
              including {restrictedGuestCount} with restrictions.{" "}
              <Link to="/">Edit party</Link>
            </p>
          ) : (
            <p className="resultsPage__subtitle">
              No dietary restrictions set — ranked by rating and distance.{" "}
              <Link to="/">Add restrictions</Link>
            </p>
          )}
        </div>

        {errorMessage && <div className="alert alert--error">{errorMessage}</div>}

        {isSearching && (
          <div className="skeletonList">
            {[0, 1, 2, 3, 4].map((index) => (
              <div key={index} className="skeleton" />
            ))}
          </div>
        )}

        {response && !isSearching && (
          <>
            <p className="results__summary">
              Top {response.results.length} of {response.candidates_considered}{" "}
              near {response.searched_location}
            </p>

            {response.results.map((result, index) => (
              <ResultCard
                key={result.place_id || result.name}
                result={result}
                rank={index + 1}
              />
            ))}

            {response.results.length === 0 && (
              <div className="placeholder">
                <p>Nothing came back for that search.</p>
              </div>
            )}

            <ul className="notes">
              {response.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
