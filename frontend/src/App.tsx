// Top-level app state and the search flow.

import { useState } from "react";
import { PartyForm } from "./components/PartyForm";
import { ResultCard } from "./components/ResultCard";
import { searchRestaurants } from "./api/client";
import type { GuestDraft, SearchResponse } from "./types";

interface Coordinates {
  latitude: number;
  longitude: number;
}

export default function App() {
  const [guestCount, setGuestCount] = useState(4);
  const [guests, setGuests] = useState<GuestDraft[]>([]);
  const [coordinates, setCoordinates] = useState<Coordinates | null>(null);
  const [locationQuery, setLocationQuery] = useState("");
  const [radiusMeters, setRadiusMeters] = useState(5000);
  const [maxPriceLevel, setMaxPriceLevel] = useState<number | null>(null);

  const [isSearching, setIsSearching] = useState(false);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Sends the current form state to the backend and stores the results.
  const runSearch = async () => {
    setIsSearching(true);
    setErrorMessage(null);

    try {
      const result = await searchRestaurants({
        guest_count: guestCount,
        guests: guests.map((guest) => ({
          name: guest.name.trim() || "Guest",
          restrictions: guest.restrictions,
        })),
        latitude: coordinates?.latitude,
        longitude: coordinates?.longitude,
        location_query: locationQuery.trim() || undefined,
        radius_meters: radiusMeters,
        max_price_level: maxPriceLevel,
      });
      setResponse(result);
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Something went wrong."
      );
      setResponse(null);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="app">
      <header className="hero">
        <h1 className="hero__title">Chompers</h1>
        <p className="hero__subtitle">
          Find a spot where <em>everyone</em> can actually eat.
        </p>
      </header>

      <main className="layout">
        <PartyForm
          guestCount={guestCount}
          guests={guests}
          coordinates={coordinates}
          locationQuery={locationQuery}
          radiusMeters={radiusMeters}
          maxPriceLevel={maxPriceLevel}
          isSearching={isSearching}
          onGuestCountChange={setGuestCount}
          onGuestsChange={setGuests}
          onCoordinatesChange={setCoordinates}
          onLocationQueryChange={setLocationQuery}
          onRadiusChange={setRadiusMeters}
          onMaxPriceChange={setMaxPriceLevel}
          onSubmit={runSearch}
        />

        <section className="results">
          {errorMessage && <div className="alert alert--error">{errorMessage}</div>}

          {isSearching && <div className="alert">Searching nearby…</div>}

          {!isSearching && !response && !errorMessage && (
            <div className="placeholder">
              <p>
                Add your group, pick a location, and we will rank the five best
                nearby options for everyone at once.
              </p>
            </div>
          )}

          {response && !isSearching && (
            <>
              <p className="results__summary">
                Top {response.results.length} of{" "}
                {response.candidates_considered} nearby near{" "}
                {response.searched_location}
              </p>

              {response.results.map((result, index) => (
                <ResultCard
                  key={result.place_id || result.name}
                  result={result}
                  rank={index + 1}
                />
              ))}

              <ul className="notes">
                {response.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
