// Pure bucket math for the range histograms (price + size). Extracted from
// the old PriceHistogram so both dimensions share one implementation and the
// arithmetic is unit-testable without mounting React.
//
// A histogram spans [0, visualMax] split into `bucketCount` equal buckets.
// The rightmost bucket doubles as the "no upper cap" affordance: dragging /
// keying the max thumb to the last bucket means `max = null` (unbounded), so
// listings past visualMax stay in scope — same semantics for price ($1M cap)
// and size (2 ha cap).

export type BucketCounts = number[];

// Value at the left edge of `bucket` (0-based).
export function bucketToValue(bucket: number, visualMax: number, bucketCount: number): number {
  return Math.round((bucket * visualMax) / bucketCount);
}

// Nearest bucket index for a value, clamped to [0, bucketCount]. Note the
// upper clamp is bucketCount (not bucketCount-1): the thumb can sit on the
// right edge, which callers read as "no cap".
export function valueToBucket(value: number | null | undefined, visualMax: number, bucketCount: number): number {
  if (value == null || value <= 0) return 0;
  return Math.min(bucketCount, Math.max(0, Math.round((value / visualMax) * bucketCount)));
}

// Count how many rows fall in each bucket. `getValue` extracts the numeric
// dimension (price or size) from a row; non-numeric / non-positive values are
// skipped (matches the pre-refactor price behavior exactly). Values at or past
// visualMax land in the last bucket.
export function computeBucketCounts<T>(
  rows: readonly T[],
  getValue: (row: T) => number | null | undefined,
  visualMax: number,
  bucketCount: number,
): BucketCounts {
  const arr = new Array<number>(bucketCount).fill(0);
  for (const row of rows) {
    const v = getValue(row);
    if (typeof v !== "number" || v <= 0) continue;
    const b = Math.min(bucketCount - 1, Math.floor((v / visualMax) * bucketCount));
    arr[b] += 1;
  }
  return arr;
}
