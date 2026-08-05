#!/usr/bin/env node
// Price-sync linter — a fast (<1s) static check for the "hidden price
// surface" drift class: web/app/lib/pricing.ts is the single source of
// truth for the Pulpo Pro price, but the Python newsletter renderer
// (automation/newsletter/i18n.py) hardcodes its own price strings and
// once drifted to a stale "$19/month" (fixed in newsletter v2.2).
//
// What this checks: every currency-literal (e.g. "$4.99", "€4,99")
// found in a NON-COMMENT line of each SCAN_FILES entry must match one
// of the amounts declared in pricing.ts's PRICES block. If pricing.ts
// moves to 5.99 and the newsletter still says 4.99, CI fails with the
// offending file:line.
//
// Scope: literal price drift only. It does NOT verify the Stripe Price
// object — that rotation playbook lives in pricing.ts's header comment
// and the live-preview walk covers it.
//
// EXEMPT: comment lines (leading #) — the newsletter file documents its
// price history in comments, and history is allowed to be stale.
// A code line may carry `# price-sync-allow: <reason>` to be skipped;
// each marker must carry a reason so it stays auditable.
//
// Usage: `node scripts/check_price_sync.mjs` (zero deps).
// Wired into .github/workflows/ci.yml next to the other repo linters.

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PRICING_TS = "web/app/lib/pricing.ts";

// Files that render a user-visible price OUTSIDE the pricing.ts import
// graph. Add every new hidden price surface here — the newsletter
// precedent shows they exist.
export const SCAN_FILES = ["automation/newsletter/i18n.py"];

const ALLOW_MARKER = "price-sync-allow:";

// Only subscription-price SHAPES are flagged — two forms:
//   1. decimal amounts:  "$4.99", "€4,99"
//   2. per-month forms:  "$19/month", "$19/mo", "$19/mes" (the actual
//      historical drift string)
// Deliberately NOT matched: listing-price buckets like "$50k" /
// "Under $500k" and plain integers with no period suffix — those are
// catalog copy, not the Pro price.
const PRICE_PATTERNS = [
  /[$€]\s?(\d+[.,]\d{2})(?!\d)/g,
  /[$€]\s?(\d+(?:[.,]\d{1,2})?)\s*\/\s*(?:mo\b|month|mes\b)/g,
];

export function extractCanonicalAmounts(pricingSource) {
  // The PRICES block declares `amount: 4.99` rows; displayString rows
  // repeat the number with a glyph. Collect both, normalized.
  const amounts = new Set();
  for (const m of pricingSource.matchAll(/amount:\s*(\d+(?:\.\d{1,2})?)/g)) {
    amounts.add(normalizeAmount(m[1]));
  }
  for (const m of pricingSource.matchAll(/displayString:\s*"[$€](\d+(?:[.,]\d{1,2})?)"/g)) {
    amounts.add(normalizeAmount(m[1]));
  }
  return amounts;
}

export function normalizeAmount(raw) {
  return Number.parseFloat(String(raw).replace(",", ".")).toFixed(2);
}

export function findPriceViolations(source, canonicalAmounts, { commentPrefix = "#" } = {}) {
  const violations = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trimStart();
    if (trimmed.startsWith(commentPrefix)) continue;
    if (line.includes(ALLOW_MARKER)) continue;
    const seenAt = new Set();
    for (const pattern of PRICE_PATTERNS) {
      for (const m of line.matchAll(pattern)) {
        if (seenAt.has(m.index)) continue; // "$4.99/mo" matches both patterns
        seenAt.add(m.index);
        const amount = normalizeAmount(m[1]);
        if (!canonicalAmounts.has(amount)) {
          violations.push({ line: i + 1, literal: m[0].trim(), amount, text: trimmed.trim() });
        }
      }
    }
  }
  return violations;
}

export function main() {
  const pricingSource = fs.readFileSync(path.resolve(PRICING_TS), "utf8");
  const canonical = extractCanonicalAmounts(pricingSource);
  if (canonical.size === 0) {
    console.error(
      `check_price_sync: could not extract any amounts from ${PRICING_TS} — ` +
        "the PRICES block regex no longer matches. Update this script alongside pricing.ts."
    );
    return 1;
  }

  let failed = false;
  for (const rel of SCAN_FILES) {
    const source = fs.readFileSync(path.resolve(rel), "utf8");
    const violations = findPriceViolations(source, canonical);
    for (const v of violations) {
      failed = true;
      console.error(
        `${rel}:${v.line}: price literal ${v.literal} (=${v.amount}) does not match ` +
          `pricing.ts amounts {${[...canonical].join(", ")}}\n    ${v.text}`
      );
    }
  }

  if (failed) {
    console.error(
      "\nPrice drift detected. Either update the surface to the canonical price " +
        `from ${PRICING_TS}, or (for a genuinely independent number) add ` +
        `\`${ALLOW_MARKER} <reason>\` on the line.`
    );
    return 1;
  }
  console.log(
    `check_price_sync: OK — ${SCAN_FILES.length} surface(s) match pricing.ts ` +
      `amounts {${[...canonical].join(", ")}}`
  );
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
