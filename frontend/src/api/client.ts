// The only module that talks to the backend. No API key is ever present here.

import type { SearchRequest, SearchResponse } from "../types";

// Must exceed the backend's own upstream timeout (30s for Overpass) plus its
// pacing delay. A shorter budget here aborts searches the server would have
// answered, which surfaces as a "timeout" that was never really one.
const REQUEST_TIMEOUT_MS = 45000;

// Posts a search to the backend and returns ranked results, or throws.
export async function searchRestaurants(
  payload: SearchRequest
): Promise<SearchResponse> {
  const abortController = new AbortController();
  const timeoutId = window.setTimeout(
    () => abortController.abort(),
    REQUEST_TIMEOUT_MS
  );

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: abortController.signal,
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    return (await response.json()) as SearchResponse;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(
        "The search took too long. Try again, or narrow the search radius."
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

// Extracts a readable message from a failed backend response.
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      return body.detail[0].msg ?? "That search was rejected as invalid.";
    }
  } catch {
    // Fall through to the generic message below.
  }
  return `Search failed (${response.status}).`;
}

// Names a coordinate pair, e.g. "La Jolla, San Diego, CA", or null on failure.
export async function reverseGeocode(
  latitude: number,
  longitude: number
): Promise<string | null> {
  try {
    const response = await fetch(
      `/api/reverse-geocode?latitude=${latitude}&longitude=${longitude}`
    );
    if (!response.ok) return null;
    const body = (await response.json()) as { label?: string };
    return body.label ?? null;
  } catch {
    // A missing label is cosmetic, never worth surfacing as an error.
    return null;
  }
}

// Asks the browser for coordinates, resolving to null if unavailable.
export function requestBrowserLocation(): Promise<
  { latitude: number; longitude: number } | null
> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        }),
      () => resolve(null),
      { timeout: 10000, maximumAge: 300000 }
    );
  });
}
