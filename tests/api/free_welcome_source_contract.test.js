// Producer/consumer contract for the free-welcome `source` discriminator.
//
// Why this exists: the one-click Resubscribe on the unsubscribe confirmation
// page (api/unsubscribe.js) shipped stamping source="unsubscribe_page_resub"
// on its fireFreeWelcome call — a value the consumer endpoint
// (api/internal/free-welcome-send.py#_VALID_SOURCES) did not allow. The
// endpoint 400'd `invalid_source` and the welcome-back email silently never
// sent. Same failure class as the email_type contract: a producer literal
// with no matching entry in the consumer's closed set.
//
// What this test does: grep every fireFreeWelcome producer for the `source:`
// literal it passes, then assert each is present in the _VALID_SOURCES set
// parsed out of the Python endpoint. CI failure here is a 30-second fix:
// add the literal to _VALID_SOURCES in free-welcome-send.py (the consumer
// owns the allowlist), or correct the producer.
//
// Deliberately one-directional (like email_type_contract): a _VALID_SOURCES
// member with no producer is fine (forward-compat), a producer with no
// allowlist entry is the banned state.

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

const CONSUMER_FILE = "api/internal/free-welcome-send.py";

// Every file that calls fireFreeWelcome(...) with a `source:` literal.
// Adding a new caller? Append it here — the grep then covers it.
const PRODUCER_FILES = [
  "api/newsletter.js",
  "api/unsubscribe.js",
];

// fireFreeWelcome({ ..., source: "<X>", ... }) — capture the literal.
const SOURCE_RE = /\bsource:\s*["']([^"']+)["']/g;

function readRepoFile(rel) {
  const abs = path.join(REPO_ROOT, rel);
  if (!fs.existsSync(abs)) {
    throw new Error(
      `[free_welcome_source_contract] file not found: ${rel}. ` +
      `Update the list to match the current topology.`,
    );
  }
  return fs.readFileSync(abs, "utf8");
}

// Parse the _VALID_SOURCES = { "a", "b", ... } literal out of the Python
// endpoint. Cross-language, so we scrape the set body rather than import.
function parseValidSources() {
  const src = readRepoFile(CONSUMER_FILE);
  const m = src.match(/_VALID_SOURCES\s*=\s*\{([\s\S]*?)\}/);
  if (!m) {
    throw new Error(
      "[free_welcome_source_contract] could not locate _VALID_SOURCES set in " +
      CONSUMER_FILE + " — did the declaration change shape?",
    );
  }
  const members = [...m[1].matchAll(/["']([^"']+)["']/g)].map((x) => x[1]);
  return new Set(members);
}

// Collect source literals only from the fireFreeWelcome call sites, not any
// unrelated `source:` key elsewhere in the producer file.
function collectProducerSources() {
  const found = new Map(); // source → [files…]
  for (const rel of PRODUCER_FILES) {
    const source = readRepoFile(rel);
    for (const m of source.matchAll(/fireFreeWelcome\(\s*\{([\s\S]*?)\}\s*\)/g)) {
      const args = m[1];
      let sm;
      SOURCE_RE.lastIndex = 0;
      while ((sm = SOURCE_RE.exec(args)) !== null) {
        const value = sm[1];
        if (!found.has(value)) found.set(value, []);
        found.get(value).push(rel);
      }
    }
  }
  return found;
}

describe("free-welcome source producer/consumer contract", () => {
  it("finds at least one fireFreeWelcome source literal across producers", () => {
    const found = collectProducerSources();
    expect(
      found.size,
      "Greps returned zero fireFreeWelcome source literals — has the producer " +
      "surface moved? Update PRODUCER_FILES or the regex above.",
    ).toBeGreaterThan(0);
  });

  it("every producer source is in the endpoint's _VALID_SOURCES", () => {
    const valid = parseValidSources();
    const found = collectProducerSources();
    const orphans = [];
    for (const [value, files] of found) {
      if (!valid.has(value)) orphans.push({ value, files: [...new Set(files)] });
    }
    expect(
      orphans,
      "A fireFreeWelcome producer stamped a source not in _VALID_SOURCES. Fix: " +
      "add the literal to _VALID_SOURCES in api/internal/free-welcome-send.py — " +
      "otherwise the endpoint 400s invalid_source and the email never sends.",
    ).toEqual([]);
  });

  it("the resubscribe surfaces are covered", () => {
    // Anchor the two known resubscribe sources so a refactor that drops one
    // trips a clear failure.
    const valid = parseValidSources();
    expect(valid.has("resend_resubscribe")).toBe(true);   // homepage form
    expect(valid.has("unsubscribe_page_resub")).toBe(true); // unsub page CTA
  });
});

// Same closed-set contract for the PRO welcome dispatcher. api/unsubscribe.js
// fireProWelcomeBack POSTs source="unsubscribe_page_resub" to
// api/internal/welcome-send.py; that source MUST be in the Pro endpoint's
// _VALID_SOURCES or it 400s invalid_source and the Pro welcome-back never
// sends (the same failure class as the free path).
describe("pro-welcome source producer/consumer contract", () => {
  const PRO_CONSUMER = "api/internal/welcome-send.py";
  const PRO_PRODUCER = "api/unsubscribe.js";

  function parseProValidSources() {
    const src = readRepoFile(PRO_CONSUMER);
    const m = src.match(/_VALID_SOURCES\s*=\s*\{([\s\S]*?)\}/);
    if (!m) throw new Error(`could not locate _VALID_SOURCES in ${PRO_CONSUMER}`);
    return new Set([...m[1].matchAll(/["']([^"']+)["']/g)].map((x) => x[1]));
  }

  function collectProProducerSources() {
    const src = readRepoFile(PRO_PRODUCER);
    const out = new Set();
    // Target the Pro welcome-back payload precisely: the `source:` literal
    // sitting next to `variant: "welcome_back"` in fireProWelcomeBack's
    // JSON.stringify body. Avoids picking up unrelated `source:` keys
    // (the PostHog capture, the free dispatch) elsewhere in the file.
    for (const m of src.matchAll(
      /variant:\s*["']welcome_back["']\s*,\s*source:\s*["']([^"']+)["']/g,
    )) {
      out.add(m[1]);
    }
    return out;
  }

  it("every Pro producer source is in welcome-send.py _VALID_SOURCES", () => {
    const valid = parseProValidSources();
    const found = collectProProducerSources();
    expect(found.size).toBeGreaterThan(0);
    const orphans = [...found].filter((s) => !valid.has(s));
    expect(
      orphans,
      "fireProWelcomeBack stamped a source not in welcome-send.py _VALID_SOURCES — " +
      "add it there or the endpoint 400s invalid_source and the Pro welcome-back never sends.",
    ).toEqual([]);
  });

  it("unsubscribe_page_resub is allowlisted on the Pro endpoint", () => {
    expect(parseProValidSources().has("unsubscribe_page_resub")).toBe(true);
  });
});
