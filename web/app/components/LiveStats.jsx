// PR-4c — Live header stats chip.
// Reads /data/last_updated.json once on mount; renders three dim metrics
// ("Sources online · Listings · Updated") on desktop, collapses into a
// click-popover behind an info icon on mobile.
//
// We deliberately tolerate fetch failure: stats are decoration, not gating
// data — if the file is missing or malformed we render nothing rather than
// blowing up the whole header.
import React, { useEffect, useState } from "react";
import { t } from "../i18n.jsx";
import { Icon } from "../components.jsx";

function fmtRelative(iso, locale) {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return null;
  const mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
  // Use Intl.RelativeTimeFormat for proper EN/ES inflection.
  const lc = locale === "es" ? "es" : "en";
  const rtf = new Intl.RelativeTimeFormat(lc, { numeric: "auto" });
  if (mins < 1) return rtf.format(0, "minute");
  if (mins < 60) return rtf.format(-mins, "minute");
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return rtf.format(-hrs, "hour");
  const days = Math.round(hrs / 24);
  return rtf.format(-days, "day");
}

function LiveStats({ locale }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false); // mobile popover

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

  const statuses = data.source_status || {};
  const sourcesOnline = Object.values(statuses).filter(s => s === "green" || s === "yellow").length;
  const sourcesTotal = Object.keys(statuses).length;
  const listingsCount = typeof data.total_listings === "number" ? data.total_listings : null;
  const updatedRel = fmtRelative(data.last_updated, locale);

  if (sourcesTotal === 0 && listingsCount == null && !updatedRel) return null;

  const labels = {
    sources: t("stats.sources", locale),
    listings: t("stats.listings", locale),
    updated: t("stats.updated", locale),
    info: t("stats.info_label", locale),
  };

  return (
    <div className="live-stats">
      <div className="live-stats-inline" aria-label={labels.info}>
        {sourcesTotal > 0 && (
          <span className="ls-item" title={labels.sources}>
            <span className="ls-dot" data-state={sourcesOnline === sourcesTotal ? "ok" : "warn"} aria-hidden="true" />
            <span className="ls-num">{sourcesOnline}/{sourcesTotal}</span>
            <span className="ls-label">{labels.sources}</span>
          </span>
        )}
        {listingsCount != null && (
          <span className="ls-item" title={labels.listings}>
            <span className="ls-num">{listingsCount.toLocaleString(locale === "es" ? "es-CR" : "en-US")}</span>
            <span className="ls-label">{labels.listings}</span>
          </span>
        )}
        {updatedRel && (
          <span className="ls-item" title={labels.updated}>
            <span className="ls-label">{labels.updated}</span>
            <span className="ls-num">{updatedRel}</span>
          </span>
        )}
      </div>
      <button
        type="button"
        className="live-stats-toggle"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-label={labels.info}
        title={labels.info}
      >
        <Icon name="info" size={14} strokeWidth={1.8} />
      </button>
      {open && (
        <div className="live-stats-popover" role="dialog">
          {sourcesTotal > 0 && (
            <div className="ls-row">
              <span className="ls-dot" data-state={sourcesOnline === sourcesTotal ? "ok" : "warn"} aria-hidden="true" />
              {sourcesOnline}/{sourcesTotal} {labels.sources}
            </div>
          )}
          {listingsCount != null && (
            <div className="ls-row">{listingsCount.toLocaleString(locale === "es" ? "es-CR" : "en-US")} {labels.listings}</div>
          )}
          {updatedRel && (
            <div className="ls-row">{labels.updated} {updatedRel}</div>
          )}
        </div>
      )}
    </div>
  );
}

export { LiveStats };
