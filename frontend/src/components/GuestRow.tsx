// One guest: avatar, name, a summary of their restrictions, and the chips.

import { useState } from "react";
import {
  CUISINES,
  MAX_CUISINE_TERMS,
  RESTRICTIONS,
  type CuisineId,
  type GuestDraft,
  type RestrictionId,
} from "../types";

interface GuestRowProps {
  guest: GuestDraft;
  index: number;
  onChange: (guest: GuestDraft) => void;
  onRemove: (id: string) => void;
}

// Builds the readable restriction summary shown under a guest's name.
function summarize(restrictions: RestrictionId[]): string {
  if (restrictions.length === 0) return "No restrictions yet — tap to add";
  return RESTRICTIONS.filter((item) => restrictions.includes(item.id))
    .map((item) => item.label)
    .join(", ");
}

export function GuestRow({ guest, index, onChange, onRemove }: GuestRowProps) {
  // A guest with nothing selected yet is opened so the chips are reachable.
  const [isOpen, setIsOpen] = useState(guest.restrictions.length === 0);

  const initial = (guest.name.trim() || "?").charAt(0).toUpperCase();
  const hasRestrictions = guest.restrictions.length > 0;

  // Adds or removes one restriction from this guest.
  const toggleRestriction = (restrictionId: RestrictionId) => {
    const isActive = guest.restrictions.includes(restrictionId);
    onChange({
      ...guest,
      restrictions: isActive
        ? guest.restrictions.filter((item) => item !== restrictionId)
        : [...guest.restrictions, restrictionId],
    });
  };

  // Cycles one cuisine through neutral -> liked -> avoided -> neutral. Each
  // list is capped at the backend's limit so a submit can never be rejected.
  const cycleCuisine = (cuisineId: CuisineId) => {
    const liked = guest.likedCuisines ?? [];
    const avoided = guest.dislikedCuisines ?? [];

    if (liked.includes(cuisineId)) {
      if (avoided.length >= MAX_CUISINE_TERMS) return;
      onChange({
        ...guest,
        likedCuisines: liked.filter((item) => item !== cuisineId),
        dislikedCuisines: [...avoided, cuisineId],
      });
    } else if (avoided.includes(cuisineId)) {
      onChange({
        ...guest,
        dislikedCuisines: avoided.filter((item) => item !== cuisineId),
      });
    } else {
      if (liked.length >= MAX_CUISINE_TERMS) return;
      onChange({ ...guest, likedCuisines: [...liked, cuisineId] });
    }
  };

  return (
    <div className="guest-card">
      <div className="guest-card__row">
        <span className={`avatar avatar--${index % 4}`} aria-hidden="true">
          {initial}
        </span>

        <div className="guest-card__info">
          <input
            className="guest-card__name"
            type="text"
            maxLength={40}
            value={guest.name}
            placeholder={`Person ${index + 1}`}
            aria-label={`Name of person ${index + 1}`}
            onChange={(event) => onChange({ ...guest, name: event.target.value })}
          />
          <p
            className={`guest-card__summary ${
              hasRestrictions ? "" : "guest-card__summary--empty"
            }`}
          >
            {summarize(guest.restrictions)}
          </p>
        </div>

        <button
          type="button"
          className="guest-card__toggle"
          aria-expanded={isOpen}
          aria-label={isOpen ? "Hide restrictions" : "Edit restrictions"}
          onClick={() => setIsOpen((open) => !open)}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            style={{ transform: isOpen ? "rotate(180deg)" : undefined }}
          >
            <path
              d="M6 9l6 6 6-6"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        <button
          type="button"
          className="icon-button"
          aria-label={`Remove ${guest.name.trim() || `person ${index + 1}`}`}
          onClick={() => onRemove(guest.id)}
        >
          &times;
        </button>
      </div>

      {isOpen && (
        <>
          <div className="chip-group">
            {RESTRICTIONS.map((restriction) => {
              const isActive = guest.restrictions.includes(restriction.id);
              return (
                <button
                  key={restriction.id}
                  type="button"
                  aria-pressed={isActive}
                  className={`chip chip--${restriction.kind} ${
                    isActive ? "chip--active" : ""
                  }`}
                  onClick={() => toggleRestriction(restriction.id)}
                >
                  {restriction.label}
                </button>
              );
            })}
          </div>

          <p className="chip-group__hint">
            Cuisines — tap to like, tap again to avoid
          </p>
          <div className="chip-group chip-group--tight">
            {CUISINES.map((cuisine) => {
              const isLiked = (guest.likedCuisines ?? []).includes(cuisine.id);
              const isAvoided = (guest.dislikedCuisines ?? []).includes(
                cuisine.id
              );
              const state = isLiked ? "like" : isAvoided ? "avoid" : "";
              return (
                <button
                  key={cuisine.id}
                  type="button"
                  aria-pressed={isLiked || isAvoided}
                  aria-label={
                    isLiked
                      ? `Likes ${cuisine.label}`
                      : isAvoided
                        ? `Avoids ${cuisine.label}`
                        : cuisine.label
                  }
                  className={`chip chip--cuisine ${state ? `chip--${state}` : ""}`}
                  onClick={() => cycleCuisine(cuisine.id)}
                >
                  {isLiked ? "♥ " : isAvoided ? "✕ " : ""}
                  {cuisine.label}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
