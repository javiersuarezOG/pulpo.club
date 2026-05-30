// Shared location picker used by:
//   - the browse filter panel (web/app/pages.jsx → FilterPanel)
//   - the account newsletter prefs (web/app/account.jsx → NewsletterFilterChips)
//
// The `super_zones` block in the active country's manifest groups individual
// zones (known_zones) into user-facing buckets. Tapping a super-zone toggles
// every child zone in or out; tapping a child toggles just that one. Lakes
// are modelled as super-zones with exactly one child so the same component
// renders them as a single-tap row without a children rail.
//
// Selection state is a Set of zone display names (e.g. "El Tunco"). Names
// match `known_zones[*].name` and the values stamped on listings as
// `zone_name` by web/app/data/listings.ts:adaptListing — so the same Set
// powers both surfaces' downstream filters / preferences.

import React from "react";
import { t } from "../i18n.jsx";
import { SUPER_ZONES, ZONES } from "../data.jsx";

export function LocationFilter({ selected, onChange, locale, helpText }) {
  const sel = selected || new Set();
  const lc = locale || "en";

  const handleZoneToggle = (name) => {
    const next = new Set(sel);
    if (next.has(name)) next.delete(name); else next.add(name);
    onChange(next);
  };

  const handleSuperToggle = (sz) => {
    const next = new Set(sel);
    const allOn = sz.children.every((c) => next.has(c));
    if (allOn) sz.children.forEach((c) => next.delete(c));
    else sz.children.forEach((c) => next.add(c));
    onChange(next);
  };

  // Leftover zones — anything in known_zones that isn't a child of a
  // super_zone. Suchitoto, Ataco, Juayúa, etc. render here.
  const inSuper = new Set();
  SUPER_ZONES.forEach((sz) => sz.children.forEach((c) => inSuper.add(c)));
  const leftovers = ZONES.map((z) => z.name).filter((n) => !inSuper.has(n));

  return (
    <div className="location-filter">
      {helpText && <p className="location-filter-help">{helpText}</p>}

      <div className="location-zones-stack">
        {SUPER_ZONES.map((sz) => {
          const inZone = sz.children.filter((c) => sel.has(c)).length;
          const total = sz.children.length;
          const isAll = total > 0 && inZone === total;
          const isPartial = inZone > 0 && inZone < total;
          const isStandalone = total === 1;

          const name = lc === "es" ? sz.name_es : sz.name_en;
          const subtitle = lc === "es" ? sz.subtitle_es : sz.subtitle_en;
          const tally = isStandalone ? (isAll ? "✓" : "—") : `${inZone}/${total}`;

          const cls = [
            "location-zone-parent",
            sz.type === "lake" ? "is-lake" : "is-beach",
            isAll ? "is-all" : "",
            isPartial ? "is-partial" : "",
          ].filter(Boolean).join(" ");

          return (
            <div key={sz.key} className="location-zone">
              <button
                type="button"
                className={cls}
                aria-pressed={isAll ? "true" : "false"}
                onClick={() => handleSuperToggle(sz)}
              >
                <span className="location-zone-icon" aria-hidden="true">
                  {sz.type === "lake" ? "\u{1F4A7}" : "\u{1F3C4}"}
                </span>
                <span className="location-zone-meta">
                  <span className="location-zone-name">{name}</span>
                  <span className="location-zone-sub">{subtitle}</span>
                </span>
                <span className="location-zone-tally">{tally}</span>
              </button>

              {!isStandalone && (
                <div className="location-zone-children">
                  {sz.children.map((childName) => (
                    <button
                      key={childName}
                      type="button"
                      className={`chip ${sel.has(childName) ? "is-active" : ""}`}
                      onClick={() => handleZoneToggle(childName)}
                    >
                      {childName}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {leftovers.length > 0 && (
        <>
          <div className="location-zone-divider">
            {t("filter.zone.more_places", lc)}
          </div>
          <div className="chip-grid location-zone-more">
            {leftovers.map((n) => (
              <button
                key={n}
                type="button"
                className={`chip ${sel.has(n) ? "is-active" : ""}`}
                onClick={() => handleZoneToggle(n)}
              >
                {n}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
