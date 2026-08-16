// The search form: headcount, each guest's restrictions, location, filters.

import { LocationPicker } from "./LocationPicker";
import { GuestRow } from "./GuestRow";
import type { GuestDraft } from "../types";

const MAX_GUESTS = 20;

// Radius options in meters, labelled in miles for a US audience.
const RADIUS_OPTIONS = [
  { meters: 1600, label: "1 mi" },
  { meters: 5000, label: "3 mi" },
  { meters: 16000, label: "10 mi" },
  { meters: 40000, label: "25 mi" },
];

interface Coordinates {
  latitude: number;
  longitude: number;
}

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

  const hasLocation = coordinates !== null || locationQuery.trim().length > 0;

  // Appends a blank guest, up to the supported maximum.
  const addGuest = () => {
    if (guests.length >= MAX_GUESTS) return;
    const newGuest: GuestDraft = {
      id: crypto.randomUUID(),
      name: "",
      restrictions: [],
    };
    const nextGuests = [...guests, newGuest];
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
      className="panel"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <section className="panel__section">
        <label className="field">
          <span className="field__label">How many people?</span>
          <input
            type="number"
            min={1}
            max={MAX_GUESTS}
            value={guestCount}
            className="field__input field__input--number"
            onChange={(event) =>
              onGuestCountChange(
                Math.max(1, Math.min(MAX_GUESTS, Number(event.target.value) || 1))
              )
            }
          />
        </label>
        {guestCount >= 6 && (
          <p className="hint">
            Large party — we will flag results so you can call ahead. Seating
            capacity is not something we can verify.
          </p>
        )}
      </section>

      <section className="panel__section">
        <div className="panel__sectionHeader">
          <h2 className="panel__title">Who has restrictions?</h2>
          <button type="button" className="button button--ghost" onClick={addGuest}>
            + Add person
          </button>
        </div>
        <p className="hint">
          Only add people with restrictions. Everyone else is assumed easy to
          please.
        </p>

        {guests.length === 0 ? (
          <p className="empty">
            No restrictions yet — results will be ranked by rating and distance.
          </p>
        ) : (
          guests.map((guest, index) => (
            <GuestRow
              key={guest.id}
              guest={guest}
              index={index}
              canRemove
              onChange={updateGuest}
              onRemove={removeGuest}
            />
          ))
        )}
      </section>

      <section className="panel__section">
        <h2 className="panel__title">Where?</h2>
        <LocationPicker
          coordinates={coordinates}
          locationQuery={locationQuery}
          onCoordinatesChange={onCoordinatesChange}
          onLocationQueryChange={onLocationQueryChange}
        />
      </section>

      <section className="panel__section panel__section--inline">
        <label className="field">
          <span className="field__label">Within</span>
          <select
            className="field__input"
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

        <label className="field">
          <span className="field__label">Max price</span>
          <select
            className="field__input"
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
      </section>

      <button
        type="submit"
        className="button button--primary"
        disabled={isSearching || !hasLocation}
      >
        {isSearching ? "Searching…" : "Find our top 5"}
      </button>
      {!hasLocation && (
        <p className="hint hint--center">
          Pick a location to search.
        </p>
      )}
    </form>
  );
}
