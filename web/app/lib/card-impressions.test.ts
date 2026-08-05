// Unit tests for the card-impression batching module. We drive a fake
// IntersectionObserver so we control exactly when a card "enters the
// viewport", and fake timers so the debounce flush is deterministic.
//
// The event `browse.card_impression` is asserted via the telemetry test
// hook: track() pushes into window.__pulpoEvents__ when test mode is on.
// Here we mock the hook module directly so no PostHog SDK is involved.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const captured: Array<{ name: string; props: Record<string, unknown> }> = [];
vi.mock("../telemetry/hook", () => ({
  track: (name: string, props: Record<string, unknown>) => captured.push({ name, props }),
}));

// A controllable IntersectionObserver: tests call intersect(el) to
// simulate the element crossing the visibility threshold.
type ObsCb = (entries: Array<{ target: Element; isIntersecting: boolean }>) => void;
class FakeIO {
  cb: ObsCb;
  observed = new Set<Element>();
  static instances: FakeIO[] = [];
  constructor(cb: ObsCb) {
    this.cb = cb;
    FakeIO.instances.push(this);
  }
  observe(el: Element) { this.observed.add(el); }
  unobserve(el: Element) { this.observed.delete(el); }
  disconnect() { this.observed.clear(); }
  intersect(el: Element) { this.cb([{ target: el, isIntersecting: true }]); }
}

function fakeEl(id: string): Element {
  return { __id: id } as unknown as Element;
}

let mod: typeof import("./card-impressions");

beforeEach(async () => {
  captured.length = 0;
  FakeIO.instances = [];
  vi.stubGlobal("IntersectionObserver", FakeIO as never);
  vi.stubGlobal("document", { addEventListener: () => {}, visibilityState: "visible" } as never);
  vi.useFakeTimers();
  vi.resetModules();
  mod = await import("./card-impressions");
  mod.__resetForTest();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function theObserver(): FakeIO {
  // ensureObserver() lazily constructs one on the first observeCard().
  return FakeIO.instances[FakeIO.instances.length - 1];
}

describe("observeCard + batching", () => {
  it("fires one batched event with parallel id/position arrays after the debounce", () => {
    const a = fakeEl("a");
    const b = fakeEl("b");
    mod.observeCard(a, { listingId: "l1", position: 0, surface: "browse", sort: "rank" });
    mod.observeCard(b, { listingId: "l2", position: 1, surface: "browse", sort: "rank" });
    const io = theObserver();
    io.intersect(a);
    io.intersect(b);
    expect(captured).toHaveLength(0); // still buffered
    vi.advanceTimersByTime(1000);
    expect(captured).toHaveLength(1);
    expect(captured[0].name).toBe("browse.card_impression");
    expect(captured[0].props).toMatchObject({
      listing_ids: ["l1", "l2"],
      positions: [0, 1],
      surface: "browse",
      sort: "rank",
    });
  });

  it("dedupes: the same listing only counts once until reset", () => {
    const a = fakeEl("a");
    mod.observeCard(a, { listingId: "l1", position: 0, surface: "browse", sort: "rank" });
    const io = theObserver();
    io.intersect(a);
    io.intersect(a); // re-enter — must not double count
    vi.advanceTimersByTime(1000);
    expect(captured).toHaveLength(1);
    expect(captured[0].props.listing_ids).toEqual(["l1"]);
  });

  it("eager-flushes at the batch size without waiting for the debounce", () => {
    const io0 = (() => {
      mod.observeCard(fakeEl("seed"), { listingId: "seed", position: 0, surface: "browse", sort: "rank" });
      return theObserver();
    })();
    // 10 distinct impressions should trigger an immediate flush (batch=10).
    for (let i = 0; i < 10; i++) {
      const el = fakeEl(`e${i}`);
      mod.observeCard(el, { listingId: `L${i}`, position: i, surface: "browse", sort: "rank" });
      io0.intersect(el);
    }
    // No timer advance — the 10th impression flushed synchronously.
    expect(captured).toHaveLength(1);
    expect(captured[0].props.listing_ids).toHaveLength(10);
  });

  it("resetImpressions flushes pending and lets a listing count again", () => {
    const a = fakeEl("a");
    mod.observeCard(a, { listingId: "l1", position: 0, surface: "browse", sort: "rank" });
    const io = theObserver();
    io.intersect(a);
    // reset flushes the buffered impression immediately...
    mod.resetImpressions("browse");
    expect(captured).toHaveLength(1);
    // ...and clears dedupe, so the same listing re-entering counts anew.
    const a2 = fakeEl("a2");
    mod.observeCard(a2, { listingId: "l1", position: 3, surface: "browse", sort: "price_asc" });
    theObserver().intersect(a2);
    vi.advanceTimersByTime(1000);
    expect(captured).toHaveLength(2);
    expect(captured[1].props).toMatchObject({ listing_ids: ["l1"], positions: [3], sort: "price_asc" });
  });

  it("keeps surfaces in separate batches", () => {
    const a = fakeEl("a");
    const b = fakeEl("b");
    mod.observeCard(a, { listingId: "l1", position: 0, surface: "browse", sort: "rank" });
    mod.observeCard(b, { listingId: "l2", position: 0, surface: "saved", sort: "recent" });
    const io = theObserver();
    io.intersect(a);
    io.intersect(b);
    vi.advanceTimersByTime(1000);
    expect(captured).toHaveLength(2);
    const surfaces = captured.map((e) => e.props.surface).sort();
    expect(surfaces).toEqual(["browse", "saved"]);
  });

  it("is a no-op when IntersectionObserver is unavailable", async () => {
    vi.stubGlobal("IntersectionObserver", undefined as never);
    vi.resetModules();
    const fresh = await import("./card-impressions");
    fresh.__resetForTest();
    const cleanup = fresh.observeCard(fakeEl("x"), {
      listingId: "l1", position: 0, surface: "browse", sort: "rank",
    });
    expect(typeof cleanup).toBe("function");
    vi.advanceTimersByTime(2000);
    expect(captured).toHaveLength(0);
  });
});
