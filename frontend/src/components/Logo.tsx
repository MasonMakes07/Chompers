interface LogoProps {
  className?: string;
  /** Rendered as the SVG's accessible name; omit for decorative use. */
  label?: string;
}

// Renders the Chompers mark: three dango balls on a level skewer, resting on
// a plate.
export function Logo({ className, label }: LogoProps) {
  return (
    <svg
      className={className}
      viewBox="34 55 148 69"
      role={label ? "img" : "presentation"}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {/* Plate */}
      <ellipse
        cx="100"
        cy="98"
        rx="62"
        ry="22"
        fill="#eef2ec"
        stroke="#3f5a45"
        strokeWidth="3"
      />
      <ellipse cx="100" cy="95" rx="43" ry="14" fill="#dbe6dd" />
      {/* Skewer — level, and drawn before the balls so each one hides the
          length it passes through. The left end stops inside the first ball
          so it never pokes out the back. */}
      <line
        x1="52"
        y1="73"
        x2="178"
        y2="73"
        stroke="#c2a878"
        strokeWidth="4"
        strokeLinecap="round"
      />
      {/* Three equal balls, centred on the skewer. Their bottoms land on the
          inner ellipse — the plate's surface — so the rim passes behind them
          rather than under them. */}
      <circle cx="64" cy="73" r="15" fill="#d9b354" />
      <circle cx="100" cy="73" r="15" fill="#3f5a45" />
      <circle cx="136" cy="73" r="15" fill="#b58575" />
    </svg>
  );
}
