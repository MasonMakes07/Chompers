// URL query-string helpers, so a results page can be shared and refreshed.

import type { Coordinates } from "./types";

export const DEFAULT_RADIUS_METERS = 5000;

export interface SearchParamState {
  query: string;
  locationQuery: string;
  coordinates: Coordinates | null;
  radiusMeters: number;
  maxPriceLevel: number | null;
}

// Builds the /search URL for a given search, omitting empty values.
export function buildSearchPath(state: SearchParamState): string {
  const params = new URLSearchParams();

  if (state.query) params.set("q", state.query);
  if (state.locationQuery) params.set("loc", state.locationQuery);
  if (state.coordinates && !state.locationQuery) {
    params.set("lat", state.coordinates.latitude.toFixed(5));
    params.set("lng", state.coordinates.longitude.toFixed(5));
  }
  if (state.radiusMeters !== DEFAULT_RADIUS_METERS) {
    params.set("radius", String(state.radiusMeters));
  }
  if (state.maxPriceLevel !== null) {
    params.set("price", String(state.maxPriceLevel));
  }

  return `/search?${params.toString()}`;
}

// Parses a number from URL params, returning null when absent or invalid.
function readNumber(params: URLSearchParams, key: string): number | null {
  const raw = params.get(key);
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

// Reads a search back out of the URL, with sane fallbacks throughout.
export function parseSearchParams(params: URLSearchParams): SearchParamState {
  const latitude = readNumber(params, "lat");
  const longitude = readNumber(params, "lng");
  const radius = readNumber(params, "radius");
  const price = readNumber(params, "price");

  return {
    query: params.get("q") ?? "",
    locationQuery: params.get("loc") ?? "",
    coordinates:
      latitude !== null && longitude !== null ? { latitude, longitude } : null,
    radiusMeters: radius ?? DEFAULT_RADIUS_METERS,
    maxPriceLevel: price,
  };
}
