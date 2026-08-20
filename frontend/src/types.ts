// Wire types mirroring backend/schemas.py. Keep these in sync by hand.

export const RESTRICTIONS = [
  { id: "vegetarian", label: "Vegetarian", kind: "diet" },
  { id: "vegan", label: "Vegan", kind: "diet" },
  { id: "gluten_free", label: "Gluten-free", kind: "diet" },
  { id: "dairy_free", label: "Dairy-free", kind: "diet" },
  { id: "nut_allergy", label: "Nut allergy", kind: "allergy" },
  { id: "shellfish_allergy", label: "Shellfish allergy", kind: "allergy" },
  { id: "halal", label: "Halal", kind: "religious" },
  { id: "kosher", label: "Kosher", kind: "religious" },
] as const;

export type RestrictionId = (typeof RESTRICTIONS)[number]["id"];

// Each id is lowercase so the backend scorer can substring-match it against a
// Google place type (e.g. "italian" matches "italian_restaurant").
export const CUISINES = [
  { id: "italian", label: "Italian" },
  { id: "mexican", label: "Mexican" },
  { id: "chinese", label: "Chinese" },
  { id: "japanese", label: "Japanese" },
  { id: "thai", label: "Thai" },
  { id: "indian", label: "Indian" },
  { id: "korean", label: "Korean" },
  { id: "vietnamese", label: "Vietnamese" },
  { id: "mediterranean", label: "Mediterranean" },
  { id: "greek", label: "Greek" },
  { id: "american", label: "American" },
  { id: "seafood", label: "Seafood" },
  { id: "pizza", label: "Pizza" },
  { id: "barbecue", label: "Barbecue" },
] as const;

export type CuisineId = (typeof CUISINES)[number]["id"];

// The backend rejects a guest with more than this many terms in either list.
export const MAX_CUISINE_TERMS = 8;

export interface GuestDraft {
  id: string;
  name: string;
  restrictions: RestrictionId[];
  likedCuisines: CuisineId[];
  dislikedCuisines: CuisineId[];
}

export interface SearchRequest {
  query?: string;
  guest_count: number;
  guests: {
    name: string;
    restrictions: RestrictionId[];
    liked_cuisines: string[];
    disliked_cuisines: string[];
  }[];
  latitude?: number;
  longitude?: number;
  location_query?: string;
  radius_meters: number;
  max_price_level?: number | null;
  limit?: number;
}

export interface RestrictionFit {
  restriction: string;
  label: string;
  confidence: number;
  evidence: "explicit" | "keyword" | "cuisine" | "default";
  reason: string;
  verified: boolean;
}

export interface GuestFit {
  guest_name: string;
  confidence: number;
  status: "good" | "limited" | "risky";
  restriction_fits: RestrictionFit[];
}

export interface RestaurantResult {
  place_id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  cuisine: string;
  rating: number | null;
  rating_count: number;
  price_level: number | null;
  open_now: boolean | null;
  maps_uri: string;
  distance_meters: number;
  score: number;
  group_fit: number;
  guest_fits: GuestFit[];
  warnings: string[];
}

export interface SearchResponse {
  results: RestaurantResult[];
  searched_location: string;
  query: string | null;
  candidates_considered: number;
  excluded_count: number;
  notes: string[];
}

export interface Coordinates {
  latitude: number;
  longitude: number;
}
