// Guard: the recurring FREE Sunday send must stay STAGED — its scheduled
// run is dry-run until the operator flips the FREE_NEWSLETTER_LIVE repo
// variable. This test exists so nobody accidentally turns the cron into an
// auto-live mass-send (the highest-stakes outbound path Pulpo has).

import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const WF = path.resolve(__dirname, "../../.github/workflows/pulpo-newsletter-free.yml");
const src = fs.readFileSync(WF, "utf8");

describe("pulpo-newsletter-free.yml — staged free Sunday send", () => {
  it("scheduled runs are DRY-RUN unless FREE_NEWSLETTER_LIVE == 'true'", () => {
    // The recurring go-live switch is the repo variable; without it the
    // cron builds + logs the queue but never calls Resend.
    expect(src).toMatch(/PULPO_NEWSLETTER_DRY_RUN/);
    expect(src).toMatch(/github\.event_name == 'schedule' && vars\.FREE_NEWSLETTER_LIVE == 'true'/);
  });

  it("only goes live via the repo var OR an explicit manual send_mode=yes", () => {
    expect(src).toMatch(/github\.event\.inputs\.send_mode == 'yes'/);
    // The live branch resolves to '0' (dry-run off); everything else '1'.
    expect(src).toMatch(/&& '0' \|\| '1'/);
  });

  it("sends the free edition to the free audience", () => {
    expect(src).toMatch(/--newsletter pulpo-free-general/);
    expect(src).toMatch(/--free-audience/);
  });

  it("has its own concurrency group + Sunday schedule (no collision with Pro)", () => {
    expect(src).toMatch(/group:\s*pulpo-newsletter-free-audience/);
    expect(src).toMatch(/cron:\s*"0 17 \* \* 0"/);
  });
});
