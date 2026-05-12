// Star pill badge — renders a listing's star_rating as a compact "★ 4.5"
// chip with bilingual accessible labelling.
//
// Backed by listing.star_rating (0.0–5.0 in 0.5 increments, derived in
// pulpo/derived_rules.derive_star_rating from rank_score). When the
// rating is 0.0 the pill renders nothing — a missing-rank-score listing
// shouldn't show "0 stars" because that reads worse than "no signal".
//
// Bilingual at write time per the rewrite plan (Q1): ARIA label reads
// "4.5 stars out of 5" in English / "4,5 estrellas de 5" in Spanish.
// Spanish uses the comma decimal separator following SV convention
// (mirrors what Intl.NumberFormat(es) produces).
import React from "react";
import { t } from "../i18n.jsx";

/**
 * @param {object} props
 * @param {number} props.stars              — 0.0..5.0 in 0.5 increments
 * @param {("sm"|"md")} [props.size="md"]   — sm = card badge, md = detail page
 * @param {string} [props.locale]           — override the auto-detected locale
 * @param {string} [props.className]
 */
export function StarPill({ stars, size = "md", locale, className = "" }) {
  if (typeof stars !== "number" || !Number.isFinite(stars) || stars <= 0) {
    return null;
  }
  // Clamp defensively — the deriver caps at 5.0 but a malformed
  // ranked.json record could send a higher value.
  const value = Math.max(0, Math.min(5, stars));
  // .0 stars renders as the integer (e.g. "4"), .5 as "4.5" — matches
  // the brief's "★ 4.5" copy without sprinkling .0 across the page.
  const lc = (locale || (typeof document !== "undefined" ? document.documentElement.lang : "en")) || "en";
  const decimalSep = lc === "es" ? "," : ".";
  const isHalf = value % 1 !== 0;
  const displayValue = isHalf
    ? `${Math.floor(value)}${decimalSep}5`
    : String(Math.floor(value));
  // Same string token as the auto-detected locale fallback — keeps the
  // pill's ARIA label sourcing from the i18n catalog.
  const ariaLabel = t("star_pill.aria", lc, { value: displayValue });
  return (
    <span
      className={`star-pill star-pill-${size} ${className}`.trim()}
      role="img"
      aria-label={ariaLabel}
    >
      <span className="star-pill-glyph" aria-hidden="true">★</span>
      <span className="star-pill-value">{displayValue}</span>
    </span>
  );
}
