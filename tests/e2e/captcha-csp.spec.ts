import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

const CLERK_CAPTCHA_RE = /Clerk:.*Failed to load the CAPTCHA|Failed to load the CAPTCHA script/i;
const CSP_VIOLATION_RE = /violates the following Content Security Policy directive/i;

// NOTE: not @critical yet. Promoting this to the CI gate is a plan-006
// item — it currently fails on 3 pre-existing activation-landing 404s
// (unrelated to its CAPTCHA/CSP purpose, which both pass). Triage those
// 404s + tolerate or fix them before tagging @critical, per the plan-006
// "de-flake before promoting" rule.
test.describe("Clerk CAPTCHA CSP guard", () => {
  test("activation landing does not emit Clerk CAPTCHA or CSP console failures", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    const errors = attachErrorRecorder(page);
    const captchaFailures: string[] = [];
    const cspFailures: string[] = [];

    page.on("console", (msg) => {
      const text = msg.text();
      if (CLERK_CAPTCHA_RE.test(text)) captchaFailures.push(text);
      if (CSP_VIOLATION_RE.test(text)) cspFailures.push(text);
    });

    await page.goto(
      "/account?__clerk_status=sign_up&__clerk_ticket=dummy_csp_guard",
      { waitUntil: "domcontentloaded" },
    );
    await page.waitForTimeout(5000);

    expect(captchaFailures, "Clerk Turnstile CAPTCHA failed to load").toEqual([]);
    expect(cspFailures, "browser reported CSP violations on activation landing").toEqual([]);
    expect(errors, "unexpected console/page errors on activation landing").toEqual([]);
  });
});
