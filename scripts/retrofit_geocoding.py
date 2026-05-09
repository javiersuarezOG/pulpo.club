"""
Retrofit lat/lng + recomputed distances for listings whose description
claims walking distance / beachfront but whose stored dist_beach_km is
inconsistent with that claim.

Workflow:
  1. Run audit_beach_distance_consistency.audit() to identify offenders.
  2. For each, call DeepSeek with the current SYSTEM_PROMPT (which
     includes the named-beach reference table).
  3. Update ONLY the geocoding fields (lat, lng, geocoding_source,
     geocoding_confidence, geocoding_reference) in:
       - web/data/ranked.json
       - web/data/llm_enrichment.json (per-listing sidecar so the value
         survives the next nightly run instead of getting clobbered).
  4. Recompute dist_beach_km + dist_airport_km from the new lat/lng.
  5. Save and emit a summary.

Does NOT touch: title_canonical, short_description_canonical,
reasons_to_buy, url_language. Those are already cached and approved —
this is a geocoding-only retrofit.

Usage:
    python3 scripts/retrofit_geocoding.py            # all flagged
    python3 scripts/retrofit_geocoding.py --dry-run  # don't write files
    python3 scripts/retrofit_geocoding.py --limit 20 # cap for testing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Load .env if not already exported
if not os.environ.get("DEEPSEEK_API_TOKEN"):
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from automation.distance_fields import (  # type: ignore
    compute_dist_beach_km, compute_dist_airport_km,
)
from automation.llm_enrichment_prompts import SYSTEM_PROMPT, render_user_prompt  # type: ignore
from scripts.audit_beach_distance_consistency import audit  # type: ignore


RANKED  = REPO / "web" / "data" / "ranked.json"
SIDECAR = REPO / "web" / "data" / "llm_enrichment.json"


def _sidecar_key(li: dict) -> str:
    """Match the convention used by automation/llm_enrichment.py::_key()."""
    return f"{li.get('source')}|{li.get('source_id')}"


def _call_deepseek(client, user_prompt: str) -> dict | None:
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )
        return json.loads((resp.choices[0].message.content or "").strip())
    except Exception as e:
        print(f"    !! deepseek call failed: {e!r}", flush=True)
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="don't write to disk")
    p.add_argument("--limit",   type=int, default=None,
                   help="only retrofit the first N flagged listings")
    args = p.parse_args()

    if not os.environ.get("DEEPSEEK_API_TOKEN"):
        print("ERROR: DEEPSEEK_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("pip install openai", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=os.environ["DEEPSEEK_API_TOKEN"],
    )

    listings: list[dict] = json.loads(RANKED.read_text(encoding="utf-8"))
    sidecar: dict = json.loads(SIDECAR.read_text(encoding="utf-8")) if SIDECAR.exists() else {}
    by_key = {(li["source"], li["source_id"]): li for li in listings}

    flagged = audit(listings)
    if args.limit:
        flagged = flagged[: args.limit]

    print(f"Retrofitting {len(flagged)} listings (dry_run={args.dry_run})...", flush=True)
    print(flush=True)

    counts = {"updated": 0, "no_change": 0, "regressed": 0, "failed": 0}
    t0 = time.monotonic()
    for i, f in enumerate(flagged, 1):
        li = by_key[(f["source"], f["source_id"])]
        user_prompt = render_user_prompt(
            li.get("description"),
            location_text=li.get("location_text"),
            municipality=li.get("municipality"),
            department=li.get("department"),
            country=li.get("country"),
        )
        old_dist = li.get("dist_beach_km")
        parsed = _call_deepseek(client, user_prompt)
        if not parsed or not isinstance(parsed.get("latlong"), dict):
            counts["failed"] += 1
            continue
        ll = parsed["latlong"]
        new_lat = ll.get("lat")
        new_lng = ll.get("lng")
        if not isinstance(new_lat, (int, float)) or not isinstance(new_lng, (int, float)):
            counts["failed"] += 1
            continue

        # Update ranked.json record in place
        li["lat"] = round(float(new_lat), 6)
        li["lng"] = round(float(new_lng), 6)
        li["geocoding_confidence"] = ll.get("confidence")
        li["geocoding_source"]     = ll.get("source")
        ref = ll.get("reference")
        li["geocoding_reference"]  = ref.strip() if isinstance(ref, str) else None

        # Recompute the two distance fields that depend on lat/lng.
        new_dist_beach = compute_dist_beach_km(li)
        new_dist_air, _ = compute_dist_airport_km(li)
        li["dist_beach_km"]   = new_dist_beach
        li["dist_airport_km"] = new_dist_air

        # Mirror the same fields into the sidecar so the next nightly run
        # — which gates re-enrichment on whether the sidecar already
        # carries lat/lng — does NOT overwrite the retrofit. Anything
        # else in the sidecar (title_canonical, reasons_to_buy, etc.)
        # stays untouched.
        sk = _sidecar_key(li)
        if sk in sidecar:
            sidecar[sk]["lat"] = li["lat"]
            sidecar[sk]["lng"] = li["lng"]
            sidecar[sk]["geocoding_confidence"] = li["geocoding_confidence"]
            sidecar[sk]["geocoding_source"]     = li["geocoding_source"]
            sidecar[sk]["geocoding_reference"]  = li["geocoding_reference"]
            sidecar[sk]["retrofit_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # If the sidecar entry is missing, we don't synthesize one — the
        # nightly enrichment will create it next run with the new prompt.

        # Bookkeeping
        if new_dist_beach is None or old_dist is None:
            counts["no_change"] += 1
        elif new_dist_beach <= max(2.0, old_dist - 1):
            counts["updated"] += 1
        elif new_dist_beach > old_dist + 1:
            counts["regressed"] += 1
        else:
            counts["no_change"] += 1

        if i % 10 == 0 or i == len(flagged):
            elapsed = time.monotonic() - t0
            rate = i / max(elapsed, 0.1)
            eta = (len(flagged) - i) / max(rate, 0.01)
            print(f"  [{i:3d}/{len(flagged)}] updated={counts['updated']} "
                  f"no_change={counts['no_change']} regressed={counts['regressed']} "
                  f"failed={counts['failed']}  ({elapsed:.0f}s, ~{eta:.0f}s left)",
                  flush=True)

    print(flush=True)
    print("=" * 80, flush=True)
    print(f"Updated:   {counts['updated']}", flush=True)
    print(f"No-change: {counts['no_change']}", flush=True)
    print(f"Regressed: {counts['regressed']}", flush=True)
    print(f"Failed:    {counts['failed']}", flush=True)
    print("=" * 80, flush=True)

    if args.dry_run:
        print("[dry-run] no files written.", flush=True)
        return

    RANKED.write_text(
        json.dumps(listings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    SIDECAR.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {RANKED.relative_to(REPO)} ({len(listings)} records)", flush=True)
    print(f"wrote {SIDECAR.relative_to(REPO)} ({len(sidecar)} sidecar entries)", flush=True)


if __name__ == "__main__":
    main()
