import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const widget = fs.readFileSync(
  path.join(root, "web/app/admin/widgets/newsletter/NewsletterWidget.jsx"),
  "utf8",
);
const endpoint = fs.readFileSync(
  path.join(root, "api/admin/newsletter/trigger-preview.js"),
  "utf8",
);
const workflow = fs.readFileSync(
  path.join(root, ".github/workflows/pulpo-newsletter.yml"),
  "utf8",
);
const freeWorkflow = fs.readFileSync(
  path.join(root, ".github/workflows/pulpo-newsletter-free.yml"),
  "utf8",
);
const subscribers = fs.readFileSync(
  path.join(root, "automation/newsletter/subscribers.py"),
  "utf8",
);

describe("admin newsletter widget ↔ production contract", () => {
  it("shows the production cron instead of a stale weekday/time", () => {
    expect(workflow).toContain('cron: "0 16 * * 0"');
    expect(widget).toContain('trigger: "Sundays 16:00 UTC · cron"');
    expect(freeWorkflow).toContain('cron: "0 17 * * 0"');
    expect(widget).toContain('trigger: "Sundays 17:00 UTC · staged cron"');
    expect(widget).not.toContain('trigger: "Mondays 14:00 UTC · cron"');
  });

  it("truthfully reports that a weekly preview sends one recipient", () => {
    expect(endpoint).toContain("sends one real");
    expect(subscribers).toContain("ONE fake recipient");
    expect(widget).toContain("1 preview email");
    expect(widget).not.toContain("3 cohort previews");
  });

  it("keeps the displayed preview limit aligned with the endpoint", () => {
    expect(endpoint).toMatch(/maxAttempts:\s*5/);
    expect(widget).toContain("limit reached (5 per hour)");
  });
});
