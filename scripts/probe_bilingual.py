"""One-shot probe: run the new bilingual + LOCATION HINTS prompt against 5
random listings from web/data/ranked.json and report the parsed result.

Run: DEEPSEEK_API_TOKEN=... python scripts/probe_bilingual.py
"""
from __future__ import annotations
import json
import os
import random
import sys
import textwrap
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.llm_enrichment_prompts import SYSTEM_PROMPT, render_user_prompt  # noqa: E402
from automation.llm_enrichment_schema import DEFAULT_SCHEMA, validate_response  # noqa: E402

import openai  # noqa: E402


def _load_token() -> str:
    tok = os.environ.get("DEEPSEEK_API_TOKEN")
    if not tok:
        env_path = REPO / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DEEPSEEK_API_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not tok:
        sys.exit("DEEPSEEK_API_TOKEN missing — set in env or .env")
    return tok


def _pick_random_listings(n: int = 5, seed: int = 7) -> list[dict]:
    data = json.loads((REPO / "web/data/ranked.json").read_text())
    rng = random.Random(seed)
    # Diverse pick: stratify across sources where possible
    by_src: dict[str, list[dict]] = {}
    for li in data:
        by_src.setdefault(li.get("source", "?"), []).append(li)
    picks: list[dict] = []
    for src in ["goodlife", "oceanside", "century21", "bienesraices", "remax", "nexo"]:
        if by_src.get(src):
            picks.append(rng.choice(by_src[src]))
        if len(picks) >= n:
            break
    return picks[:n]


def _wrap(s: str, width: int = 90) -> str:
    return "\n".join(textwrap.wrap(s, width=width)) if s else ""


def main() -> int:
    token = _load_token()
    listings = _pick_random_listings(5)
    client = openai.OpenAI(
        api_key=token,
        base_url=DEFAULT_SCHEMA.base_url,
    )

    total_in = total_out = 0
    total_cost = 0.0
    t_start = time.monotonic()

    print(f"\n[probe] schema_version={DEFAULT_SCHEMA.schema_version} "
          f"model={DEFAULT_SCHEMA.model} max_tokens={DEFAULT_SCHEMA.max_tokens}\n")

    for idx, li in enumerate(listings, 1):
        key = f"{li.get('source')}|{li.get('source_id')}"
        user = render_user_prompt(
            li.get("description"),
            location_text=li.get("location_text"),
            municipality=li.get("municipality"),
            department=li.get("department"),
            country=li.get("country"),
        )
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=DEFAULT_SCHEMA.model,
            max_tokens=DEFAULT_SCHEMA.max_tokens,
            temperature=DEFAULT_SCHEMA.temperature,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user},
            ],
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        choice = resp.choices[0]
        finish = getattr(choice, "finish_reason", None)
        usage = getattr(resp, "usage", None)
        ti = getattr(usage, "prompt_tokens", 0) or 0
        to = getattr(usage, "completion_tokens", 0) or 0
        total_in += ti
        total_out += to
        # DeepSeek-chat pricing: $0.27 / 1M input, $1.10 / 1M output (cache miss)
        cost = (ti * 0.27 + to * 1.10) / 1_000_000
        total_cost += cost

        print("=" * 100)
        print(f"#{idx} {key}  zone={li.get('zone')!r}  "
              f"municipality={li.get('municipality')!r}  "
              f"department={li.get('department')!r}")
        print(f"     SOURCE TITLE: {li.get('title') or '—'}")
        print(f"     SOURCE DESC:  {_wrap(li.get('description') or '—')[:300]}{'…' if len(li.get('description') or '') > 300 else ''}")
        print(f"     [latency={latency_ms}ms tokens={ti}/{to} cost=${cost:.4f} finish={finish}]")
        raw = choice.message.content or "{}"
        try:
            parsed = json.loads(raw)
        except Exception as e:
            print(f"     ERROR parsing JSON: {e!r}")
            print(f"     RAW: {raw[:400]!r}")
            continue
        ok, reason = validate_response(parsed, DEFAULT_SCHEMA)
        print(f"     SCHEMA VALID: {ok}{(' (' + reason + ')') if reason else ''}")
        print()
        # Title
        t = parsed.get("title", {})
        print(f"     title.en: {t.get('en','—')}")
        print(f"     title.es: {t.get('es','—')}")
        print()
        # Description (truncated)
        d = parsed.get("description", {})
        print(f"     desc.en:  {_wrap(d.get('en',''), 90)}")
        print()
        print(f"     desc.es:  {_wrap(d.get('es',''), 90)}")
        print()
        # USPs
        usps = parsed.get("usps", []) or []
        for j, u in enumerate(usps, 1):
            print(f"     usp{j}.en: {u.get('en','—')}")
            print(f"     usp{j}.es: {u.get('es','—')}")
        print()
        # Meta
        print(f"     url_language: {parsed.get('url_language')}")
        ll = parsed.get("latlong") or {}
        print(f"     latlong:      lat={ll.get('lat')} lng={ll.get('lng')} "
              f"src={ll.get('source')} conf={ll.get('confidence')} "
              f"ref={ll.get('reference')!r}")
        print()

    elapsed = time.monotonic() - t_start
    print("=" * 100)
    print(f"\n[probe summary] {len(listings)} listings, {elapsed:.1f}s wall-clock")
    print(f"  tokens in/out:  {total_in} / {total_out}")
    print(f"  total cost:     ${total_cost:.4f}")
    print(f"  per-listing:    ${total_cost/len(listings):.4f} avg")
    print(f"  scaled to 873:  ${total_cost*873/len(listings):.2f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
