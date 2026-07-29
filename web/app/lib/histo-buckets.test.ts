import { describe, expect, it } from "vitest";
import { bucketToValue, valueToBucket, computeBucketCounts } from "./histo-buckets";

const PRICE_MAX = 1_000_000;
const SIZE_MAX = 20_000;
const N = 24;

describe("bucketToValue", () => {
  it("maps bucket index to its left-edge value (price scale)", () => {
    expect(bucketToValue(0, PRICE_MAX, N)).toBe(0);
    expect(bucketToValue(N, PRICE_MAX, N)).toBe(PRICE_MAX);
    expect(bucketToValue(12, PRICE_MAX, N)).toBe(500_000);
  });
  it("works for the size scale too", () => {
    expect(bucketToValue(0, SIZE_MAX, N)).toBe(0);
    expect(bucketToValue(N, SIZE_MAX, N)).toBe(SIZE_MAX);
    expect(bucketToValue(12, SIZE_MAX, N)).toBe(10_000);
  });
});

describe("valueToBucket", () => {
  it("clamps null/zero/negative to bucket 0", () => {
    expect(valueToBucket(null, PRICE_MAX, N)).toBe(0);
    expect(valueToBucket(undefined, PRICE_MAX, N)).toBe(0);
    expect(valueToBucket(0, PRICE_MAX, N)).toBe(0);
    expect(valueToBucket(-5, PRICE_MAX, N)).toBe(0);
  });
  it("allows the right edge (bucket N) so the thumb reads as 'no cap'", () => {
    expect(valueToBucket(PRICE_MAX, PRICE_MAX, N)).toBe(N);
    expect(valueToBucket(PRICE_MAX * 2, PRICE_MAX, N)).toBe(N); // clamped
  });
  it("rounds to nearest bucket", () => {
    expect(valueToBucket(500_000, PRICE_MAX, N)).toBe(12);
  });
});

describe("computeBucketCounts", () => {
  const id = (v: number | null | undefined) => v;

  it("buckets values and skips non-numeric / non-positive (matches pre-refactor price behavior)", () => {
    const rows = [10, 0, -1, null, undefined, NaN, 500_000, 999_999, 1_000_000];
    const counts = computeBucketCounts(rows, id, PRICE_MAX, N);
    expect(counts).toHaveLength(N);
    expect(counts.reduce((a, c) => a + c, 0)).toBe(4); // 10, 500k, 999999, 1M
    expect(counts[0]).toBe(1);   // 10 → bucket 0
    expect(counts[12]).toBe(1);  // 500k → bucket 12
  });

  it("clamps values at or past visualMax into the last bucket", () => {
    const counts = computeBucketCounts([1_000_000, 5_000_000], id, PRICE_MAX, N);
    expect(counts[N - 1]).toBe(2);
  });

  it("works on the size scale with an object extractor", () => {
    const rows = [{ size_m2: 1_000 }, { size_m2: 25_000 }, { size_m2: null }];
    const counts = computeBucketCounts(rows, (r) => r.size_m2, SIZE_MAX, N);
    expect(counts.reduce((a, c) => a + c, 0)).toBe(2); // null skipped
    expect(counts[N - 1]).toBe(1); // 25k > 20k cap → last bucket
  });
});
