// The group planner: headcount, guests with restrictions, location, filters.

import { useState } from "react";
import { GuestRow } from "./GuestRow";
import { requestBrowserLocation } from "../api/client";
import { useParty } from "../context/PartyContext";
import { isCodeLike } from "../validation";
import type { Coordinates, GuestDraft } from "../types";

const MAX_GUESTS = 20;

// Radius options in meters, labelled in miles for a US audience.
const RADIUS_OPTIONS = [
  { meters: 1600, label: "1 mi" },
  { meters: 5000, label: "3 mi" },
  { meters: 16000, label: "10 mi" },
  { meters: 40000, label: "25 mi" },
];

interface PartyFormProps {
  guestCount: number;
  guests: GuestDraft[];
  coordinates: Coordinates | null;
  locationQuery: string;
  radiusMeters: number;
  maxPriceLevel: number | null;
  isSearching: boolean;
  onGuestCountChange: (count: number) => void;
  onGuestsChange: (guests: GuestDraft[]) => void;
  onCoordinatesChange: (coordinates: Coordinates | null) => void;
  onLocationQueryChange: (query: string) => void;
  onRadiusChange: (meters: number) => void;
  onMaxPriceChange: (priceLevel: number | null) => void;
  onSubmit: () => void;
}

export function PartyForm(props: PartyFormProps) {
  const {
    guestCount,
    guests,
    coordinates,
    locationQuery,
    radiusMeters,
    maxPriceLevel,
    isSearching,
    onGuestCountChange,
    onGuestsChange,
    onCoordinatesChange,
    onLocationQueryChange,
    onRadiusChange,
    onMaxPriceChange,
    onSubmit,
  } = props;

  const { locationLabel, isNamingLocation } = useParty();
  const [isLocating, setIsLocating] = useState(false);
  const [locateFailed, setLocateFailed] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);

  const hasLocation = coordinates !== null || locationQuery.trim().length > 0;

  // Requests coordinates from the browser and clears the typed fallback.
  const useMyLocation = async () => {
    setIsLocating(true);
    setLocateFailed(false);
    const position = await requestBrowserLocation();
    setIsLocating(false);

    if (position) {
      onCoordinatesChange(position);
      onLocationQueryChange("");
    } else {
      setLocateFailed(true);
    }
  };

  // Appends a blank guest, up to the supported maximum.
  const addGuest = () => {
    if (guests.length >= MAX_GUESTS) return;
    const nextGuests = [
      ...guests,
      {
        id: crypto.randomUUID(),
        name: "",
        restrictions: [],
        likedCuisines: [],
        dislikedCuisines: [],
      },
    ];
    onGuestsChange(nextGuests);
    if (nextGuests.length > guestCount) {
      onGuestCountChange(nextGuests.length);
    }
  };

  // Replaces one guest in the list by id.
  const updateGuest = (updated: GuestDraft) => {
    onGuestsChange(
      guests.map((guest) => (guest.id === updated.id ? updated : guest))
    );
  };

  // Drops one guest from the list by id.
  const removeGuest = (id: string) => {
    onGuestsChange(guests.filter((guest) => guest.id !== id));
  };

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        // Reject code-like names or location before hitting the backend.
        const freeText = [locationQuery, ...guests.map((guest) => guest.name)];
        if (freeText.some(isCodeLike)) {
          setInputError("Names and location must be plain text, not code.");
          return;
        }
        setInputError(null);
        onSubmit();
      }}
    >
      <h2 className="section-title">How many people?</h2>
      <div className="stepper" style={{ marginTop: "0.75rem" }}>
        <button
          type="button"
          className="stepper__button"
          aria-label="Remove one person"
          disabled={guestCount <= Math.max(1, guests.length)}
          onClick={() => onGuestCountChange(guestCount - 1)}
        >
          −
        </button>
        <span className="stepper__value" aria-live="polite">
          {guestCount}
        </span>
        <button
          type="button"
          className="stepper__button"
          aria-label="Add one person"
          disabled={guestCount >= MAX_GUESTS}
          onClick={() => onGuestCountChange(guestCount + 1)}
        >
          +
        </button>
      </div>
      {guestCount >= 6 && (
        <p className="hint">
          Large party — we will flag results so you can call ahead. Seating
          capacity is not something we can verify.
        </p>
      )}

      <div className="card__divider" />

      <div className="section-head">
        <h2 className="section-title">Who has restrictions?</h2>
        <button type="button" className="button-dark" onClick={addGuest}>
          + Add person
        </button>
      </div>
      <p className="hint">
        Only add people with restrictions. Everyone else is assumed easy to
        please.
      </p>

      {guests.length === 0 ? (
        <p className="empty-note">
          No restrictions yet — results will be ranked by cuisine fit and
          distance.
        </p>
      ) : (
        <div className="guest-list">
          {guests.map((guest, index) => (
            <GuestRow
              key={guest.id}
              guest={guest}
              index={index}
              onChange={updateGuest}
              onRemove={removeGuest}
            />
          ))}
        </div>
      )}

      <div className="card__divider" />

      <h2 className="section-title">Where?</h2>
      <div className="location-row" style={{ marginTop: "0.75rem" }}>
        <button
          type="button"
          className={`locate-button ${
            coordinates ? "locate-button--active" : ""
          }`}
          onClick={useMyLocation}
          disabled={isLocating}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="2" />
            <circle cx="12" cy="12" r="2.5" fill="currentColor" />
            <path
              d="M12 1v3M12 20v3M1 12h3M20 12h3"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          {isLocating ? "Locating…" : "Use my location"}
        </button>

        <span className="location-row__or">or</span>

        <input
          type="text"
          className="text-input"
          maxLength={120}
          placeholder="Portland, OR"
          aria-label="City or ZIP code"
          value={locationQuery}
          onChange={(event) => {
            onLocationQueryChange(event.target.value);
            if (event.target.value) onCoordinatesChange(null);
          }}
        />
      </div>

      {coordinates && (
        <p className="status-line status-line--ok">
          {isNamingLocation ? (
            "Finding your location…"
          ) : locationLabel ? (
            <>
              Searching near <strong>{locationLabel}</strong>
            </>
          ) : (
            // The name lookup failed, so show coordinates rather than an
            // empty reassurance the user cannot verify.
            `Using your location (${coordinates.latitude.toFixed(3)}, ${coordinates.longitude.toFixed(3)})`
          )}
        </p>
      )}
      {locateFailed && (
        <p className="status-line status-line--warn">
          Could not get your location. Type a city or ZIP instead.
        </p>
      )}

      <div className="filters-row" style={{ marginTop: "1.25rem" }}>
        <label>
          <span className="field-label">Within</span>
          <select
            className="select-input"
            value={radiusMeters}
            onChange={(event) => onRadiusChange(Number(event.target.value))}
          >
            {RADIUS_OPTIONS.map((option) => (
              <option key={option.meters} value={option.meters}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span className="field-label">Max price</span>
          <select
            className="select-input"
            value={maxPriceLevel ?? ""}
            onChange={(event) =>
              onMaxPriceChange(
                event.target.value === "" ? null : Number(event.target.value)
              )
            }
          >
            <option value="">Any</option>
            <option value={1}>$</option>
            <option value={2}>$$</option>
            <option value={3}>$$$</option>
            <option value={4}>$$$$</option>
          </select>
        </label>
      </div>

      <button
        type="submit"
        className="button-primary"
        style={{ marginTop: "1.5rem" }}
        disabled={isSearching || !hasLocation}
      >
        {isSearching ? "Searching…" : "Find our top 5"}
      </button>
      {inputError && (
        <p className="status-line status-line--warn" role="alert">
          {inputError}
        </p>
      )}
      {!hasLocation && (
        <p className="hint" style={{ textAlign: "center" }}>
          Pick a location to search.
        </p>
      )}
    </form>
  );
}
