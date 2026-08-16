// One ranked restaurant, with the reasoning that put it there.

import { MatchBadge } from "./MatchBadge";
import type { RestaurantResult } from "../types";

interface ResultCardProps {
  result: RestaurantResult;
  rank: number;
}

// Converts meters into a short human-readable distance.
function formatDistance(meters: number): string {
  const miles = meters / 1609.34;
  return miles < 0.2 ? `${Math.round(meters)} m` : `${miles.toFixed(1)} mi`;
}

// Renders a price level as dollar signs, or a dash when unknown.
function formatPrice(priceLevel: number | null): string {
  return priceLevel === null || priceLevel <= 0 ? "—" : "$".repeat(priceLevel);
}

export function ResultCard({ result, rank }: ResultCardProps) {
  const groupFitPercent = Math.round(result.group_fit * 100);

  return (
    <article className="card">
      <div className="card__rank" aria-hidden="true">
        {rank}
      </div>

      <div className="card__body">
        <header className="card__header">
          <h3 className="card__name">{result.name}</h3>
          <span className="card__cuisine">{result.cuisine}</span>
        </header>

        <p className="card__meta">
          {result.rating !== null && (
            <span>
              ★ {result.rating.toFixed(1)}{" "}
              <span className="card__muted">({result.rating_count})</span>
            </span>
          )}
          <span>{formatPrice(result.price_level)}</span>
          <span>{formatDistance(result.distance_meters)}</span>
          {result.open_now !== null && (
            <span className={result.open_now ? "open" : "closed"}>
              {result.open_now ? "Open now" : "Closed"}
            </span>
          )}
        </p>

        <p className="card__address">{result.address}</p>

        <div className="fitbar" aria-label={`Group fit ${groupFitPercent}%`}>
          <div className="fitbar__track">
            <div
              className="fitbar__fill"
              style={{ width: `${groupFitPercent}%` }}
            />
          </div>
          <span className="fitbar__label">{groupFitPercent}% group fit</span>
        </div>

        {result.guest_fits.length > 0 && (
          <ul className="badges">
            {result.guest_fits.map((fit) => (
              <MatchBadge key={fit.guest_name} fit={fit} />
            ))}
          </ul>
        )}

        {result.warnings.length > 0 && (
          <ul className="warnings">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}

        {result.maps_uri && (
          <a
            className="card__link"
            href={result.maps_uri}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in Google Maps →
          </a>
        )}
      </div>
    </article>
  );
}
