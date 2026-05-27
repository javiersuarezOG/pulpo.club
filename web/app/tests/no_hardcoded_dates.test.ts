import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const REPO_ROOT = path.resolve(__dirname, "../../..");

const DATE_LITERAL_RE = /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic)\s+\d{1,2},?\s*\d{4}\b/;

function walk(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

function targetFiles(): string[] {
  const root = path.join(REPO_ROOT, "web/app");
  const files = [
    path.join(root, "account.jsx"),
    ...walk(path.join(root, "lib")).filter((f) => /\/subscription[^/]*\.(ts|tsx|js|jsx)$/.test(f)),
    ...walk(root).filter((f) => /-section\.(jsx|tsx)$/.test(f)),
  ];
  return Array.from(new Set(files)).filter((f) => fs.existsSync(f));
}

function codeLinesOnly(source: string): string[] {
  const lines = source.split(/\r?\n/);
  let inBlockComment = false;
  return lines.map((line) => {
    let rest = line;
    let cleaned = "";
    while (rest.length > 0) {
      if (inBlockComment) {
        const end = rest.indexOf("*/");
        if (end === -1) return "";
        rest = rest.slice(end + 2);
        inBlockComment = false;
        continue;
      }
      const block = rest.indexOf("/*");
      const single = rest.indexOf("//");
      if (single !== -1 && (block === -1 || single < block)) {
        cleaned += rest.slice(0, single);
        return cleaned;
      }
      if (block === -1) {
        cleaned += rest;
        return cleaned;
      }
      cleaned += rest.slice(0, block);
      rest = rest.slice(block + 2);
      inBlockComment = true;
    }
    return cleaned;
  });
}

describe("no hardcoded display dates in account subscription UI", () => {
  it("does not include literal localized date strings", () => {
    const offenders: string[] = [];
    for (const file of targetFiles()) {
      const rel = path.relative(REPO_ROOT, file);
      const lines = codeLinesOnly(fs.readFileSync(file, "utf8"));
      lines.forEach((line, idx) => {
        if (!DATE_LITERAL_RE.test(line)) return;
        const prev = lines[idx - 1] || "";
        const next = lines[idx + 1] || "";
        const adjacent = `${prev}\n${line}\n${next}`;
        if (/date-literal-allowed:\s+\S/.test(adjacent)) return;
        offenders.push(`${rel}:${idx + 1}: ${line.trim()}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
