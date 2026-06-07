"""Per-source dedup audit — emits web/data/dedup_audit.json each nightly.

Read-only telemetry. PRD acceptance criterion: "Dedup rate documented
per new source." The audit groups every visible listing by the stable
content fingerprint from ``pulpo.scrapers.lib.dedup_hasher`` and reports:

- per-source totals: raw, kept-unique, dropped-as-dupe-of-other-source
- a symmetric N×N overlap matrix: ``{source_a: {source_b: count}}``
  where ``count`` is the number of fingerprints shared between the two
  sources

The audit runs AFTER ``automation/run.py``'s existing
``duplicate_detection`` step (which uses phone + coord pair matching).
This module's content-fingerprint pass is complementary — it catches
the cross-broker "same property, different agent" case that pair
matching misses, and surfaces the result as a per-source matrix the
operator can read at a glance.

Schema::

    {
      "computed_at": "<ISO>",
      "total_in_dataset": 962,
      "total_unique_fingerprints": 941,
      "per_source": {
        "<slug>": {
          "raw": <int>,                # listings from this source
          "unique_in_source": <int>,   # distinct fingerprints from this source
          "kept_as_unique": <int>,     # fingerprints unique to this source
          "shared_with_others": <int>  # fingerprints also seen at another source
        },
        ...
      },
      "overlap_matrix": {
        "<source_a>": {"<source_b>": <count>, ...},
        ...
      }
    }

The overlap matrix is symmetric: ``matrix[a][b] == matrix[b][a]``.
Self-pairs are excluded.

Listings without a ``source`` field are bucketed under ``"_unknown"``
so the audit never silently drops rows.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from automation.country_sidecars import write_json_sidecar
from pulpo.scrapers.lib.dedup_hasher import listing_fingerprint


def _source_of(li: Any) -> str:
    if isinstance(li, dict):
        v = li.get("source")
    else:
        v = getattr(li, "source", None)
    return v if isinstance(v, str) and v else "_unknown"


def compute_audit(listings: Iterable[Any]) -> dict[str, Any]:
    """Pure compute — no I/O. Mirrors the JSON shape ``write_audit`` writes."""
    fingerprints_by_source: dict[str, list[str]] = defaultdict(list)
    source_per_fp: dict[str, set[str]] = defaultdict(set)
    total = 0

    for li in listings:
        total += 1
        fp = listing_fingerprint(li)
        src = _source_of(li)
        fingerprints_by_source[src].append(fp)
        source_per_fp[fp].add(src)

    per_source: dict[str, dict[str, int]] = {}
    for source, fps in fingerprints_by_source.items():
        unique_fps = set(fps)
        kept_as_unique = sum(
            1 for fp in unique_fps if source_per_fp[fp] == {source}
        )
        shared = len(unique_fps) - kept_as_unique
        per_source[source] = {
            "raw": len(fps),
            "unique_in_source": len(unique_fps),
            "kept_as_unique": kept_as_unique,
            "shared_with_others": shared,
        }

    # Symmetric overlap matrix. For each fingerprint seen at >1 source,
    # increment matrix[a][b] AND matrix[b][a] by 1 for every unordered
    # pair {a, b} in the source set.
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for fp, srcs in source_per_fp.items():
        if len(srcs) < 2:
            continue
        srcs_list = sorted(srcs)
        for i, a in enumerate(srcs_list):
            for b in srcs_list[i + 1:]:
                matrix[a][b] += 1
                matrix[b][a] += 1

    # Normalize the defaultdict-of-defaultdict to plain dicts + sorted
    # keys for stable JSON output.
    overlap_matrix: dict[str, dict[str, int]] = {
        a: {b: matrix[a][b] for b in sorted(matrix[a].keys())}
        for a in sorted(matrix.keys())
    }

    return {
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_in_dataset": total,
        "total_unique_fingerprints": len(source_per_fp),
        "per_source": {k: per_source[k] for k in sorted(per_source.keys())},
        "overlap_matrix": overlap_matrix,
    }


def write_audit(
    listings: Iterable[Any],
    web_data_dir: Path,
) -> dict[str, Any]:
    """Compute audit + write to ``<web_data_dir>/dedup_audit.json``.

    Returns the audit dict so callers can log a one-line summary.
    """
    audit = compute_audit(listings)
    out_path = Path(web_data_dir) / "dedup_audit.json"
    write_json_sidecar(out_path, audit)
    return audit
