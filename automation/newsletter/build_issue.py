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
from .segments import select_picks
from .store import excluded_source_ids_for, last_send_at_for
from .types import (
    Cohort,
    Commentary,
    Issue,
    IssuePick,
    Locale,
    Preference,
    Recipient,
)

ISSUE_DEFAULT_TOP_N = 10
ISSUE_TOP_PICKS_RICH = 2   # picks rendered with a full hero image + callouts
DEFAULT_WINDOW_DAYS = 14

LLM_TOGGLE_ENV = "PULPO_NEWSLETTER_USE_LLM"


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


def _blurb(listing: dict, locale: Locale) -> str:
    desc = listing.get("short_description_canonical") or {}
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


def _to_pick(listing: dict, *, rank: int, locale: Locale, paywalled: bool, site_root: str) -> IssuePick:
    tc = listing.get("title_canonical") or {}
    title = tc.get(locale) or tc.get("en") or listing.get("title") or "Listing"
    price_text, price_note = _format_price(listing, locale)
    callouts = commentary_mod.pick_callouts_for_listing(listing, locale)
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

    rich_picks: list[IssuePick] = []
    for i, listing in enumerate(kept_listings[:ISSUE_TOP_PICKS_RICH]):
        rich_picks.append(_to_pick(listing, rank=i + 1, locale=locale, paywalled=paywall_all and i > 0, site_root=site_root))
    short_picks: list[IssuePick] = []
    for i, listing in enumerate(kept_listings[ISSUE_TOP_PICKS_RICH:]):
        short_picks.append(_to_pick(listing, rank=ISSUE_TOP_PICKS_RICH + i + 1, locale=locale, paywalled=paywall_all, site_root=site_root))

    skip_pick_listing = skip_candidates[0] if skip_candidates else None
    skip_pick = _to_pick(skip_pick_listing, rank=0, locale=locale, paywalled=False, site_root=site_root) if skip_pick_listing else None

    glance_rows: list[dict] = []
    for i, listing in enumerate(kept_listings):
        tc = listing.get("title_canonical") or {}
        glance_rows.append({
            "num": f"{i + 1:02d}",
            "title": tc.get(locale) or tc.get("en") or listing.get("title") or "—",
            "where": _location_line(listing, locale),
            "price": (f"${int(listing['price_usd']):,}" if listing.get("price_usd") else "—"),
        })
    if skip_pick_listing:
        tc = skip_pick_listing.get("title_canonical") or {}
        glance_rows.append({
            "num": "×",
            "title": tc.get(locale) or tc.get("en") or skip_pick_listing.get("title") or "—",
            "where": _location_line(skip_pick_listing, locale),
            "price": (f"${int(skip_pick_listing['price_usd']):,}" if skip_pick_listing.get("price_usd") else "—"),
            "muted": True,
        })

    issue_id = issue_date.strftime("%Y-%m-%d")
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
    unsubscribe_url = (
        f"{site_root.rstrip('/')}/unsubscribe?r={recipient.email_hash}&i={issue_number}"
    )
    paywall_url = (
        f"{site_root.rstrip('/')}/api/stripe/start-checkout?ref=newsletter_issue_{issue_number}"
    )
    welcome_prefs_url = None
    if cohort == "anonymous":
        welcome_prefs_url = (
            f"{site_root.rstrip('/')}/welcome?r={recipient.email_hash}&ref=newsletter_issue_{issue_number}"
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
    )
