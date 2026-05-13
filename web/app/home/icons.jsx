// Homepage-v2 icons. One export per glyph so tree-shaking strips the
// unused ones from the bundle. Tabler-outline-style: 24×24 viewBox,
// stroke="currentColor", strokeWidth controllable via prop.
//
// The existing components.jsx Icon component covers arrow_right /
// close / map_pin / search / sparkle / heart / star. Anything the
// homepage redesign needs that isn't already there lives here.
import React from "react";

function svg(children, { size = 24, strokeWidth = 1.6, className = "", title } = {}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export const IconMailFast = (p = {}) => svg(
  <>
    <path d="M3 7h13a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H9" />
    <path d="M3 7l8 6 8-6" />
    <path d="M3 12H1" />
    <path d="M5 17H2" />
  </>, p,
);

export const IconListSearch = (p = {}) => svg(
  <>
    <path d="M4 6h12" />
    <path d="M4 12h7" />
    <path d="M4 18h5" />
    <circle cx="16" cy="16" r="3.5" />
    <path d="m21 21-2.5-2.5" />
  </>, p,
);

export const IconMapPinHeart = (p = {}) => svg(
  <>
    <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z" />
    <path d="M9.2 9.5a1.7 1.7 0 0 1 2.8-1.2c.8 0 1.7-.5 2.5 0a1.7 1.7 0 0 1 .3 2.6L12 13l-2.6-2.1a1.7 1.7 0 0 1-.2-1.4z" />
  </>, p,
);

export const IconRipple = (p = {}) => svg(
  <>
    <path d="M3 12c2 2 4 2 6 0s4-2 6 0 4 2 6 0" />
    <path d="M3 8c2 2 4 2 6 0s4-2 6 0 4 2 6 0" opacity="0.55" />
    <path d="M3 16c2 2 4 2 6 0s4-2 6 0 4 2 6 0" opacity="0.55" />
  </>, p,
);

export const IconBeach = (p = {}) => svg(
  <>
    {/* Palm-ish umbrella over a wave line */}
    <path d="M13 4c-3 0-6 2-6 5l6-2-6 2c0-3 3-5 6-5z" />
    <path d="M13 4c3 0 6 2 6 5l-6-2 6 2c0-3-3-5-6-5z" />
    <path d="M13 4v15" />
    <path d="M2 21c2 0 2-1.2 5-1.2s3 1.2 5 1.2 3-1.2 5-1.2 3 1.2 5 1.2" />
  </>, p,
);

export const IconLock = (p = {}) => svg(
  <>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </>, p,
);

export const IconArrowDownRight = (p = {}) => svg(
  <>
    <path d="M7 7l10 10" />
    <polyline points="17 9 17 17 9 17" />
  </>, p,
);

export const IconSparkles = (p = {}) => svg(
  <>
    <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z" />
    <path d="M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z" />
  </>, p,
);

export const IconArrowRight = (p = {}) => svg(
  <>
    <line x1="5" y1="12" x2="19" y2="12" />
    <polyline points="12 5 19 12 12 19" />
  </>, p,
);

export const IconMenu2 = (p = {}) => svg(
  <>
    <line x1="4" y1="7" x2="20" y2="7" />
    <line x1="4" y1="17" x2="20" y2="17" />
  </>, p,
);

export const IconX = (p = {}) => svg(
  <>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </>, p,
);

// Filled bolt — used by the Just In pill in the v3 hero. Tabler-style
// lightning glyph rendered as a filled shape rather than stroke so it
// reads bold against the clay-orange pill background. Skips the stroke
// settings from svg() by inlining its own.
export const IconBoltFilled = ({ size = 24, className = "", title } = {}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    className={className}
    aria-hidden={title ? undefined : true}
    role={title ? "img" : undefined}
  >
    {title ? <title>{title}</title> : null}
    <path d="M13 2 L4 14 L11 14 L10 22 L20 10 L13 10 Z" />
  </svg>
);
