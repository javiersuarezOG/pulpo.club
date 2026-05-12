// Discovery filter pills — All / ★ Top rated / Under $250K / Gated /
// Waterfront. Horizontal row, click jumps to /browse?tag=<value>.
//
// Same component renders on the homepage and on /browse (Phase 5).
// The `source_page` prop differentiates them in telemetry so the
// dashboard can split funnel-from-homepage vs. funnel-from-browse.
//
// Mobile-first: pills horizontally scroll when they overflow at
// 375px width; fit inline at 768px+. Active state on /browse is
// driven by the URL filter — on the homepage there's no active
// state because clicking ALWAYS navigates away.
import React from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { DISCOVERY_TAGS, DISCOVERY_PILL_LABELS } from "../config/ia.ts";

/**
 * @param {object} props
 * @param {object} props.app          — App state with goBrowse(...)
 * @param {string} props.locale       — "en" | "es"
 * @param {string} props.sourcePage   — "homepage" | "browse"
 * @param {string} [props.activeTag]  — currently-active pill (browse only)
 */
export function DiscoveryPills({ app, locale, sourcePage, activeTag }) {
  const onClick = (tag) => {
    track("discovery_pill.clicked", {
      filter: tag,
      source_page: sourcePage,
    });
    if (tag === "all") {
      app.goBrowse({});
      return;
    }
    // Pass the tag as the category slug — BrowsePage's
    // buildFiltersForCategory expands "top_rated" / "under_250k" /
    // "gated" / "waterfront" into the corresponding discovery_tags
    // filter entry. Reusing the category param keeps URL contract
    // + popstate resync simple.
    app.goBrowse({ category: tag });
  };

  return (
    <nav className="discovery-pills" aria-label={t("discovery_pill.heading", locale)}>
      <ul className="discovery-pills-list" role="list">
        <li>
          <button
            type="button"
            className={`discovery-pill ${activeTag == null ? "is-active" : ""}`.trim()}
            onClick={() => onClick("all")}
            aria-pressed={activeTag == null}
          >
            {t("discovery_pill.all", locale)}
          </button>
        </li>
        {DISCOVERY_TAGS.map((tag) => {
          const label = DISCOVERY_PILL_LABELS[tag];
          const isActive = activeTag === tag;
          return (
            <li key={tag}>
              <button
                type="button"
                className={`discovery-pill ${isActive ? "is-active" : ""}`.trim()}
                onClick={() => onClick(tag)}
                aria-pressed={isActive}
              >
                {label[locale === "es" ? "es" : "en"]}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
