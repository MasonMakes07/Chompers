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
  useState,
  type ReactNode,
} from "react";
import type { Coordinates, GuestDraft } from "../types";

const GUESTS_STORAGE_KEY = "chompers.guests";
const COORDS_STORAGE_KEY = "chompers.coords";

interface PartyContextValue {
  guestCount: number;
  guests: GuestDraft[];
  coordinates: Coordinates | null;
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
    readStored<GuestDraft[]>(GUESTS_STORAGE_KEY, [])
  );
  const [coordinates, setCoordinatesState] = useState<Coordinates | null>(() =>
    readStored<Coordinates | null>(COORDS_STORAGE_KEY, null)
  );
  const [guestCount, setGuestCount] = useState(4);

  useEffect(() => {
    writeStored(GUESTS_STORAGE_KEY, guests);
  }, [guests]);

  useEffect(() => {
    writeStored(COORDS_STORAGE_KEY, coordinates);
  }, [coordinates]);

  // Stores the guest list and keeps headcount at least as large as it.
  const setGuests = useCallback((nextGuests: GuestDraft[]) => {
    setGuestsState(nextGuests);
    setGuestCount((currentCount) => Math.max(currentCount, nextGuests.length));
  }, []);

  const setCoordinates = useCallback(
    (next: Coordinates | null) => setCoordinatesState(next),
    []
  );

  const value = useMemo(
    () => ({
      guestCount,
      guests,
      coordinates,
      setGuestCount,
      setGuests,
      setCoordinates,
    }),
    [guestCount, guests, coordinates, setGuests, setCoordinates]
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
