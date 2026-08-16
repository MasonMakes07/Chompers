// Location input: browser geolocation by default, typed city/ZIP as fallback.

import { useState } from "react";
import { requestBrowserLocation } from "../api/client";

interface Coordinates {
  latitude: number;
  longitude: number;
}

interface LocationPickerProps {
  coordinates: Coordinates | null;
  locationQuery: string;
  onCoordinatesChange: (coordinates: Coordinates | null) => void;
  onLocationQueryChange: (query: string) => void;
}

export function LocationPicker({
  coordinates,
  locationQuery,
  onCoordinatesChange,
  onLocationQueryChange,
}: LocationPickerProps) {
  const [isLocating, setIsLocating] = useState(false);
  const [locateFailed, setLocateFailed] = useState(false);

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

  return (
    <div className="location">
      <button
        type="button"
        className="button button--ghost"
        onClick={useMyLocation}
        disabled={isLocating}
      >
        {isLocating ? "Locating…" : "Use my location"}
      </button>

      <span className="location__divider">or</span>

      <input
        type="text"
        className="location__input"
        maxLength={120}
        placeholder="City or ZIP code"
        aria-label="City or ZIP code"
        value={locationQuery}
        onChange={(event) => {
          onLocationQueryChange(event.target.value);
          if (event.target.value) {
            onCoordinatesChange(null);
          }
        }}
      />

      {coordinates && (
        <p className="location__status location__status--ok">
          Using your current location.
        </p>
      )}
      {locateFailed && (
        <p className="location__status location__status--warn">
          Could not get your location. Type a city or ZIP instead.
        </p>
      )}
    </div>
  );
}
