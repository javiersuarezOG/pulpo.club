// PR-4c — Live header stats chip.
// Reads /data/last_updated.json once on mount and renders a single
// "Listings" count with a pulsing live dot. Earlier iterations also
// surfaced Sources + Updated, but those were dropped — the live dot
// next to the listings number carries the "this is live data" signal
// on its own and the rail reads cleaner.
//
// We deliberately tolerate fetch failure: stats are decoration, not gating
// data — if the file is missing or malformed we render nothing rather than
// blowing up the whole header.
import React, { useEffect, useState } from "react";
import { t } from "../i18n.jsx";
import { useListings } from "../data/use-listings.tsx";

function LiveStats({ locale }) {
  const [data, setData] = useState(null);
  // Source the listings count from the same loaded array Browse renders
  // so the header chip can't drift from the in-page "{N} listings" count.
  // last_updated.json#total_listings is the raw pipeline total (includes
  // is_incomplete rows that applyFilters() hides by default), so reading
  // it directly produced a visible mismatch (923 in header vs 873 on
  // /browse).
  const listings = useListings();

  useEffect(() => {
    let cancelled = false;
    import("../telemetry/perf").then(({ timedFetch }) =>
      timedFetch("last_updated.json", "/data/last_updated.json", { headers: { Accept: "application/json" } })
    )
      .then(r => (r.ok ? r.json() : null))
      .then(j => { if (!cancelled) setData(j); })
      .catch(() => { /* swallow — see header comment */ });
    return () => { cancelled = true; };
  }, []);

  if (!data) return null;

  // Mirror the default-filter exclusions in pages.jsx applyFilters() so the
  // header chip matches what /browse shows with no user filters applied.
  // Fall back to the pipeline total while listings are still loading; if
  // it's missing too, omit the chip.
  const browsableCount = listings.length
    ? listings.filter(l => !l.is_sold && !l.is_incomplete).length
    : null;
  const listingsCount = browsableCount
    ?? (typeof data.total_listings === "number" ? data.total_listings : null);

  if (listingsCount == null) return null;

  const labels = {
    listings: t("stats.listings", locale),
  };

  return (
    <div className="live-stats">
      <div className="live-stats-inline">
        <span className="ls-item" title={labels.listings}>
          <span className="ls-dot ls-dot--live" data-state="ok" aria-hidden="true" />
          <span className="ls-num">{listingsCount.toLocaleString(locale === "es" ? "es-CR" : "en-US")}</span>
          <span className="ls-label">{labels.listings}</span>
        </span>
      </div>
    </div>
  );
}

export { LiveStats };
