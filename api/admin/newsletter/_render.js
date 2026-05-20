// Simplified newsletter renderer for the admin preview widget.
//
// NOT byte-identical to the production renderer (automation/newsletter/
// render_html.py). The production renderer is a magazine layout with
// editorial commentary, hero images, paywall states, callouts. The admin
// preview gives operators a fast, accurate read on which listings their
// filter selected — clean cards in rank order, with price, location, key
// flags, and a thumbnail.
//
// Operators wanting a byte-identical preview should use the existing
// `pulpo-newsletter` GitHub Actions workflow with `only_email=<their
// address>`. That path uses the real Python renderer.

const SITE_ROOT = (process.env.PULPO_SITE_ROOT || "https://pulpo.club").replace(/\/$/, "");

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtMoney(n) {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return "$" + Math.round(Number(n)).toLocaleString("en-US");
}

function photoUrl(listing) {
  const urls = listing.photo_urls || [];
  if (urls.length && typeof urls[0] === "string" && urls[0].startsWith("http")) return urls[0];
  const hero = listing.hero_photo_path || "";
  if (hero.startsWith("http")) return hero;
  if (hero) return SITE_ROOT + (hero.startsWith("/") ? hero : "/" + hero);
  return "";
}

function locationLine(l) {
  const parts = [];
  if (l.municipality) parts.push(l.municipality);
  if (l.department) parts.push(l.department);
  return parts.join(" · ");
}

function pickTitle(l, locale) {
  const tc = l.title_canonical || {};
  return tc[locale] || tc.en || l.title || "Listing";
}

function pillsFor(l) {
  const pills = [];
  if (l.property_type) pills.push(l.property_type);
  if (l.is_beachfront) pills.push("beachfront");
  else if (l.is_walk_to_beach) pills.push("walk to beach");
  if (l.has_power && l.has_water) pills.push("power+water");
  if (l.is_repriced) pills.push("repriced");
  if (l.is_motivated) pills.push("motivated");
  return pills.slice(0, 4);
}

function cardHtml(listing, rank, locale, opts) {
  const { paywalled } = opts || {};
  const photo = photoUrl(listing);
  const title = pickTitle(listing, locale);
  const url = listing.url || `${SITE_ROOT}/listing/${encodeURIComponent(`${listing.source}-${listing.source_id}`)}`;
  const price = fmtMoney(listing.price_usd);
  const ppm = listing.price_per_m2 ? `$${Math.round(listing.price_per_m2).toLocaleString("en-US")}/m²` : "";
  const area = listing.area_m2 ? `${Math.round(listing.area_m2).toLocaleString("en-US")} m²` : "";
  const pills = pillsFor(listing);
  const meta = [locationLine(listing), area, ppm].filter(Boolean).join(" · ");

  return `
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0 0 20px;border:1px solid #e7e7e0;border-radius:8px;overflow:hidden;background:#fff;">
    <tr>
      <td style="padding:0;">
        ${photo ? `
        <a href="${escapeHtml(url)}" style="display:block;">
          <img src="${escapeHtml(photo)}" alt="" width="100%" style="display:block;width:100%;max-height:240px;object-fit:cover;border:none;" />
        </a>` : ""}
      </td>
    </tr>
    <tr>
      <td style="padding:16px 20px 18px;">
        <div style="font-family:Menlo,monospace;font-size:11px;letter-spacing:0.1em;color:#7a7a72;margin:0 0 6px;text-transform:uppercase;">
          Pick · ${String(rank).padStart(2, "0")}
        </div>
        <div style="font-family:Georgia,serif;font-size:20px;line-height:26px;color:#1a201c;margin:0 0 8px;">
          <a href="${escapeHtml(url)}" style="color:#1a201c;text-decoration:none;">${escapeHtml(title)}</a>
        </div>
        <div style="font-size:13px;color:#5a605b;margin:0 0 10px;">${escapeHtml(meta)}</div>
        <div style="font-size:18px;font-weight:600;color:#1a201c;margin:0 0 10px;">${escapeHtml(price)}</div>
        ${pills.length ? `
        <div style="margin:0 0 10px;">
          ${pills.map((p) => `<span style="display:inline-block;font-size:11px;background:#f0f1ec;color:#3d4540;border-radius:999px;padding:3px 10px;margin-right:4px;">${escapeHtml(p)}</span>`).join("")}
        </div>` : ""}
        ${paywalled ? `
        <div style="margin-top:10px;font-size:12px;color:#7a7a72;font-style:italic;border-top:1px dashed #e7e7e0;padding-top:10px;">
          (Free tier preview — full pick body unlocks on Pulpo Pro.)
        </div>` : ""}
      </td>
    </tr>
  </table>`;
}

function shellHtml({ heading, intro, body, footer }) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Pulpo · admin preview</title>
</head>
<body style="margin:0;padding:0;background:#f4f3ed;font-family:-apple-system,Segoe UI,sans-serif;color:#1a201c;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f4f3ed;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" style="max-width:640px;width:100%;background:#fff;border-radius:10px;border:1px solid #e7e7e0;padding:24px 28px 28px;">
          <tr><td>
            <div style="font-family:Menlo,monospace;font-size:11px;letter-spacing:0.1em;color:#7a7a72;text-transform:uppercase;margin:0 0 4px;">
              [PULPO ADMIN TEST]
            </div>
            <h1 style="font-family:Georgia,serif;font-size:30px;line-height:36px;color:#1a201c;margin:0 0 6px;">
              ${escapeHtml(heading)}
            </h1>
            <p style="font-size:14px;color:#5a605b;margin:0 0 24px;line-height:22px;">${escapeHtml(intro)}</p>
            ${body}
            <hr style="border:none;border-top:1px solid #e7e7e0;margin:24px 0 16px;" />
            <p style="font-size:12px;color:#7a7a72;line-height:18px;margin:0;">${footer}</p>
          </td></tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;
}

function renderAdminIssue({ picks, cohort, locale, issueNumber, filterTrace }) {
  const paywallAll = cohort === "free_prefs";
  const heading = `Issue ${String(issueNumber).padStart(2, "0")} preview`;
  const intro = [
    `Cohort: ${cohort}.`,
    `Locale: ${locale}.`,
    `${picks.length} pick${picks.length === 1 ? "" : "s"} selected from the current ranked.json.`,
  ].join(" ");
  const cards = picks
    .map((l, i) => cardHtml(l, i + 1, locale, { paywalled: paywallAll && i > 0 }))
    .join("\n");
  const body = picks.length
    ? cards
    : `<p style="font-size:14px;color:#5a605b;background:#f4f3ed;border-radius:6px;padding:16px;">No listings match this filter. Try widening the price band or removing a category constraint.</p>`;
  const footer = [
    `This is an admin test — not the production newsletter HTML.`,
    `For byte-identical production-renderer previews, dispatch the <code>pulpo-newsletter</code> GitHub Actions workflow with <code>only_email</code> set.`,
    `Filter spec: ${escapeHtml(JSON.stringify(filterTrace || {}))}`,
  ].join(" ");
  return shellHtml({ heading, intro, body, footer });
}

module.exports = { renderAdminIssue, shellHtml };
