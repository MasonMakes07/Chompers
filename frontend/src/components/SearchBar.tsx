// Quick search: a free-text box plus the location to search near.

import { useState } from "react";
import { requestBrowserLocation } from "../api/client";
import { useParty } from "../context/PartyContext";

interface SearchBarProps {
  initialQuery?: string;
  initialLocation?: string;
  onSearch: (query: string, locationQuery: string) => void;
}

export function SearchBar({
  initialQuery = "",
  initialLocation = "",
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
    <form className="searchbar" onSubmit={submit}>
      <div className="searchbar__row">
        <span className="searchbar__icon" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <circle
              cx="11"
              cy="11"
              r="7"
              stroke="currentColor"
              strokeWidth="2"
            />
            <path
              d="M20 20l-3.5-3.5"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </span>

        <input
          type="search"
          className="searchbar__query"
          maxLength={120}
          placeholder="Search restaurants, cuisines, diets…"
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
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="2" />
            <circle cx="12" cy="12" r="2.5" fill="currentColor" />
            <path
              d="M12 1v3M12 20v3M1 12h3M20 12h3"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </button>

        <button
          type="submit"
          className="searchbar__submit"
          disabled={!hasLocation}
          title={hasLocation ? undefined : "Choose a location first"}
        >
          Search
        </button>
      </div>
    </form>
  );
}
