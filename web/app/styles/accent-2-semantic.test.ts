// `--accent-2` is heart red — semantically reserved for the save/heart
// state on listings and for error/invalid form states. Using it anywhere
// else creates two problems: (a) the color collides visually with the
// save button (recipients see red and assume "save"), and (b) red on a
// calm green/paper brand reads as warning, which is wrong for any
// neutral-context use (the share-pin highlight that shipped briefly with
// --accent-2 was a real example).
//
// This test walks every rule in index.css that resolves to `--accent-2`
// and asserts the selector text contains at least one save/error
// semantic word. Any non-semantic use should either (a) switch to a
// different brand token, or (b) get a justified exception added below.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const CSS_PATH = resolve(__dirname, "index.css");

// Words that, when present in the rule's selector, make `--accent-2`
// a semantically-justified choice. Add to this list (with justification)
// rather than ignoring violations.
const SEMANTIC_WORDS = [
  "heart",           // save action
  "save",            // save action (CTAs / aria-labels)
  "bookmark",
  "wishlist",
  "aria-invalid",    // form invalid state
  "invalid",
  "error",           // error message / state
  "danger",
];

// Rules that legitimately reference --accent-2 but don't carry a
// semantic word in their selector (rare). Add the exact selector text
// here with a one-line justification comment.
const SELECTOR_EXCEPTIONS: Array<{ selector: string; why: string }> = [
  // (none yet — extend as needed)
];

function looksSemantic(selector: string): boolean {
  const lc = selector.toLowerCase();
  return SEMANTIC_WORDS.some((w) => lc.includes(w));
}

function isException(selector: string): boolean {
  return SELECTOR_EXCEPTIONS.some((e) => e.selector === selector.trim());
}

// Parse CSS rules from the file. Splits on `}` to get rule blocks, then
// for each block extracts the selector (everything before `{`) and the
// body. CSS is forgiving enough that this naive split holds for our
// hand-written file — we don't use nested rules or `@supports {}`
// blocks that would break it.
function stripComments(css: string): string {
  // Strip `/* ... */` block comments (no nested comments in CSS).
  // Without this, the selector extracted before a rule includes the
  // preceding comment text and the error message becomes unreadable.
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function extractAccent2Rules(css: string): Array<{ selector: string; body: string }> {
  const stripped = stripComments(css);
  const rules: Array<{ selector: string; body: string }> = [];
  const blocks = stripped.split("}");
  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed.includes("{")) continue;
    const [selectorPart, body] = trimmed.split("{");
    if (!body || !body.includes("var(--accent-2)")) continue;
    // Skip @media wrapper headers; the real selector is on the inner
    // rule which gets its own pass.
    if (selectorPart.trim().startsWith("@")) continue;
    rules.push({ selector: selectorPart.trim(), body: body.trim() });
  }
  return rules;
}

describe("--accent-2 semantic guard", () => {
  const css = readFileSync(CSS_PATH, "utf8");
  const accent2Rules = extractAccent2Rules(css);

  it("finds at least one rule referencing --accent-2 (sanity check)", () => {
    // If this fails, either the parser broke or someone removed all
    // accent-2 uses — both worth investigating.
    expect(accent2Rules.length).toBeGreaterThan(0);
  });

  it("every rule referencing --accent-2 has a save/error semantic in its selector", () => {
    const violators = accent2Rules.filter((r) => !looksSemantic(r.selector) && !isException(r.selector));
    if (violators.length > 0) {
      const lines = violators
        .map((r) => `  - "${r.selector}" → uses var(--accent-2) but selector lacks any of: ${SEMANTIC_WORDS.join(", ")}`)
        .join("\n");
      throw new Error(
        `--accent-2 (heart red) used on non-save/non-error selectors:\n${lines}\n\n` +
        `Fix options:\n` +
        `  1. Use a different brand token (--accent for brand green, --moss, --gold, --badge-* etc.)\n` +
        `  2. If the selector legitimately represents a save/error semantic, rename it to include one of: ${SEMANTIC_WORDS.join(", ")}\n` +
        `  3. If you have a justified exception, add the selector to SELECTOR_EXCEPTIONS in ${CSS_PATH.replace(/.*pulpo\.club[^/]*/, "")}.test.ts with a one-line why.`,
      );
    }
  });
});
