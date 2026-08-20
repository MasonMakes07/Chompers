// Shared party state, so guests survive navigation between pages.
//
// Location and filters live in the URL (shareable, refreshable). Guests live
// here and in sessionStorage, because a restriction list is too large and too
// personal to put in a query string.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { reverseGeocode } from "../api/client";
import type { Coordinates, GuestDraft } from "../types";

const GUESTS_STORAGE_KEY = "chompers.guests";
const COORDS_STORAGE_KEY = "chompers.coords";
const LABEL_STORAGE_KEY = "chompers.coordsLabel";

interface PartyContextValue {
  guestCount: number;
  guests: GuestDraft[];
  coordinates: Coordinates | null;
  /** Human-readable name for `coordinates`, or null while it resolves. */
  locationLabel: string | null;
  isNamingLocation: boolean;
  setGuestCount: (count: number) => void;
  setGuests: (guests: GuestDraft[]) => void;
  setCoordinates: (coordinates: Coordinates | null) => void;
}

const PartyContext = createContext<PartyContextValue | null>(null);

// Reads and parses a sessionStorage value, returning a fallback on any error.
function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

// Writes a value to sessionStorage, ignoring quota or privacy-mode failures.
function writeStored(key: string, value: unknown): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage is a convenience here, never a requirement.
  }
}

export function PartyProvider({ children }: { children: ReactNode }) {
  const [guests, setGuestsState] = useState<GuestDraft[]>(() =>
    // Backfill cuisine fields so guests stored before this feature existed
    // (and any hand-edited storage) still satisfy the current shape.
    readStored<GuestDraft[]>(GUESTS_STORAGE_KEY, []).map((guest) => ({
      ...guest,
      likedCuisines: guest.likedCuisines ?? [],
      dislikedCuisines: guest.dislikedCuisines ?? [],
    }))
  );
  const [coordinates, setCoordinatesState] = useState<Coordinates | null>(() =>
    readStored<Coordinates | null>(COORDS_STORAGE_KEY, null)
  );
  const [locationLabel, setLocationLabel] = useState<string | null>(() =>
    readStored<string | null>(LABEL_STORAGE_KEY, null)
  );
  const [isNamingLocation, setIsNamingLocation] = useState(false);
  const [guestCount, setGuestCount] = useState(4);

  useEffect(() => {
    writeStored(GUESTS_STORAGE_KEY, guests);
  }, [guests]);

  useEffect(() => {
    writeStored(COORDS_STORAGE_KEY, coordinates);
  }, [coordinates]);

  useEffect(() => {
    writeStored(LABEL_STORAGE_KEY, locationLabel);
  }, [locationLabel]);

  // Coordinates already looked up, so StrictMode's double-invoked effect
  // does not fire a second identical request.
  const namedCoordsRef = useRef<string | null>(null);

  // Names the coordinates whenever they change, so the UI can show where
  // "my location" actually is instead of an unhelpful generic phrase.
  useEffect(() => {
    if (coordinates === null) {
      namedCoordsRef.current = null;
      setLocationLabel(null);
      return;
    }

    const coordsKey = `${coordinates.latitude},${coordinates.longitude}`;
    if (namedCoordsRef.current === coordsKey) return;
    namedCoordsRef.current = coordsKey;

    let isCurrent = true;
    setIsNamingLocation(true);

    void reverseGeocode(coordinates.latitude, coordinates.longitude).then(
      (label) => {
        if (!isCurrent) return;
        setLocationLabel(label);
        setIsNamingLocation(false);
      }
    );

    return () => {
      isCurrent = false;
    };
  }, [coordinates]);

  // Stores the guest list and keeps headcount at least as large as it.
  const setGuests = useCallback((nextGuests: GuestDraft[]) => {
    setGuestsState(nextGuests);
    setGuestCount((currentCount) => Math.max(currentCount, nextGuests.length));
  }, []);

  // Replaces the coordinates, clearing any stale label for the old spot.
  const setCoordinates = useCallback((next: Coordinates | null) => {
    setCoordinatesState(next);
    setLocationLabel(null);
  }, []);

  const value = useMemo(
    () => ({
      guestCount,
      guests,
      coordinates,
      locationLabel,
      isNamingLocation,
      setGuestCount,
      setGuests,
      setCoordinates,
    }),
    [
      guestCount,
      guests,
      coordinates,
      locationLabel,
      isNamingLocation,
      setGuests,
      setCoordinates,
    ]
  );

  return <PartyContext.Provider value={value}>{children}</PartyContext.Provider>;
}

// Returns the shared party state, throwing if used outside the provider.
export function useParty(): PartyContextValue {
  const context = useContext(PartyContext);
  if (context === null) {
    throw new Error("useParty must be used inside a PartyProvider");
  }
  return context;
}
