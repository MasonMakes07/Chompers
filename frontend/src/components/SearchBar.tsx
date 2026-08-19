// Quick search: a free-text box plus the location to search near.

import { useState } from "react";
import { requestBrowserLocation } from "../api/client";
import { useParty } from "../context/PartyContext";

const EXAMPLE_QUERIES = ["sushi", "cheap tacos", "vegan brunch", "late night"];

interface SearchBarProps {
  initialQuery?: string;
  initialLocation?: string;
  size?: "large" | "compact";
  onSearch: (query: string, locationQuery: string) => void;
}

export function SearchBar({
  initialQuery = "",
  initialLocation = "",
  size = "large",
  onSearch,
}: SearchBarProps) {
  const { coordinates, setCoordinates } = useParty();
  const [query, setQuery] = useState(initialQuery);
  const [locationQuery, setLocationQuery] = useState(initialLocation);
  const [isLocating, setIsLocating] = useState(false);

  const hasLocation = coordinates !== null || locationQuery.trim().length > 0;

  // Requests browser coordinates and clears the typed location on success.
  const useMyLocation = async () => {
    setIsLocating(true);
    const position = await requestBrowserLocation();
    setIsLocating(false);
    if (position) {
      setCoordinates(position);
      setLocationQuery("");
    }
  };

  // Submits the search, letting the parent decide where to navigate.
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!hasLocation) return;
    onSearch(query.trim(), locationQuery.trim());
  };

  return (
    <form className={`searchbar searchbar--${size}`} onSubmit={submit}>
      <div className="searchbar__row">
        <input
          type="search"
          className="searchbar__query"
          maxLength={120}
          placeholder="Search food, cuisine, or a vibe…"
          aria-label="Search restaurants"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <input
          type="text"
          className="searchbar__location"
          maxLength={120}
          placeholder={coordinates ? "Near you" : "City or ZIP"}
          aria-label="Location"
          value={locationQuery}
          onChange={(event) => {
            setLocationQuery(event.target.value);
            if (event.target.value) setCoordinates(null);
          }}
        />

        <button
          type="button"
          className="searchbar__locate"
          onClick={useMyLocation}
          disabled={isLocating}
          title="Use my location"
          aria-label="Use my location"
        >
          {isLocating ? "…" : "◎"}
        </button>

        <button
          type="submit"
          className="button button--primary searchbar__submit"
          disabled={!hasLocation}
        >
          Search
        </button>
      </div>

      {size === "large" && (
        <div className="searchbar__examples">
          <span className="searchbar__examplesLabel">Try:</span>
          {EXAMPLE_QUERIES.map((example) => (
            <button
              key={example}
              type="button"
              className="searchbar__example"
              onClick={() => setQuery(example)}
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {!hasLocation && size === "large" && (
        <p className="hint">
          Add a city or ZIP, or tap ◎ to use your location.
        </p>
      )}
    </form>
  );
}
