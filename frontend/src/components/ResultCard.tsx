// One ranked restaurant, with the reasoning that put it there.

import type { GuestFit, RestaurantResult } from "../types";

interface ResultCardProps {
  result: RestaurantResult;
  rank: number;
  /** False when browsing, where there is no party to fit and the score
   *  would read 100 for every result. */
  showGroupFit?: boolean;
}

// Converts meters into a short human-readable distance.
function formatDistance(meters: number): string {
  const miles = meters / 1609.34;
  return miles < 0.2 ? `${Math.round(meters)} m away` : `${miles.toFixed(1)} mi away`;
}

// Renders a price level as dollar signs, or null when the data is absent.
function formatPrice(priceLevel: number | null): string | null {
  return priceLevel === null || priceLevel <= 0 ? null : "$".repeat(priceLevel);
}

// Titlecases the raw cuisine string so it reads as a label.
function formatCuisine(cuisine: string): string {
  if (!cuisine) return "Restaurant";
  return cuisine.charAt(0).toUpperCase() + cuisine.slice(1);
}

// Picks the badge color band from the group-fit percentage.
function scoreTone(percent: number): string {
  if (percent >= 96) return "strong";
  if (percent >= 86) return "good";
  return "weak";
}

// Matches the backend's "good" status threshold (translator.py), so a chip
// only claims a restriction the whole group is comfortably served on.
const GOOD_CONFIDENCE = 0.75;

interface DietHighlight {
  label: string;
  verified: boolean;
}

// Aggregates the group's confidently-met restrictions into positive chips. A
// restriction qualifies only when its least-served guest still clears the good
// bar, and is marked verified only when every such guest's evidence is.
function dietHighlights(guestFits: GuestFit[]): DietHighlight[] {
  const byRestriction = new Map<
    string,
    { label: string; minConfidence: number; verified: boolean }
  >();

  for (const guestFit of guestFits) {
    for (const fit of guestFit.restriction_fits) {
      const existing = byRestriction.get(fit.restriction);
      if (existing === undefined) {
        byRestriction.set(fit.restriction, {
          label: fit.label,
          minConfidence: fit.confidence,
          verified: fit.verified,
        });
      } else {
        existing.minConfidence = Math.min(existing.minConfidence, fit.confidence);
        existing.verified = existing.verified && fit.verified;
      }
    }
  }

  return [...byRestriction.values()]
    .filter((entry) => entry.minConfidence >= GOOD_CONFIDENCE)
    .map((entry) => ({ label: entry.label, verified: entry.verified }));
}

// Summarizes one guest's limiting restriction for the compact badge.
function badgeText(fit: GuestFit): string {
  const limiting = fit.restriction_fits.reduce<
    GuestFit["restriction_fits"][number] | null
  >(
    (weakest, current) =>
      weakest === null || current.confidence < weakest.confidence
        ? current
        : weakest,
    null
  );
  return limiting === null ? "no restrictions" : limiting.label;
}

export function ResultCard({
  result,
  rank,
  showGroupFit = true,
}: ResultCardProps) {
  const groupFitPercent = Math.round(result.group_fit * 100);
  const price = formatPrice(result.price_level);
  const subParts = [formatCuisine(result.cuisine), price].filter(Boolean);
  const highlights = showGroupFit ? dietHighlights(result.guest_fits) : [];

  return (
    <article className="result-row">
      <div className="result-row__top">
        <span className="result-row__rank" aria-hidden="true">
          {rank}
        </span>

        <span className="result-row__thumb" aria-hidden="true" />

        <div className="result-row__main">
          <h3 className="result-row__name">{result.name}</h3>
          <p className="result-row__sub">{subParts.join(" · ")}</p>
          <p className="result-row__meta">
            {result.rating !== null && (
              <span className="rating">
                ★ {result.rating.toFixed(1)}
                {result.rating_count > 0 &&
                  ` (${result.rating_count.toLocaleString()})`}
              </span>
            )}
            <span>{formatDistance(result.distance_meters)}</span>
            {result.open_now !== null && (
              <span>{result.open_now ? "Open now" : "Closed"}</span>
            )}
            {result.maps_uri && (
              <a
                href={result.maps_uri}
                target="_blank"
                rel="noopener noreferrer"
              >
                Map
              </a>
            )}
          </p>
        </div>

        {showGroupFit && (
          <div className="result-row__score">
            <div
              className={`score-badge score-badge--${scoreTone(groupFitPercent)}`}
            >
              {groupFitPercent}
            </div>
            <span className="score-label">Group fit</span>
          </div>
        )}
      </div>

      {highlights.length > 0 && (
        <ul className="diet-highlights">
          {highlights.map((highlight) => (
            <li
              key={highlight.label}
              className={`diet-chip ${
                highlight.verified ? "diet-chip--verified" : ""
              }`}
              title={
                highlight.verified
                  ? "Confirmed by the listing"
                  : "Likely, based on cuisine"
              }
            >
              {highlight.label}
              {highlight.verified ? " ✓" : ""}
            </li>
          ))}
        </ul>
      )}

      {showGroupFit && result.guest_fits.length > 0 && (
        <ul className="badges">
          {result.guest_fits.map((fit) => (
            <li key={fit.guest_name} className={`badge badge--${fit.status}`}>
              <span className="badge__name">{fit.guest_name}</span>
              <span>{badgeText(fit)}</span>
            </li>
          ))}
        </ul>
      )}

      {result.warnings.length > 0 && (
        <ul className="result-row__warnings">
          {result.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
