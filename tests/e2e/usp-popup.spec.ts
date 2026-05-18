// Wave-5 USP popup — end-to-end smoke.
//
// Coverage:
//   * Flag off: legacy USPBand renders inline, no popup.
//   * Flag on + ?upsell=1: popup fires synchronously with trigger=url_param.
//   * Flag on + scroll past 50%: popup fires with trigger=scroll.
//   * Flag on + paid user: popup never arms, no DOM, no events.
//   * Dismiss stamps the 7-day cap; second visit within 7d → no popup.
//   * CTA routes through Wave-1's utility (anon → /start, intercepted).
//
// Timer + exit-intent triggers are validated in unit tests
// (lib/usp-popup-trigger.test.ts); driving real-time + mouse-out events
// in Playwright adds flake without proportional coverage.

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, seedUser, seedProUser } from "./_helpers";

type CapturedEvent = { name: string; props: Record<string, unknown>; ts: number };

async function getEvents(page: Page): Promise<CapturedEvent[]> {
  return page.evaluate(() => {
    const w = window as unknown as { __pulpoEvents__?: CapturedEvent[] };
    return Array.isArray(w.__pulpoEvents__) ? [...w.__pulpoEvents__] : [];
  });
}

test.describe("USP popup (Wave 5) — flag off (rollback path)", () => {
  test("USPBand renders inline; no popup", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=0",
      { waitUntil: "networkidle" },
    );

    await expect(page.locator(".hp-usp")).toBeVisible();
    await expect(page.locator(".usp-popup-modal")).toHaveCount(0);

    const events = await getEvents(page);
    expect(events.find((e) => e.name === "usp_popup.shown")).toBeUndefined();

    expect(errors).toEqual([]);
  });
});

test.describe("USP popup (Wave 5) — flag on", () => {
  test("?upsell=1 fires the popup with trigger=url_param", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=1&upsell=1",
      { waitUntil: "networkidle" },
    );

    // USPBand absent (migrated into popup); popup visible.
    await expect(page.locator(".hp-usp")).toHaveCount(0);
    await expect(page.locator(".usp-popup-modal")).toBeVisible();

    // Event fires with the right trigger.
    const ev = (await getEvents(page)).find((e) => e.name === "usp_popup.shown");
    expect(ev, "usp_popup.shown should fire").toBeTruthy();
    expect(ev!.props.trigger).toBe("url_param");
    expect(ev!.props.user_state).toBe("anonymous");

    expect(errors).toEqual([]);
  });

  test("scroll past 50% fires the popup with trigger=scroll", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=1",
      { waitUntil: "networkidle" },
    );

    // No popup at rest.
    await expect(page.locator(".usp-popup-modal")).toHaveCount(0);

    // Scroll past 50%.
    await page.evaluate(() => {
      const scrollable = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      window.scrollTo(0, scrollable * 0.55);
    });

    await expect(page.locator(".usp-popup-modal")).toBeVisible({ timeout: 3_000 });
    const ev = (await getEvents(page)).find((e) => e.name === "usp_popup.shown");
    expect(ev).toBeTruthy();
    expect(ev!.props.trigger).toBe("scroll");

    expect(errors).toEqual([]);
  });

  test("paid users never see the popup, even with ?upsell=1", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=1&upsell=1",
      { waitUntil: "networkidle" },
    );

    await expect(page.locator(".usp-popup-modal")).toHaveCount(0);
    const events = await getEvents(page);
    expect(events.find((e) => e.name === "usp_popup.shown")).toBeUndefined();

    expect(errors).toEqual([]);
  });
});

test.describe("USP popup (Wave 5) — dismiss + suppression", () => {
  test("Maybe-later stamps the 7-day cap; second visit shows nothing", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");

    // First visit: popup fires via ?upsell=1.
    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=1&upsell=1",
      { waitUntil: "networkidle" },
    );
    await expect(page.locator(".usp-popup-modal")).toBeVisible();

    // Dismiss via Maybe-later button. Scope to inside the popup to
    // avoid matching the hero's own "Try a free month / Maybe later"
    // CTAs; force-click sidesteps the animated-leaderboard actionability
    // flake under the modal.
    await page.locator(".usp-popup-modal").getByRole("button", { name: /Maybe later/i }).click({ force: true });
    await expect(page.locator(".usp-popup-modal")).toHaveCount(0);

    const events = await getEvents(page);
    const dismissEv = events.find((e) => e.name === "usp_popup.dismissed");
    expect(dismissEv).toBeTruthy();
    expect(dismissEv!.props.action).toBe("maybe_later");

    // localStorage stamped.
    const stamp = await page.evaluate(() => localStorage.getItem("pulpo-usp-popup-dismissed-at"));
    expect(stamp).toMatch(/^\d+$/);

    // Second visit (same session, same ?upsell=1) — suppression wins.
    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=1&upsell=1",
      { waitUntil: "networkidle" },
    );
    await expect(page.locator(".usp-popup-modal")).toHaveCount(0);
    const events2 = await getEvents(page);
    expect(events2.find((e) => e.name === "usp_popup.shown")).toBeUndefined();

    expect(errors).toEqual([]);
  });
});

test.describe("USP popup (Wave 5) — CTA wiring", () => {
  test("anon CTA click → opens FreeMonthModal (post-#262 routing)", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_usp_popup_v1=1&upsell=1&ff_cta_routing_v2=1",
      { waitUntil: "networkidle" },
    );

    // Verify the popup CTA is reachable before clicking. Target by
    // the popup-specific CSS class to avoid the hero's "Try a free
    // month" CTA which sits behind the backdrop.
    const popupCta = page.locator(".usp-popup-modal .btn-primary");
    await expect(popupCta).toBeVisible();
    // dispatchEvent fires a synthetic click event directly on the
    // element — bypasses Playwright's coordinate-based hit testing
    // entirely. React listens on the bubble; this triggers onClick.
    await popupCta.dispatchEvent("click");

    // Click reached the handler — assert telemetry first so a failure
    // here narrows the diagnosis (handler missed vs. dispatch missed).
    await expect.poll(async () => {
      const list = await getEvents(page);
      return list.find((e) => e.name === "usp_popup.cta_clicked") ? true : false;
    }, { timeout: 3_000, message: "usp_popup.cta_clicked should fire" }).toBe(true);

    // Post-#262: UspPopup CTA dispatches to free_month_modal which
    // opens FreeMonthModal in-page. UspPopup also unmounts (its
    // onClose fires after dispatch).
    await expect(page.locator(".free-month-modal")).toBeVisible({ timeout: 3_000 });

    const events = await getEvents(page);
    const routed = events.find((e) => e.name === "cta_routed" && e.props.cta_id === "header_primary");
    expect(routed).toBeTruthy();
    expect(routed!.props.branch).toBe("free_month_modal");
    expect(
      events.find((e) => e.name === "free_month_modal.shown" && e.props.trigger === "usp_section"),
    ).toBeTruthy();

    expect(errors).toEqual([]);
  });
});
