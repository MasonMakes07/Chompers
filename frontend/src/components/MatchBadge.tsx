// Per-guest indicator showing how well one person is served, and why.

import type { GuestFit } from "../types";

const STATUS_LABELS: Record<GuestFit["status"], string> = {
  good: "Good options",
  limited: "Limited options",
  risky: "Risky",
};

interface MatchBadgeProps {
  fit: GuestFit;
}

export function MatchBadge({ fit }: MatchBadgeProps) {
  // Picks the restriction that limited this guest, which explains the badge.
  const limitingFit = fit.restriction_fits.reduce<
    GuestFit["restriction_fits"][number] | null
  >(
    (weakest, current) =>
      weakest === null || current.confidence < weakest.confidence
        ? current
        : weakest,
    null
  );

  const explanation = limitingFit
    ? `${limitingFit.label} — ${limitingFit.reason}`
    : "No restrictions";

  return (
    <li className={`badge badge--${fit.status}`} title={explanation}>
      <span className="badge__name">{fit.guest_name}</span>
      <span className="badge__status">{STATUS_LABELS[fit.status]}</span>
      <span className="badge__why">
        {explanation}
        {limitingFit && !limitingFit.verified && (
          <em className="badge__inferred"> (inferred)</em>
        )}
      </span>
    </li>
  );
}
