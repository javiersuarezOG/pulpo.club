// Compact serialization of a free-member newsletter filter — the WRITER
// side (the /api/newsletter-prefs endpoint reads the current value to
// prefill the form and writes the new one). The READER is the pipeline's
// automation/newsletter/prefs_codec.py; the two MUST stay in lockstep.
// tests/api/prefs_codec_contract.test.js pins JS↔Python parity on a shared
// fixture set.
//
// The filter lives on the Resend contact's `last_name` field (side-channel),
// NOT contact properties — see prefs_codec.py's header for why (the pipeline
// reads the audience with one list call, which omits properties but returns
// last_name, and Pulpo never renders last_name).
//
// Format (after the `pulpo-filter:` prefix): `k=v` pairs joined by `;`:
//   pulpo-filter:pt=land,house;mx=500000;mn=0;z=el_tunco;cat=beachfront
//   pt property_types (csv)   mx max_price_usd (int)   z zones (csv)
//   mn min_price_usd (int)    cat categories (csv)
//
// decode() is total — malformed input yields {} (→ empty filter), never throws.

const PREFIX = "pulpo-filter:";

const SLUG_KEYS = { pt: "property_types", z: "zones", cat: "categories" };
const INT_KEYS = { mx: "max_price_usd", mn: "min_price_usd" };

function cleanSlug(s) {
  return String(s).trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
}

function cleanSlugList(raw) {
  const out = [];
  for (const part of String(raw).split(",")) {
    const slug = cleanSlug(part);
    if (slug && !out.includes(slug)) out.push(slug);
  }
  return out;
}

// Parse a `last_name` value into a filter object. Total — never throws.
function decode(raw) {
  if (typeof raw !== "string") return {};
  const s = raw.trim();
  if (!s.startsWith(PREFIX)) return {};
  const body = s.slice(PREFIX.length);
  const out = {};
  for (const pair of body.split(";")) {
    const eq = pair.indexOf("=");
    if (eq < 0) continue;
    const k = pair.slice(0, eq).trim().toLowerCase();
    const v = pair.slice(eq + 1);
    if (SLUG_KEYS[k]) {
      const vals = cleanSlugList(v);
      if (vals.length) out[SLUG_KEYS[k]] = vals;
    } else if (INT_KEYS[k]) {
      const digits = (v.match(/\d/g) || []).join("");
      if (digits) {
        const n = parseInt(digits, 10);
        // min=0 carries no floor — drop it so round-trips are stable.
        if (!(k === "mn" && n === 0)) out[INT_KEYS[k]] = n;
      }
    }
  }
  return out;
}

// Serialize a filter object to a `last_name` value (incl. prefix). Empty
// filter → "" (caller clears last_name). Mirrors prefs_codec.py `encode`.
function encode(pref) {
  const parts = [];
  for (const [short, field] of Object.entries(SLUG_KEYS)) {
    const vals = pref && pref[field];
    if (Array.isArray(vals)) {
      const slugs = vals.map((x) => cleanSlug(x)).filter(Boolean);
      if (slugs.length) parts.push(`${short}=${slugs.join(",")}`);
    }
  }
  for (const [short, field] of Object.entries(INT_KEYS)) {
    const v = pref && pref[field];
    if (typeof v === "number" && Number.isFinite(v) && v > 0) {
      parts.push(`${short}=${Math.trunc(v)}`);
    }
  }
  return parts.length ? PREFIX + parts.join(";") : "";
}

module.exports = { PREFIX, encode, decode };
