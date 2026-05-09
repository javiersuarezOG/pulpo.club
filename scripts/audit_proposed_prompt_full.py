"""
Full-scope test: how many of today's 189 description/distance
inconsistencies does the proposed prompt resolve?

For each listing flagged by scripts/audit_beach_distance_consistency.py,
calls DeepSeek with the production SYSTEM_PROMPT (post-edit), recomputes
dist_beach_km from the returned lat/lng, and reports how many drop
below 2 km (i.e. their description claim becomes consistent with the
distance).

Read-only — does NOT touch the production sidecar/ranked.json.

Run:
    python3 scripts/audit_proposed_prompt_full.py            # all 189
    python3 scripts/audit_proposed_prompt_full.py 30         # limit to 30
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Load .env if env var isn't set yet
if not os.environ.get("DEEPSEEK_API_TOKEN"):
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from automation.distance_fields import compute_dist_beach_km  # type: ignore
from automation.llm_enrichment_prompts import SYSTEM_PROMPT, render_user_prompt  # type: ignore
from scripts.audit_beach_distance_consistency import audit  # type: ignore


def _call(client, user_prompt: str) -> dict | None:
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
        print(f"    !! call failed: {e!r}")
        return None


def main() -> None:
    if not os.environ.get("DEEPSEEK_API_TOKEN"):
        print("ERROR: DEEPSEEK_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("pip install openai", file=sys.stderr)
        sys.exit(1)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    listings = json.loads((REPO / "web" / "data" / "ranked.json").read_text())
    by_key = {(li["source"], li["source_id"]): li for li in listings}
    flagged = audit(listings)
    if limit:
        flagged = flagged[:limit]

    print(f"Auditing {len(flagged)} flagged listings against the proposed prompt...")
    print()

    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=os.environ["DEEPSEEK_API_TOKEN"],
    )

    results = []
    counts = {"resolved": 0, "still_far": 0, "worse": 0, "failed": 0}
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
        old_dist = f["dist_beach_km"]
        parsed = _call(client, user_prompt)
        if not parsed or not isinstance(parsed.get("latlong"), dict):
            counts["failed"] += 1
            continue
        ll = parsed["latlong"]
        new_dist = compute_dist_beach_km({"lat": ll.get("lat"), "lng": ll.get("lng")})
        if new_dist is None:
            counts["failed"] += 1
            continue
        if new_dist <= 2.0:
            counts["resolved"] += 1
            verdict = "RESOLVED"
        elif new_dist < old_dist - 1:
            counts["still_far"] += 1
            verdict = "improved-not-resolved"
        elif new_dist > old_dist + 1:
            counts["worse"] += 1
            verdict = "REGRESSED"
        else:
            counts["still_far"] += 1
            verdict = "unchanged"

        results.append({
            "src":      f["source"],
            "id":       f["source_id"],
            "title":    f["title"],
            "claim":    f["claim_snippet"],
            "old_dist": old_dist,
            "new_dist": new_dist,
            "old_latlng": (f["lat"], f["lng"]),
            "new_latlng": (ll.get("lat"), ll.get("lng")),
            "new_conf":   ll.get("confidence"),
            "verdict":  verdict,
        })

        # Progress
        if i % 10 == 0 or i == len(flagged):
            elapsed = time.monotonic() - t0
            rate = i / max(elapsed, 0.1)
            eta = (len(flagged) - i) / max(rate, 0.01)
            print(
                f"  [{i:3d}/{len(flagged)}] "
                f"resolved={counts['resolved']} improved={counts['still_far']} "
                f"regressed={counts['worse']} failed={counts['failed']}  "
                f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)"
            )

    print()
    print("=" * 80)
    total_attempted = sum(counts.values())
    print(f"Total attempted: {total_attempted}")
    print(f"  RESOLVED (new_dist ≤ 2km):     {counts['resolved']}  "
          f"({100*counts['resolved']/max(total_attempted,1):.0f}%)")
    print(f"  Improved but still > 2km:      {counts['still_far']}")
    print(f"  REGRESSED (new_dist > old):    {counts['worse']}")
    print(f"  API failures:                  {counts['failed']}")
    print("=" * 80)

    # Save raw rows
    out = REPO / "scripts" / "_prompt_proximity_cues_full_results.json"
    out.write_text(json.dumps({"counts": counts, "results": results},
                              indent=2, ensure_ascii=False))
    print(f"raw → {out}")

    # Show any regressions
    regressed = [r for r in results if r["verdict"] == "REGRESSED"]
    if regressed:
        print(f"\nRegressions ({len(regressed)}):")
        for r in regressed[:15]:
            print(f"  {r['src']}/{r['id']}: {r['old_dist']}km → {r['new_dist']}km")
            print(f"    title: {r['title']}")
            print(f"    claim: {r['claim']!r}")
            print(f"    new_latlng: {r['new_latlng']} ({r['new_conf']})")


if __name__ == "__main__":
    main()
