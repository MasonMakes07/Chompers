// One guest: their name and the restrictions they carry.

import { RESTRICTIONS, type GuestDraft, type RestrictionId } from "../types";

interface GuestRowProps {
  guest: GuestDraft;
  index: number;
  canRemove: boolean;
  onChange: (guest: GuestDraft) => void;
  onRemove: (id: string) => void;
}

export function GuestRow({
  guest,
  index,
  canRemove,
  onChange,
  onRemove,
}: GuestRowProps) {
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

  return (
    <div className="guest-row">
      <div className="guest-row__header">
        <input
          className="guest-row__name"
          type="text"
          maxLength={40}
          value={guest.name}
          placeholder={`Person ${index + 1}`}
          aria-label={`Name of person ${index + 1}`}
          onChange={(event) => onChange({ ...guest, name: event.target.value })}
        />
        {canRemove && (
          <button
            type="button"
            className="guest-row__remove"
            aria-label={`Remove person ${index + 1}`}
            onClick={() => onRemove(guest.id)}
          >
            &times;
          </button>
        )}
      </div>

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
    </div>
  );
}
