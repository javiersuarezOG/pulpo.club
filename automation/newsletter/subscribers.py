"""Build the per-issue recipient list by joining Resend Audience contacts
with Clerk users.

Identity model:
- Resend Audience is the source-of-truth for "who is subscribed". Anonymous
  email-only signups live here without a Clerk user.
- Clerk is the source-of-truth for "what tier + what newsletter preference".
  We match by email (lowercased + trimmed). When a Resend contact has a
  matching Clerk user, we promote them to the corresponding cohort; when
  there's no match, they're cohort=anonymous.

PII rule: we hash emails for telemetry (store.email_hash) but the actual
address still has to go to Resend at send time. Logs use email_domain only.

Env contract:
    RESEND_API_KEY        — required to enumerate audience
    RESEND_AUDIENCE_ID    — required (UUID of the audience)
    CLERK_SECRET_KEY      — optional; without it, every recipient is anon
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .store import email_hash
from .types import Locale, Preference, Recipient, SavedListing

RESEND_API_BASE = "https://api.resend.com"
CLERK_API_BASE = "https://api.clerk.com/v1"
CLERK_PAGE_SIZE = 200                                 # Clerk caps at 500
RESEND_PAGE_SIZE = 100


# ── HTTP wrappers (lazy httpx import, monkeypatched in tests) ────────────
def _get_json(url: str, *, headers: dict, params: Optional[dict] = None,
              timeout: float = 15.0) -> dict:
    import httpx  # type: ignore
    r = httpx.get(url, headers=headers, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ── Resend audience enumeration ───────────────────────────────────────────
@dataclass
class ResendContact:
    id: str
    email: str
    unsubscribed: bool
    created_at: Optional[str]
    # LEARNING: locale side-channel. /api/newsletter writes
    # "pulpo-locale:<lc>" into the Resend contact's first_name on
    # subscribe; we parse it back here so anonymous subscribers
    # (no matching Clerk user) get their newsletter in the language
    # they signed up in. None when the prefix is missing or malformed;
    # the consumer in join_recipients() falls back to "en" in that case
    # — identical to pre-2026-05-28 behavior. See docs/email-audit.md.
    locale: Optional[Locale] = None


_LOCALE_PREFIX = "pulpo-locale:"
_LOCALE_VALUES: tuple[Locale, ...] = ("en", "es")


def _parse_locale_first_name(raw: Any) -> Optional[Locale]:
    if not isinstance(raw, str):
        return None
    if not raw.startswith(_LOCALE_PREFIX):
        return None
    suffix = raw[len(_LOCALE_PREFIX):].strip().lower()
    return suffix if suffix in _LOCALE_VALUES else None  # type: ignore[return-value]


def list_audience(
    audience_id: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    get_override: Any = None,
) -> list[ResendContact]:
    """List every contact in a Resend audience.

    Resend's contacts API is not paginated as of 2026 — `data` is the full
    list. If that changes, switch to the cursor scheme noted in their docs.
    """
    audience_id = audience_id or os.environ.get("RESEND_AUDIENCE_ID", "")
    api_key = api_key or os.environ.get("RESEND_API_KEY", "")
    if not audience_id or not api_key:
        return []
    url = f"{RESEND_API_BASE}/audiences/{audience_id}/contacts"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = (get_override or _get_json)(url, headers=headers)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[ResendContact] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        email = r.get("email")
        if not isinstance(email, str) or "@" not in email:
            continue
        # Resend returns first_name in either snake- or camel-case
        # depending on SDK version; tolerate both.
        first_name = r.get("first_name") or r.get("firstName")
        out.append(ResendContact(
            id=str(r.get("id") or ""),
            email=email.strip().lower(),
            unsubscribed=bool(r.get("unsubscribed", False)),
            created_at=r.get("created_at"),
            locale=_parse_locale_first_name(first_name),
        ))
    return out


# ── Clerk user enumeration ────────────────────────────────────────────────
@dataclass
class ClerkUser:
    id: str
    email: str
    first_name: Optional[str]
    plan: str
    profile: dict
    # PR-NL-8 — `privateMetadata.saves[]` length. The newsletter's
    # "Your Pulpo" block reads this to render the saved-listings row.
    # Stored as a count, not the actual ids, since the email only needs
    # the headline number ("3 saved listings from past issues").
    saved_count: int = 0
    # Favorites backend — the FULL saves array, normalized to a list of
    # `{id, saved_at?, price_at_save_usd?, source?}` dicts. Newer
    # entries are emitted by api/saves.js with enrichment; older
    # entries are bare ID strings and surface here with None baselines.
    # The newsletter pipeline turns this into FavoriteUpdate rows for
    # the "Your saved listings" section via commentary.compute_favorites.
    saves: list[dict] = field(default_factory=list)


def list_clerk_users(
    *,
    secret_key: Optional[str] = None,
    get_override: Any = None,
    page_size: int = CLERK_PAGE_SIZE,
) -> list[ClerkUser]:
    """Paginate through Clerk's /users endpoint.

    Quiet no-op when CLERK_SECRET_KEY is missing — for local / partial-env
    dry-runs we just degrade every recipient to anonymous.
    """
    secret_key = secret_key or os.environ.get("CLERK_SECRET_KEY", "")
    if not secret_key:
        return []
    headers = {"Authorization": f"Bearer {secret_key}"}
    out: list[ClerkUser] = []
    offset = 0
    getter = get_override or _get_json
    while True:
        params = {"limit": page_size, "offset": offset}
        payload = getter(f"{CLERK_API_BASE}/users", headers=headers, params=params)
        rows = payload if isinstance(payload, list) else payload.get("data")
        if not isinstance(rows, list) or not rows:
            break
        for u in rows:
            user = _parse_clerk_user(u)
            if user is not None:
                out.append(user)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def _parse_clerk_user(u: dict) -> Optional[ClerkUser]:
    if not isinstance(u, dict):
        return None
    email = _primary_email(u)
    if not email:
        return None
    public_md = u.get("public_metadata") or u.get("publicMetadata") or {}
    if not isinstance(public_md, dict):
        public_md = {}
    plan = public_md.get("plan")
    if not isinstance(plan, str) or plan not in ("pro", "agency", "free"):
        plan = "free"
    profile = public_md.get("profile") if isinstance(public_md.get("profile"), dict) else {}
    # PR-NL-8 — saves live in privateMetadata (per api/saves.js). Read
    # defensively so a missing or wrong-shaped value degrades to 0
    # rather than crashing the entire audience send.
    private_md = u.get("private_metadata") or u.get("privateMetadata") or {}
    raw_saves = private_md.get("saves") if isinstance(private_md, dict) else None
    saves = _normalize_saves(raw_saves)
    return ClerkUser(
        id=str(u.get("id") or ""),
        email=email,
        first_name=(u.get("first_name") or u.get("firstName")) or None,
        plan=plan,
        profile=profile,
        saved_count=len(saves),
        saves=saves,
    )


def _normalize_saves(raw: Any) -> list[dict]:
    """Coerce the mixed saves array into a list of enriched dicts.

    privateMetadata.saves[] is a MIXED array (post-favorites-backend):
      • Legacy entries: bare ID strings — `"remax__001461165132"`
      • New entries: `{id, saved_at?, price_at_save_usd?, source?}`

    Returns a flat list of normalized dicts. Always-present `id`,
    optional baselines. Malformed entries (None, ints, dicts without
    `id`) are dropped silently so a single bad record can't block the
    rest of the recipient's favorites section.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if isinstance(entry, str) and entry:
            out.append({"id": entry})
            continue
        if isinstance(entry, dict):
            eid = entry.get("id")
            if isinstance(eid, str) and eid:
                normalized: dict = {"id": eid}
                sa = entry.get("saved_at")
                if isinstance(sa, str) and sa:
                    normalized["saved_at"] = sa
                pas = entry.get("price_at_save_usd")
                if isinstance(pas, (int, float)) and pas > 0:
                    normalized["price_at_save_usd"] = float(pas)
                src = entry.get("source")
                if isinstance(src, str) and src:
                    normalized["source"] = src
                out.append(normalized)
    return out


def _primary_email(u: dict) -> Optional[str]:
    addresses = u.get("email_addresses") or u.get("emailAddresses") or []
    primary_id = u.get("primary_email_address_id") or u.get("primaryEmailAddressId")
    if not isinstance(addresses, list):
        return None
    if primary_id:
        for a in addresses:
            if isinstance(a, dict) and a.get("id") == primary_id:
                em = a.get("email_address") or a.get("emailAddress")
                if isinstance(em, str) and "@" in em:
                    return em.strip().lower()
    # Fallback: first verified address; then first overall.
    for a in addresses:
        if isinstance(a, dict):
            em = a.get("email_address") or a.get("emailAddress")
            if isinstance(em, str) and "@" in em:
                return em.strip().lower()
    return None


# ── Join → Recipient list ─────────────────────────────────────────────────

# P3 (2026-05-29) — DiscoverFilter → Preference translation table.
#
# The Discover filter (web/app/lib/user-profile.ts :: DiscoverFilter)
# carries axes the cron's `Preference` shape doesn't model 1-1. The
# tables below pin the mapping. Axes that DON'T appear here are
# intentionally dropped (they're Discover-only browsing controls):
#
#   land_types     — residential/commercial/tourist tagging (no cron use)
#   infra          — water/power/paved/sewage (no cron use)
#   status         — Discover "new"/"price_drop" pills (already implied by ranker)
#   size_min       — no min-size filter on Preference yet
#   readiness      — Discover-only readiness floor
#   rank_max       — Discover-only "Top 10" pill
#   master_category — Beach/Lake IA navigation, not a filter axis
_DISCOVER_SUBCATEGORY_TO_PROPERTY_TYPE = {
    "homes": "house",
    "condos": "condo",
    "land":  "land",
}

# `features` + `discovery_tags` both map into the cron's `categories`
# vocabulary. The mapping is intentionally narrow: only values that
# have a clear semantic equivalent on the cron side are translated.
# Unknown entries are dropped — the cron will fall back to the broad
# cut rather than apply a category predicate it doesn't recognise.
_DISCOVER_FEATURE_TO_CATEGORY = {
    "beachfront":     "beachfront",
    "water_body":     "water_features",
    # Drop without mapping (no cron-side category):
    #   ocean_view, mountain_view, flat
}
_DISCOVER_TAG_TO_CATEGORY = {
    "under_250k": "under_250k",
    "waterfront": "beachfront",      # the Discover "Waterfront" pill is the
                                     # broad beachfront/water-body bucket;
                                     # cron's "beachfront" category captures it.
    # Drop without mapping:
    #   top_rated  — rank-floor concept, not a category
    #   gated      — no cron-side category yet
}


def _preference_from_discover_filters(discover: dict) -> Preference:
    """Translate `publicMetadata.profile.discover_filters` → Preference.

    P3 of the unified-filter rollout (Discover panel ↔ /account/newsletter
    ↔ newsletter cron). Empty / missing → empty Preference (the cohort
    fallback kicks in inside build_issue).

    See the mapping tables above for which Discover axes survive the
    translation and which are intentionally dropped (Discover-only
    browsing controls vs. cron-consumable filter axes).
    """
    if not isinstance(discover, dict):
        return Preference()

    def _list_of_str(v):
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    # property_types ← subcategory (single string → 1-element list)
    property_types: list[str] = []
    sub = discover.get("subcategory")
    if isinstance(sub, str):
        translated = _DISCOVER_SUBCATEGORY_TO_PROPERTY_TYPE.get(sub)
        if translated:
            property_types.append(translated)

    # categories ← features + discovery_tags (translated + deduped,
    # preserving insertion order for deterministic test output)
    categories: list[str] = []
    seen: set[str] = set()
    for feat in _list_of_str(discover.get("features")):
        mapped = _DISCOVER_FEATURE_TO_CATEGORY.get(feat)
        if mapped and mapped not in seen:
            categories.append(mapped)
            seen.add(mapped)
    for tag in _list_of_str(discover.get("discovery_tags")):
        mapped = _DISCOVER_TAG_TO_CATEGORY.get(tag)
        if mapped and mapped not in seen:
            categories.append(mapped)
            seen.add(mapped)

    return Preference(
        zones=_list_of_str(discover.get("zones")),
        # `departments` doesn't exist in DiscoverFilter — users who
        # migrated to the unified filter pick zones (more specific)
        # instead. Leave departments empty; apply_preference's
        # conjunctive AND on department + zone means an empty
        # departments list is the "no opinion" branch.
        departments=[],
        property_types=property_types,
        max_price_usd=(
            discover["price_max"]
            if isinstance(discover.get("price_max"), (int, float))
            else None
        ),
        min_price_usd=(
            discover["price_min"]
            if isinstance(discover.get("price_min"), (int, float)) and discover["price_min"] > 0
            else None
        ),
        categories=categories,
    )


def _preference_from_profile(profile: dict) -> Preference:
    """Read the recipient's preference off Clerk's publicMetadata.profile.

    Precedence (post-2026-05-29):
      1. `discover_filters` — the unified Discover ↔ /account/newsletter
         shape (P2a-2). Picked when the blob is present + non-empty.
      2. `newsletter` — legacy narrow shape (departments / property_types /
         max_price_usd). Retained as a fallback for users who hadn't
         touched the new UI by the time P3 shipped; the dashboard will
         tell us when to drop it.
      3. Empty Preference — the cohort fallback inside build_issue then
         picks the broadest cut.

    Tolerates extra keys we don't know about — the cron is forward-
    compatible with new fields either UI starts writing.
    """
    if not isinstance(profile, dict):
        return Preference()

    discover = profile.get("discover_filters")
    if isinstance(discover, dict) and discover:
        return _preference_from_discover_filters(discover)

    nl = profile.get("newsletter")
    if not isinstance(nl, dict):
        return Preference()
    def _list_of_str(v):
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
    return Preference(
        zones=_list_of_str(nl.get("zones")),
        departments=_list_of_str(nl.get("departments")),
        property_types=_list_of_str(nl.get("property_types")),
        max_price_usd=nl.get("max_price_usd") if isinstance(nl.get("max_price_usd"), (int, float)) else None,
        min_price_usd=nl.get("min_price_usd") if isinstance(nl.get("min_price_usd"), (int, float)) else None,
        categories=_list_of_str(nl.get("categories")),
    )


def _locale_for(user: Optional[ClerkUser]) -> Locale:
    if user is None:
        return "en"
    nl = (user.profile.get("newsletter") if isinstance(user.profile, dict) else None) or {}
    lc = nl.get("locale") if isinstance(nl, dict) else None
    return "es" if lc == "es" else "en"


# PR-NL-9 (audience scope) — the personalised newsletter is a Pro
# feature. Free and anonymous recipients used to receive a paywalled /
# fallback variant; that's removed. Free users will get a different
# product on a separate pipeline; anonymous subscribers get nothing
# from this cron. The filter is enforced in join_recipients so a stale
# call site that bypasses it can't quietly re-introduce free sends.
PRO_AUDIENCE_TIERS: frozenset[str] = frozenset({"pro", "agency"})


def join_recipients(
    *,
    contacts: Iterable[ResendContact],
    clerk_users: Iterable[ClerkUser],
    include_unsubscribed: bool = False,
    only_emails: Optional[set[str]] = None,
) -> list[Recipient]:
    """Build the cron's per-recipient queue.

    PR-NL-9 (audience scope): only Pro + Agency recipients land in the
    queue. Free-tier and Resend-only (anonymous, no Clerk match)
    contacts are silently dropped — they're not the audience for this
    newsletter, and a different system will handle them.

    `only_emails` is the smoke-test seam — pass `{"javier@suarez.ventures"}`
    to send Issue 01 to a single address. The set is matched case-insensitively
    against the Resend audience. Note: even with `only_emails`, the Pro
    filter still applies; a free-tier address passed through this seam
    will still be dropped.
    """
    by_email: dict[str, ClerkUser] = {
        u.email: u for u in clerk_users if u.email
    }
    only = {e.strip().lower() for e in only_emails} if only_emails else None

    out: list[Recipient] = []
    seen: set[str] = set()
    for c in contacts:
        if c.email in seen:
            continue
        seen.add(c.email)
        if not include_unsubscribed and c.unsubscribed:
            continue
        if only is not None and c.email not in only:
            continue
        user = by_email.get(c.email)
        # Pro / Agency gate. Anonymous (no Clerk record) is filtered
        # here; free-tier Clerk users are filtered by the tier check
        # right after.
        if user is None:
            continue
        if user.plan not in PRO_AUDIENCE_TIERS:
            continue
        preference = _preference_from_profile(user.profile)
        recipient = Recipient(
            email_hash=email_hash(c.email),
            display_name=user.first_name,
            locale=_locale_for(user),
            tier=user.plan,
            has_account=True,
            preference=preference,
            saved_count=user.saved_count,
            saves=[SavedListing(
                id=s["id"],
                saved_at=s.get("saved_at"),
                price_at_save_usd=s.get("price_at_save_usd"),
                source=s.get("source"),
            ) for s in user.saves],
        )
        out.append(recipient)
    return out


def synthesize_preview_recipients(
    email: str,
    *,
    locale: Locale = "en",
) -> list[tuple[Recipient, str]]:
    """ONE fake recipient — the Pro-with-prefs variant — addressed to the
    operator's email.

    PR-NL-9 (audience scope): the personalised newsletter is a Pro
    feature, so the preview only needs to vet what a Pro subscriber
    actually sees. The earlier anonymous + free_prefs variants are
    removed; Free users will get a different product on a separate
    pipeline, and anonymous subscribers are not part of this audience.

    Preference: `departments=["La Libertad"]`. Wide enough that the
    picker always finds picks, narrow enough that the operator sees
    the "filter applied" branch render (not the broad fallback).

    `locale` controls which language the rendered email is in. The
    admin widget lets the operator pick EN or ES so they can QA both
    variants from the same surface.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValueError(f"synthesize_preview_recipients: invalid email {email!r}")
    if locale not in ("en", "es"):
        raise ValueError(f"synthesize_preview_recipients: invalid locale {locale!r}")
    eh = email_hash(email)
    recipients = [
        Recipient(
            email_hash=eh,
            display_name="Preview",
            locale=locale,
            tier="pro",
            has_account=True,
            preference=Preference(departments=["La Libertad"]),
        ),
    ]
    return [(r, email) for r in recipients]


def build_recipient_queue(
    *,
    only_emails: Optional[set[str]] = None,
    include_unsubscribed: bool = False,
) -> list[tuple[Recipient, str]]:
    """End-to-end helper: fetch + join + return (recipient, raw_email) tuples.

    `raw_email` is what gets passed to Resend's `to` field — we keep it
    out of the Recipient dataclass so logs that serialize Recipient don't
    accidentally leak PII.
    """
    contacts = list_audience()
    users = list_clerk_users()
    recipients = join_recipients(
        contacts=contacts,
        clerk_users=users,
        include_unsubscribed=include_unsubscribed,
        only_emails=only_emails,
    )
    # Pair each Recipient with its raw email — rely on positional order
    # being stable inside join_recipients (it iterates contacts in input
    # order and only appends matches).
    email_by_hash = {email_hash(c.email): c.email for c in contacts}
    return [(r, email_by_hash[r.email_hash]) for r in recipients]
