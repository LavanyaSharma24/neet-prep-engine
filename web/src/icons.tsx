/** Inline SVG icons — no font/asset requests, just markup, themeable via
 * currentColor. Kept intentionally minimal: one visual family (rounded
 * stroke, 1.75px weight) so the three answer-state badges read as a set. */

const commonProps = {
  width: 14,
  height: 14,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2.25,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function CheckCircleIcon() {
  return (
    <svg {...commonProps}>
      <path d="M8 12.5l2.5 2.5L16 9" />
      <circle cx="12" cy="12" r="9.25" />
    </svg>
  );
}

export function SparkleIcon() {
  return (
    <svg {...commonProps}>
      <path d="M12 3.5l1.8 4.9 4.9 1.8-4.9 1.8L12 16.9l-1.8-4.9-4.9-1.8 4.9-1.8L12 3.5z" />
      <path d="M19 15.5l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7.7-1.9z" />
    </svg>
  );
}

export function FlagIcon() {
  return (
    <svg {...commonProps}>
      <path d="M12 9v6.5" />
      <circle cx="12" cy="17.5" r="0.75" fill="currentColor" stroke="none" />
      <path d="M12 3.75a8.25 8.25 0 108.25 8.25A8.25 8.25 0 0012 3.75z" />
    </svg>
  );
}
