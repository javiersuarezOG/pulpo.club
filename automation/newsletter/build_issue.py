"""Turn (recipient, ranked listings, history) into a fully-populated Issue.

This is the cohort-branching layer. The renderer is dumb — it reads from
Issue and writes HTML. The cohort logic, the paywall calls, and the fallback
preferences all live here so the template stays simple.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import commentary as commentary_mod
from . import i18n
from .segments import apply_preference, select_picks
from .store import excluded_source_ids_for, last_send_at_for
from .types import (
    Chip,
    Cohort,
    Commentary,
    Issue,
    IssuePick,
    Locale,
    Preference,
    Recipient,
    YourPulpoState,
)

ISSUE_DEFAULT_TOP_N = 10
ISSUE_TOP_PICKS_RICH = 3   # picks rendered with a full hero image + callouts (was 2 pre PR-NL-5)
ISSUE_CHIPS_PER_PICK = 4   # max supportive chips alongside the hero / pick
DEFAULT_WINDOW_DAYS = 14

LLM_TOGGLE_ENV = "PULPO_NEWSLETTER_USE_LLM"

# PR-NL-6 default: LLM is ON unless explicitly disabled. Operators
# disable it by setting PULPO_NEWSLETTER_USE_LLM=0 (or "false"/"no").
# The fallback path is the deterministic story / commentary generator,
# so any error (no_token, network, finish_reason=length, etc.) lands
# safely. See `_llm_or_deterministic_story` for the decision tree.
LLM_DEFAULT_ON = True

# Per-listing story cache, scoped to one Python process. The audience
# send loops every recipient through `build_issue` — but for a given
# (source_id, locale) the warm paragraph is identical regardless of
# which recipient is reading it. Without this cache we'd burn ~2,800×
# the DeepSeek tokens that the cap is sized for. The cache is bounded
# by the small universe of listings rendered in one issue (~10-15) so
# it doesn't drift; `reset_story_cache()` is the test-only escape
# hatch when a suite needs to exercise fresh generation."""
_story_cache: dict[tuple[str, str], tuple[str, str]] = {}


def reset_story_cache() -> None:
    """Test-only — flushes the per-process story cache so each test can
    exercise fresh generation in isolation."""
    global _story_cache
    _story_cache = {}

# Per-process cap on LLM commentary calls (PR-7 of the reliability plan,
# audit item #17 — newsletter workflow_dispatch can flip the LLM toggle
# without a cost guard). The dry-run workflow today fires ~5 cohorts;
# the cap is set high enough to leave headroom for early production
# audience growth, but low enough that an accidental loop / repeated
# workflow_dispatch can't run away. Operators with a legitimate
# higher-volume need can override via PULPO_NEWSLETTER_LLM_MAX_COMMENTARIES.
#
# Past the cap, _llm_or_deterministic_commentary silently falls back to
# the deterministic generator (which is the safe path for every other
# LLM failure mode anyway). One stderr line per skip so the operator
# sees the cap was reached.
LLM_COMMENTARY_CAP_ENV = "PULPO_NEWSLETTER_LLM_MAX_COMMENTARIES"
LLM_COMMENTARY_CAP_DEFAULT = 50
_llm_commentary_count = 0       # per-process counter, reset on import


def _llm_commentary_cap() -> int:
    """Read the cap from env, with the centralized PR-2 helper so an
    empty / whitespace value falls back to the default cleanly."""
    from automation._config import env_int
    return env_int(LLM_COMMENTARY_CAP_ENV, LLM_COMMENTARY_CAP_DEFAULT)


def reset_llm_commentary_counter() -> None:
    """Test-only escape hatch — flushes the per-process counter so each
    test can exercise the cap in isolation. Production code should never
    need to call this."""
    global _llm_commentary_count
    _llm_commentary_count = 0


def _telemetry_capture(event: str, props: dict) -> None:
    """Fire a PostHog event if telemetry is wired. Never raises."""
    try:
        from automation import posthog_client  # type: ignore
    except Exception:                              # noqa: BLE001
        return
    try:
        posthog_client.capture(event, props)
    except Exception:                              # noqa: BLE001
        pass


def _llm_or_deterministic_commentary(
    *,
    cohort: str,
    locale: Locale,
    pref: Preference,
    display_name: Optional[str],
    n_scanned: int,
    picks: list[dict],
    skip_pick: Optional[dict],
    recipient_hash: str,
    issue_id: str,
    llm_client_override: Any = None,
) -> Commentary:
    """Decide LLM vs deterministic + fire the matching telemetry event.

    Deterministic is the safe fallback for every error path the LLM module
    can return through `LlmResult.error` (no_token, no_package, bad_json,
    schema_miss, finish_reason_length, exception). Cost is non-zero only
    when the LLM successfully responded — telemetry records the cost either
    way so we can audit any unexpected billing.
    """
    use_llm = os.environ.get(LLM_TOGGLE_ENV, "").strip() in ("1", "true", "yes")
    fallback = commentary_mod.deterministic_commentary(
        cohort=cohort,
        locale=locale,
        pref=pref,
        display_name=display_name,
        n_scanned=n_scanned,
        picks=picks,
        skip_pick=skip_pick,
    )

    # Cost guard — refuse to issue a new LLM call past the per-process
    # cap. Defends against an accidental workflow_dispatch loop or a
    # future cohort-count expansion firing into runaway billing.
    global _llm_commentary_count
    cap = _llm_commentary_cap()
    if use_llm and _llm_commentary_count >= cap and llm_client_override is None:
        import sys as _sys
        print(
            f"[newsletter] LLM commentary cap reached "
            f"({_llm_commentary_count}/{cap}); falling back to deterministic. "
            f"Raise via {LLM_COMMENTARY_CAP_ENV}=N if intentional.",
            file=_sys.stderr,
        )
        _telemetry_capture("newsletter.commentary_generated", {
            "issue_id": issue_id,
            "recipient_hash": recipient_hash,
            "cohort": cohort,
            "locale": locale,
            "source": "deterministic_cap_reached",
        })
        return fallback

    if not use_llm and llm_client_override is None:
        _telemetry_capture("newsletter.commentary_generated", {
            "issue_id": issue_id,
            "recipient_hash": recipient_hash,
            "cohort": cohort,
            "locale": locale,
            "source": "deterministic",
        })
        return fallback

    # Local import so the deterministic-only test suite doesn't have to
    # import the LLM module (which would still work — no top-level side
    # effects — but the symmetry is nicer).
    from . import llm_commentary as llm_mod
    # Increment BEFORE the call so a crash inside llm_commentary still
    # counts against the cap (defensive against an infinite retry loop
    # tripping the cap-after-success-only path).
    _llm_commentary_count += 1
    result = llm_mod.llm_commentary(
        cohort=cohort,
        locale=locale,
        pref=pref,
        display_name=display_name,
        n_scanned=n_scanned,
        picks=picks,
        skip_pick=skip_pick,
        client_override=llm_client_override,
    )
    _telemetry_capture("newsletter.commentary_generated", {
        "issue_id": issue_id,
        "recipient_hash": recipient_hash,
        "cohort": cohort,
        "locale": locale,
        "source": "llm" if result.commentary else "deterministic_fallback",
        "llm_error": result.error,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
    })
    return result.commentary or fallback


def detect_cohort(recipient: Recipient) -> Cohort:
    has_prefs = bool(
        recipient.preference.zones
        or recipient.preference.departments
        or recipient.preference.property_types
        or recipient.preference.categories
        or recipient.preference.max_price_usd
    )
    if not recipient.has_account:
        return "anonymous"
    if recipient.tier in ("pro", "agency") and has_prefs:
        return "pro_prefs"
    if recipient.tier in ("pro", "agency") and not has_prefs:
        return "logged_no_prefs"
    if has_prefs:
        return "free_prefs"
    return "logged_no_prefs"


def fallback_preference(global_listings: list[dict]) -> Preference:
    """Used when a recipient has no filter yet (cohorts C/D).

    Strategy: anchor on the dominant zone in the *top quartile* of the global
    rank so the broadest fallback still pulls from value-priced listings, not
    random noise. Adds no price cap (anonymous users haven't signalled budget).
    """
    if not global_listings:
        return Preference()
    top_q = global_listings[: max(1, len(global_listings) // 4)]
    dept_counts: dict[str, int] = {}
    for listing in top_q:
        d = listing.get("department")
        if d:
            dept_counts[d] = dept_counts.get(d, 0) + 1
    if not dept_counts:
        return Preference()
    dominant = max(dept_counts.items(), key=lambda kv: kv[1])[0]
    # No category filter on fallback — we want breadth.
    return Preference(departments=[dominant])


def _absolute_photo(listing: dict, site_root: str) -> str:
    """Email needs absolute URLs. Prefer the source CDN; fall back to our
    Cloud-hosted copy at site_root + hero_photo_path."""
    urls = listing.get("photo_urls") or []
    if urls and isinstance(urls[0], str) and urls[0].startswith("http"):
        return urls[0]
    p = listing.get("hero_photo_path") or ""
    if p.startswith("http"):
        return p
    if p:
        return site_root.rstrip("/") + (p if p.startswith("/") else "/" + p)
    return ""  # renderer hides the image block when empty


def _location_line(listing: dict, locale: Locale) -> str:
    parts: list[str] = []
    if listing.get("municipality"):
        parts.append(listing["municipality"])
    if listing.get("department"):
        parts.append(listing["department"])
    pt = listing.get("property_type")
    if pt == "land" and listing.get("area_m2"):
        parts.append(i18n.t("facts.lot_m2", locale, n=f"{int(listing['area_m2']):,}"))
    elif pt in ("house", "condo"):
        if listing.get("bedrooms") and listing.get("bathrooms"):
            parts.append(
                i18n.t(
                    "facts.bed_bath",
                    locale,
                    beds=listing["bedrooms"],
                    baths=int(listing["bathrooms"]),
                )
            )
        if listing.get("built_area_m2"):
            parts.append(
                i18n.t("facts.built_m2", locale, n=int(listing["built_area_m2"]))
            )
    return " · ".join(parts)


def _format_price(listing: dict, locale: Locale) -> tuple[str, Optional[str]]:
    price = listing.get("price_usd")
    if price is None:
        return ("—", None)
    text = f"${int(price):,}"
    note_bits: list[str] = []
    if listing.get("is_repriced"):
        prev = listing.get("previous_price")
        if isinstance(prev, (int, float)) and prev > price:
            drop_pct = (prev - price) / prev * 100
            note_bits.append(
                f"down {drop_pct:.0f}% from ${int(prev):,}"
                if locale == "en"
                else f"baja {drop_pct:.0f}% desde ${int(prev):,}"
            )
        else:
            note_bits.append("repriced this cycle" if locale == "en" else "ajustada este ciclo")
    if listing.get("is_motivated"):
        note_bits.append("motivated seller" if locale == "en" else "vendedor motivado")
    return (text, " · ".join(note_bits) if note_bits else None)


def _pills(listing: dict, locale: Locale) -> list[str]:
    pills: list[str] = []
    pt = listing.get("property_type")
    if pt:
        pills.append(i18n.t(f"facts.{pt}", locale))
    if listing.get("is_beachfront"):
        pills.append(i18n.t("facts.beachfront", locale))
    elif listing.get("is_walk_to_beach"):
        pills.append(i18n.t("facts.walk_to_beach", locale))
    has_p = listing.get("has_power")
    has_w = listing.get("has_water")
    has_r = listing.get("has_paved_access")
    if has_p and has_w and has_r:
        pills.append(i18n.t("facts.power_water_road", locale))
    elif has_p and has_w:
        pills.append(i18n.t("facts.power_water", locale))
    elif has_p:
        pills.append(i18n.t("facts.power", locale))
    return pills[:3]


def _keytable(listing: dict, locale: Locale) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if listing.get("price_per_m2"):
        rows.append((
            "$/m²" if locale == "en" else "$/m²",
            f"${listing['price_per_m2']:,.0f}",
        ))
    if listing.get("price_vs_zone_pct") is not None:
        pct = listing["price_vs_zone_pct"]
        if pct < 0:
            rows.append((
                "vs zone" if locale == "en" else "vs zona",
                i18n.t("facts.vs_zone_below", locale, pct=f"{abs(pct):.0f}"),
            ))
        else:
            rows.append((
                "vs zone" if locale == "en" else "vs zona",
                i18n.t("facts.vs_zone_above", locale, pct=f"{pct:.0f}"),
            ))
    if listing.get("dist_beach_km") is not None:
        km = float(listing["dist_beach_km"])
        if km < 0.1:
            rows.append(("Beach" if locale == "en" else "Playa", i18n.t("facts.beachfront", locale)))
        else:
            rows.append((
                "Beach" if locale == "en" else "Playa",
                i18n.t("facts.beach", locale, km=f"{km:.1f}"),
            ))
    if listing.get("dist_airport_km") is not None:
        km = float(listing["dist_airport_km"])
        mins = int(km * 1.1)  # rough rule-of-thumb already used in the draft
        rows.append((
            "Airport" if locale == "en" else "Aeropuerto",
            i18n.t("facts.airport", locale, km=f"{km:.0f}", min=mins),
        ))
    dom = listing.get("days_listed")
    if isinstance(dom, int):
        if dom <= 3:
            rows.append((
                "Listed" if locale == "en" else "Publicado",
                i18n.t("facts.listed_new", locale),
            ))
        else:
            rows.append((
                "Listed" if locale == "en" else "Publicado",
                i18n.t("facts.listed_days", locale, n=dom),
            ))
    return rows[:6]


def _canonical_dict(value: Any) -> dict:
    """Defensive coerce — `title_canonical` / `short_description_canonical`
    are normally `{en, es}` dicts, but a stale listing may have left a
    raw string in either field (the enrichment pipeline used to write
    that shape). Treat anything non-dict as empty so the per-locale
    `.get()` chain falls through to the legacy `listing.get("title")` /
    `listing.get("description")` columns instead of crashing the entire
    issue render."""
    return value if isinstance(value, dict) else {}


def _blurb(listing: dict, locale: Locale) -> str:
    desc = _canonical_dict(listing.get("short_description_canonical"))
    text = desc.get(locale) or desc.get("en") or listing.get("description") or ""
    # First two sentences keep the email scannable. Heuristic split — good
    # enough for editorial copy from the LLM enrichment pipeline.
    sentences = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in ".!?" and len(buf) > 30:
            sentences.append(buf.strip())
            buf = ""
            if len(sentences) >= 2:
                break
    if buf.strip():
        sentences.append(buf.strip())
    return " ".join(sentences[:3]) or text[:400]


def _filter_summary_human(pref: Preference, locale: Locale, cohort: Cohort) -> str:
    """Turn the Recipient.preference into a single short human string.

    Examples:
      Preference(departments=["La Libertad"], property_types=["land"],
                 max_price_usd=500000)
                 → "La Libertad · land · under $500k"

      Preference(zones=["el-zonte"], categories=["beachfront"])
                 → "El Zonte · Beachfront"

      Preference() (anonymous / no filter)
                 → "" — the renderer swaps in welcome-style copy.

    Locale-aware: "under" / "menos de", "land" / "terreno" mapped via
    i18n keys to stay in sync with the rest of the email. Cohort
    `anonymous` short-circuits to "" — they don't have a filter yet,
    so showing a filter summary is misleading.
    """
    if cohort == "anonymous":
        return ""

    parts: list[str] = []

    # Departments are the most readable filter dimension; lead with them
    # but cap at 2 to keep the line short.
    for d in pref.departments[:2]:
        parts.append(d.title())
    # Zones only show when no departments are set — they're more
    # granular and would just repeat what the department row already says.
    if not pref.departments:
        for z in pref.zones[:2]:
            parts.append(z.replace("-", " ").title())

    # Property type — single most expected token.
    if "land" in pref.property_types:
        parts.append("land" if locale == "en" else "terreno")
    elif "house" in pref.property_types:
        parts.append("house" if locale == "en" else "casa")
    elif "condo" in pref.property_types:
        parts.append("condo" if locale == "en" else "condo")

    # Price cap — present only when it bites. Compact dollar format
    # ("$500k", not "$500,000") matches the mockup tone.
    if pref.max_price_usd:
        cap = int(pref.max_price_usd)
        if cap >= 1_000_000:
            money = f"${cap / 1_000_000:g}M"
        elif cap >= 1_000:
            money = f"${cap // 1_000}k"
        else:
            money = f"${cap}"
        parts.append(f"under {money}" if locale == "en" else f"menos de {money}")

    # Categories last — they're usually editorial, not structural.
    for c in pref.categories[:2]:
        parts.append(c.replace("_", " ").title())

    return " · ".join(parts) if parts else ""


def _pulpo_urls(listing: dict, *, issue_number: int, site_root: str) -> tuple[str, str]:
    """The canonical /listing/<source>__<source_id> page on pulpo.club plus
    a save variant. The save_url adds `?save=1` so the SPA auto-saves
    the listing on mount (PR-NL-8 wired this for /account-authed users).

    Separator is `__` (double underscore), matching the SPA's
    `adaptListing` id format at web/app/data/listings.ts:165 — the SPA's
    `parseLocation` regex `SAFE_LISTING_ID_RE = /^[A-Za-z0-9._\\-]+$/` at
    web/app/lib/url-routing.ts:102 rejects any other punctuation, so a
    colon or `/` here lands the reader on home instead of the listing
    detail. Caught 2026-05-29 after the first v3 send.

    Both URLs include `ref=newsletter_issue_<N>` so PostHog can attribute
    in-app conversion back to the issue."""
    source_id = f"{listing.get('source')}__{listing.get('source_id')}"
    base = f"{site_root.rstrip('/')}/listing/{source_id}"
    ref = f"ref=newsletter_issue_{issue_number}"
    return (f"{base}?{ref}", f"{base}?{ref}&save=1")


def _chips_for_listing(
    listing: dict,
    *,
    rank: int,
    locale: Locale,
    rank_threshold_top: int = 3,
) -> list[Chip]:
    """Pulpo-data-derived supportive chips for a pick.

    Each chip maps to a field on the Listing row — never to fabricated or
    LLM-derived content. The renderer color-codes by `kind`:
      warm    → recent action / urgency (price drop)
      cool    → strong positive signal (top pick, deep discount, build-ready)
      neutral → quiet context (distance, utilities, freshness)

    Priority order (warm > cool > neutral) decides which chips survive when
    we trim to `ISSUE_CHIPS_PER_PICK`. The first warm chip wins emotional
    weight in the rendered email — keep that one truthful above all else.
    """
    chips: list[Chip] = []

    # ── warm ── recent action the buyer cares about right now ────────
    if listing.get("is_repriced"):
        prev = listing.get("previous_price")
        cur = listing.get("price_usd")
        if isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and prev > cur:
            delta_pct = (prev - cur) / prev * 100
            delta_usd = prev - cur
            if delta_pct >= 10:
                # Large drops lead with the percentage (more striking).
                label = (
                    f"↓ Just dropped −{delta_pct:.0f}%" if locale == "en"
                    else f"↓ Acaba de bajar −{delta_pct:.0f}%"
                )
            else:
                # Small drops lead with the dollar number (more concrete).
                label = (
                    f"↓ Just dropped −${int(delta_usd):,}" if locale == "en"
                    else f"↓ Acaba de bajar −${int(delta_usd):,}"
                )
            chips.append(Chip(label=label, kind="warm"))

    # ── cool ── strong positive signals ──────────────────────────────
    if rank > 0 and rank <= rank_threshold_top:
        chips.append(Chip(
            label="★ Top pick this fortnight" if locale == "en" else "★ Selección destacada",
            kind="cool",
        ))

    pct = listing.get("price_vs_zone_pct")
    if isinstance(pct, (int, float)) and pct <= -30:
        # Frame the discount in plain language ("under area average"), not
        # the analyst phrasing ("vs zone median per m²"). The number stays
        # honest; the wording stays warm.
        n = abs(int(round(pct)))
        chips.append(Chip(
            label=f"−{n}% under area average" if locale == "en"
            else f"−{n}% bajo el promedio",
            kind="cool",
        ))

    readiness = listing.get("readiness_score")
    if isinstance(readiness, int) and readiness >= 3:
        chips.append(Chip(
            label="Build ready" if locale == "en" else "Listo para construir",
            kind="cool",
        ))

    # ── neutral ── quiet context the reader can scan ─────────────────
    if listing.get("is_walk_to_beach"):
        chips.append(Chip(
            label="Walk to beach" if locale == "en" else "A pie de la playa",
            kind="neutral",
        ))
    else:
        beach_km = listing.get("dist_beach_km")
        if isinstance(beach_km, (int, float)) and beach_km < 25:
            mins = max(1, int(round(beach_km * 1.1)))
            chips.append(Chip(
                label=f"{mins} min to beach" if locale == "en" else f"{mins} min a la playa",
                kind="neutral",
            ))

    if isinstance(readiness, int) and 1 <= readiness <= 2:
        # Name what IS there (not what's missing) so the chip stays positive
        # without misleading. The "trade-off" lives in the listing body.
        has = []
        if listing.get("has_power"):
            has.append("power" if locale == "en" else "electricidad")
        if listing.get("has_water"):
            has.append("water" if locale == "en" else "agua")
        if has:
            joined = " + ".join(has)
            chips.append(Chip(
                label=f"{joined.capitalize()} at the lot" if locale == "en"
                else f"{joined.capitalize()} en el lote",
                kind="neutral",
            ))

    dom = listing.get("days_listed")
    if isinstance(dom, int) and dom <= 7:
        chips.append(Chip(
            label="New this week" if locale == "en" else "Nueva esta semana",
            kind="neutral",
        ))

    # Trim to cap, preserving the warm > cool > neutral priority order
    # (the list above is already ordered that way).
    return chips[:ISSUE_CHIPS_PER_PICK]


def _resolve_llm_toggle() -> bool:
    """Decide whether LLM is on for this run.

    PR-NL-6 default: ON unless explicitly disabled. The env var takes
    precedence so operators can flip it per-issue via workflow_dispatch
    without redeploying. Accepted off-values: "0", "false", "no" (case-
    insensitive). Anything else (including unset / empty) → ON.
    """
    raw = os.environ.get(LLM_TOGGLE_ENV, "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return LLM_DEFAULT_ON


def _llm_or_deterministic_story(
    listing: dict,
    *,
    locale: Locale,
    issue_id: str,
    llm_client_override: Any = None,
) -> tuple[str, str]:
    """Per-pick warm paragraph (PR-NL-6).

    Returns `(story_html, source)` where source ∈
    {"llm", "deterministic", "fallback_on_error"}.

    Decision tree:

      • Cache hit (same source_id + locale already generated this
        process) → return the cached paragraph. **Critical at audience
        scale**: a 2,800-reader audience would otherwise generate the
        same listing's story 2,800× — wasteful and would punch through
        the runaway-billing cap.
      • LLM explicitly disabled (env=0/false/no) → deterministic
      • LLM cap hit → deterministic (one stderr line so the operator
        notices the cap was reached)
      • LLM call errored / returned empty → deterministic, source
        tagged `fallback_on_error` so PostHog telemetry separates
        baseline quality from LLM-output rate
      • Otherwise (default: ON) → LLM paragraph

    The deterministic story is always computed even when LLM is on —
    cheap, has no side effects, and means we never block hero rendering
    on the LLM finishing.
    """
    locale_safe: Locale = locale if locale in ("en", "es") else "en"
    source_id = f"{listing.get('source')}:{listing.get('source_id')}"

    # Cache lookup — the per-process audience-loop optimization.
    cache_key = (source_id, locale_safe)
    if llm_client_override is None and cache_key in _story_cache:
        cached_html, cached_source = _story_cache[cache_key]
        _telemetry_capture("newsletter.story_generated", {
            "issue_id": issue_id,
            "locale": locale_safe,
            "source": f"{cached_source}_cached",
            "source_id": source_id,
        })
        return (cached_html, cached_source)

    fallback = commentary_mod.deterministic_story_for_pick(listing, locale_safe)

    if not _resolve_llm_toggle() and llm_client_override is None:
        _telemetry_capture("newsletter.story_generated", {
            "issue_id": issue_id,
            "locale": locale_safe,
            "source": "deterministic",
            "source_id": source_id,
        })
        _story_cache[cache_key] = (fallback, "deterministic")
        return (fallback, "deterministic")

    # Stories share the same per-process cap with commentaries — the
    # `_llm_commentary_count` counter is the runaway-billing guard for
    # both. Increment before the call so a crash inside llm_story still
    # counts against the cap.
    global _llm_commentary_count
    cap = _llm_commentary_cap()
    if _llm_commentary_count >= cap and llm_client_override is None:
        import sys as _sys
        print(
            f"[newsletter] LLM story cap reached "
            f"({_llm_commentary_count}/{cap}); falling back to deterministic. "
            f"Raise via {LLM_COMMENTARY_CAP_ENV}=N if intentional.",
            file=_sys.stderr,
        )
        _telemetry_capture("newsletter.story_generated", {
            "issue_id": issue_id,
            "locale": locale_safe,
            "source": "deterministic_cap_reached",
        })
        _story_cache[cache_key] = (fallback, "deterministic")
        return (fallback, "deterministic")

    # Local import — keep the deterministic-only test suite light.
    from . import llm_story as llm_story_mod
    _llm_commentary_count += 1
    result = llm_story_mod.llm_story_for_pick(
        listing=listing,
        locale=locale_safe,
        client_override=llm_client_override,
    )
    _telemetry_capture("newsletter.story_generated", {
        "issue_id": issue_id,
        "locale": locale_safe,
        "source": "llm" if result.paragraph else "fallback_on_error",
        "source_id": f"{listing.get('source')}:{listing.get('source_id')}",
        "llm_error": result.error,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
    })
    if result.paragraph:
        # Cache the LLM result so subsequent recipients in the same
        # audience send share the same paragraph for this listing.
        if llm_client_override is None:
            _story_cache[cache_key] = (result.paragraph, "llm")
        return (result.paragraph, "llm")
    # LLM errored — cache the deterministic fallback under this key so
    # we don't burn tokens retrying every recipient.
    if llm_client_override is None:
        _story_cache[cache_key] = (fallback, "fallback_on_error")
    return (fallback, "fallback_on_error")


def _to_pick(
    listing: dict,
    *,
    rank: int,
    locale: Locale,
    paywalled: bool,
    site_root: str,
    issue_number: int = 0,
    is_hero: bool = False,
    issue_id: str = "",
    llm_client_override: Any = None,
) -> IssuePick:
    """Build an IssuePick from a Listing dict.

    `is_hero=True` enables PR-NL-6 story_html generation (AI or
    deterministic). Short picks keep using the legacy `blurb` so this
    PR doesn't touch their renderer — story_html is hero-only.
    `issue_id` and `llm_client_override` only matter when is_hero=True.
    """
    tc = _canonical_dict(listing.get("title_canonical"))
    title = tc.get(locale) or tc.get("en") or listing.get("title") or "Listing"
    price_text, price_note = _format_price(listing, locale)
    callouts = commentary_mod.pick_callouts_for_listing(listing, locale)
    pulpo_url, save_url = _pulpo_urls(listing, issue_number=issue_number, site_root=site_root)
    chips = _chips_for_listing(listing, rank=rank, locale=locale)
    story_html, story_source = ("", "")
    why_bullets: list[str] = []
    shortlist_frame_html = ""
    if is_hero and not paywalled:
        # Paywalled picks render the locked teaser instead of the story —
        # no point burning LLM tokens on a paragraph the reader never sees.
        story_html, story_source = _llm_or_deterministic_story(
            listing,
            locale=locale,
            issue_id=issue_id,
            llm_client_override=llm_client_override,
        )
        # v3 — three plain-English bullets replacing the opaque
        # "Why Pulpo ranked it: value 100 · momentum 50" row. Hero-only
        # because the shortlist gets a single "For someone who…" frame
        # below instead.
        why_bullets = commentary_mod.deterministic_why_for_pick(listing, locale)
    elif not is_hero and not paywalled:
        shortlist_frame_html = commentary_mod.deterministic_shortlist_frame(listing, locale)
    return IssuePick(
        rank=rank,
        source_id=f"{listing.get('source')}:{listing.get('source_id')}",
        title=title,
        location_line=_location_line(listing, locale),
        price_text=price_text,
        price_note=price_note,
        photo_url=_absolute_photo(listing, site_root),
        listing_url=listing.get("url") or site_root,
        pills=_pills(listing, locale),
        blurb=_blurb(listing, locale),
        callouts=callouts,
        keytable=_keytable(listing, locale),
        paywalled=paywalled,
        is_repriced=bool(listing.get("is_repriced")),
        is_new_this_fortnight=bool(listing.get("_is_new_window")),
        pulpo_url=pulpo_url,
        save_url=save_url,
        chips=chips,
        story_html=story_html,
        story_source=story_source,
        why_bullets=why_bullets,
        shortlist_frame_html=shortlist_frame_html,
    )


def build_issue(
    *,
    recipient: Recipient,
    ranked_listings: list[dict],
    issue_number: int,
    issue_date: Optional[datetime] = None,
    history_rows: Optional[list] = None,
    site_root: str = "https://pulpo.club",
    llm_client_override: Any = None,
) -> Issue:
    """Compose a personalised Issue ready for render_html.

    Parameters
    ----------
    recipient            who we're building for (cohort detection key)
    ranked_listings      web/data/ranked.json contents, sorted by rank asc
    issue_number         monotonic, used in the "ISSUE 0N" header
    issue_date           when this issue ships (used to derive the eligibility
                         window vs the recipient's last send); defaults to now
    history_rows         optional pre-loaded HistoryRow list (test seam)
    site_root            absolute URL prefix for routes that may be relative
    """
    issue_date = issue_date or datetime.now(timezone.utc)
    cohort = detect_cohort(recipient)
    locale = recipient.locale

    last_send = last_send_at_for(recipient.email_hash, history=history_rows)
    if last_send:
        window_start = last_send
    else:
        window_start = issue_date - timedelta(days=DEFAULT_WINDOW_DAYS)

    excluded = excluded_source_ids_for(recipient.email_hash, now=issue_date, history=history_rows)

    if cohort in ("anonymous", "logged_no_prefs"):
        effective_pref = fallback_preference(ranked_listings)
    else:
        effective_pref = recipient.preference

    kept_listings, skip_candidates = select_picks(
        ranked_listings,
        pref=effective_pref,
        excluded_source_ids=excluded,
        window_start=window_start,
        top_n=ISSUE_DEFAULT_TOP_N,
    )

    # If a tight filter starved the cut, top up from the global fallback so
    # we never ship a near-empty issue. Mark the top-ups visually (not yet —
    # PR-NL-3 will brand them "broader cut"). Always preserve global rank.
    if len(kept_listings) < 6 and cohort != "anonymous":
        fallback = select_picks(
            ranked_listings,
            pref=fallback_preference(ranked_listings),
            excluded_source_ids=excluded | {f"{listing.get('source')}:{listing.get('source_id')}" for listing in kept_listings},
            window_start=window_start,
            top_n=ISSUE_DEFAULT_TOP_N - len(kept_listings),
        )[0]
        kept_listings = kept_listings + fallback

    # ── Cohort-aware paywall flag ───────────────────────────────────────
    # free_prefs and free-logged-in users get pick #1 photo+headline only;
    # everything else is gated behind /api/stripe/start-checkout. Pro/agency
    # see all.
    paywall_all = recipient.tier == "free"

    # Computed once here so hero-pick story generation (PR-NL-6) can
    # stamp it onto each telemetry event without re-deriving inside the
    # loop. The downstream `issue_id = issue_date.strftime(...)` later
    # in this function reuses the same string for the Issue dataclass.
    issue_id = issue_date.strftime("%Y-%m-%d")

    rich_picks: list[IssuePick] = []
    for i, listing in enumerate(kept_listings[:ISSUE_TOP_PICKS_RICH]):
        rich_picks.append(_to_pick(
            listing,
            rank=i + 1,
            locale=locale,
            paywalled=paywall_all and i > 0,
            site_root=site_root,
            issue_number=issue_number,
            is_hero=True,                          # PR-NL-6 — generate story_html
            issue_id=issue_id,
            llm_client_override=llm_client_override,
        ))
    short_picks: list[IssuePick] = []
    for i, listing in enumerate(kept_listings[ISSUE_TOP_PICKS_RICH:]):
        short_picks.append(_to_pick(listing, rank=ISSUE_TOP_PICKS_RICH + i + 1, locale=locale, paywalled=paywall_all, site_root=site_root, issue_number=issue_number))

    skip_pick_listing = skip_candidates[0] if skip_candidates else None
    skip_pick = _to_pick(skip_pick_listing, rank=0, locale=locale, paywalled=False, site_root=site_root, issue_number=issue_number) if skip_pick_listing else None

    glance_rows: list[dict] = []
    for i, listing in enumerate(kept_listings):
        tc = _canonical_dict(listing.get("title_canonical"))
        glance_rows.append({
            "num": f"{i + 1:02d}",
            "title": tc.get(locale) or tc.get("en") or listing.get("title") or "—",
            "where": _location_line(listing, locale),
            "price": (f"${int(listing['price_usd']):,}" if listing.get("price_usd") else "—"),
        })
    if skip_pick_listing:
        tc = _canonical_dict(skip_pick_listing.get("title_canonical"))
        glance_rows.append({
            "num": "×",
            "title": tc.get(locale) or tc.get("en") or skip_pick_listing.get("title") or "—",
            "where": _location_line(skip_pick_listing, locale),
            "price": (f"${int(skip_pick_listing['price_usd']):,}" if skip_pick_listing.get("price_usd") else "—"),
            "muted": True,
        })

    # issue_id already computed above for hero-pick story telemetry.
    commentary = _llm_or_deterministic_commentary(
        cohort=cohort,
        locale=locale,
        pref=effective_pref,
        display_name=recipient.display_name,
        n_scanned=len(ranked_listings),
        picks=kept_listings,
        skip_pick=skip_pick_listing,
        recipient_hash=recipient.email_hash,
        issue_id=issue_id,
        llm_client_override=llm_client_override,
    )

    _telemetry_capture("newsletter.issue_built", {
        "issue_id": issue_id,
        "issue_number": issue_number,
        "recipient_hash": recipient.email_hash,
        "cohort": cohort,
        "locale": locale,
        "tier": recipient.tier,
        "has_account": recipient.has_account,
        "picks_total": len(kept_listings),
        "has_skip": skip_pick_listing is not None,
        "paywall_banner": paywall_all,
    })

    # ── URLs ────────────────────────────────────────────────────────────
    settings_url = f"{site_root.rstrip('/')}/account?ref=newsletter_issue_{issue_number}"
    # The visible footer Unsubscribe link must match the URL pattern the
    # `/api/unsubscribe` handler accepts: `/api/unsubscribe?r=<hash>&i=<n>&t=<hmac>`.
    # Two bugs the prior path had:
    #   1. Missing /api prefix — `/unsubscribe?...` hit Vercel's
    #      catch-all `/:slug([A-Za-z0-9_-]+)` rule and 404'd before the
    #      handler ran.
    #   2. Missing &t=<hmac> token — the handler rejects requests
    #      without it (HMAC-SHA256 keyed on PULPO_UNSUBSCRIBE_SECRET).
    # The token logic lives in `send.unsubscribe_token` so the
    # security-critical HMAC stays single-sourced; URL assembly happens
    # here so the test-injected `site_root` parameter takes effect (which
    # `send.unsubscribe_url` couldn't honor because it reads the env var
    # itself).
    from .send import unsubscribe_token as _unsub_token
    UNSUBSCRIBE_SECRET_ENV = "PULPO_UNSUBSCRIBE_SECRET"
    _unsub_secret = os.environ.get(UNSUBSCRIBE_SECRET_ENV, "")
    _unsub_t = _unsub_token(recipient.email_hash, issue_number, _unsub_secret) if _unsub_secret else ""
    unsubscribe_url = (
        f"{site_root.rstrip('/')}/api/unsubscribe"
        f"?r={recipient.email_hash}&i={issue_number}&t={_unsub_t}"
    )
    paywall_url = (
        f"{site_root.rstrip('/')}/api/stripe/start-checkout?ref=newsletter_issue_{issue_number}"
    )
    welcome_prefs_url = None
    if cohort == "anonymous":
        welcome_prefs_url = (
            f"{site_root.rstrip('/')}/welcome?r={recipient.email_hash}&ref=newsletter_issue_{issue_number}"
        )

    # ── PR-NL-8 — Your Pulpo block ─────────────────────────────────────
    # `filter_match_count` is the size of the full filtered cut against
    # `ranked_listings` (not the trimmed top-N) — it answers "how many
    # listings match your filter right now" without coupling to whatever
    # ISSUE_DEFAULT_TOP_N happens to be.
    filter_match_count = (
        len(apply_preference(ranked_listings, effective_pref))
        if cohort != "anonymous" else len(ranked_listings)
    )
    your_pulpo = YourPulpoState(
        saved_count=recipient.saved_count,
        filter_summary_human=_filter_summary_human(effective_pref, locale, cohort),
        filter_match_count=filter_match_count,
    )

    return Issue(
        issue_id=issue_id,
        issue_number=issue_number,
        issue_date_human=issue_date.strftime("%-d %b %Y") if hasattr(issue_date, "strftime") else "",
        recipient=recipient,
        cohort=cohort,
        locale=locale,
        glance=glance_rows,
        picks_top=rich_picks,
        picks_shortlist=short_picks,
        skip_pick=skip_pick,
        commentary=commentary,
        paywall_banner=paywall_all,
        paywall_target_url=paywall_url,
        settings_url=settings_url,
        unsubscribe_url=unsubscribe_url,
        welcome_prefs_url=welcome_prefs_url,
        your_pulpo=your_pulpo,
    )
