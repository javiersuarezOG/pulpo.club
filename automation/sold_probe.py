"""Sold/delisted probe for missing listings — plan 012.

When the existence ledger marks a listing ``missing_recently`` or
``stale`` we know it vanished from the scrape, but not WHY: sold,
broker deleted the page, or scraper drift. This module fetches the
listing's live page (through the same per-source transport policy the
scrapers use, so WAF'd hosts don't 403 and masquerade as delisted) and
classifies the outcome into ``automation.listing_ledger.
KNOWN_REMOVAL_REASONS`` — the closed set this module is the producer
for. Consumers: the ``[sold_probe]`` nightly summary line, the
``sold_probe_completed`` PostHog event, and run.py's ``is_sold``
stamping onto shipped listings.

URL source (``urls_by_key``)
----------------------------
The ledger deliberately does not store URLs. The caller builds a
``{source|source_id: url}`` mapping from the PREVIOUS nightly's
``web/data/ranked.json`` — read from the working tree BEFORE
``phase_write_outputs`` overwrites it. That file is the reliable
superset: ``automation/carry_forward.py`` itself trusts the same
artifact (via ``git show origin/main:web/data/ranked.json``, which in
the nightly runner is byte-identical to the checked-out file), and
carry-forward rows retain their ``url`` field, so listings carried
across failed-source nights stay probe-able. Entries missing from the
mapping (e.g. long-stale rows that predate the retained ranked.json)
are skipped and counted in ``skipped_no_url`` — the retroactive sweep
in ``scripts/probe_stale_listings.py`` can be pointed at older
snapshots if that backlog ever matters.

Fail-open contract
------------------
Everything here is best-effort: a fetch error leaves the entry
un-probed (it is retried next nightly), the LLM fallback is budget-
capped and optional, and the run.py call site wraps the whole step in
try/except so the nightly can never freeze on a probe bug.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import typing as t
from urllib.parse import urlsplit

from automation.listing_ledger import (
    KNOWN_REMOVAL_REASONS,
    LedgerEntry,
)
from automation.llm_enrichment import _cost_usd
from pulpo.normalize import _SOLD_RE

# States classify_page can return: every removal reason, plus "active"
# (the page is still a live listing — NOT a removal; the ledger entry
# is left un-classified so a later nightly re-checks it).
_ACTIVE = "active"
_VALID_LLM_STATES = frozenset(KNOWN_REMOVAL_REASONS) | {_ACTIVE}

_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]*content=["\']([^"\']*)',
    re.IGNORECASE,
)
# Legal boilerplate that collides with _SOLD_RE's reservado/reservada
# markers: "Todos los derechos reservados" sits in the footer of
# virtually every Spanish-language broker site (live finding from the
# 2026-06-12 pre-merge probe dry-run: EVERY bienesraices page matched).
# Stripped from body text before the ambiguity check below.
_RIGHTS_RESERVED_RE = re.compile(
    r"(?:todos\s+los\s+)?derechos\s+reservados|all\s+rights\s+reserved",
    re.IGNORECASE,
)

_LLM_SYSTEM_PROMPT = (
    'Classify this real-estate listing page: respond JSON '
    '{"state": "active"|"sold"|"delisted"|"unknown"}. '
    '"sold" needs an explicit sold/under-contract statement; '
    'a missing/blank/redirected page is "delisted".'
)


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub(" ", html)


def _path_depth(url: str) -> int:
    """Number of non-empty path segments. ``https://x.com/`` → 0,
    ``https://x.com/propiedad/lote-123`` → 2."""
    try:
        return len([seg for seg in urlsplit(url).path.split("/") if seg])
    except ValueError:
        return 0


def _focused_text(html: str) -> str:
    """The page surfaces where a listing's OWN status is stamped:
    ``<title>``, ``og:title``, and ``<h1>`` headings. Related-listings
    widgets and footers never reach these."""
    parts: list[str] = []
    m = _TITLE_RE.search(html)
    if m:
        parts.append(_strip_tags(m.group(1)))
    og = _OG_TITLE_RE.search(html)
    if og:
        parts.append(og.group(1))
    for h1 in _H1_RE.finditer(html):
        parts.append(_strip_tags(h1.group(1)))
    return " ".join(" ".join(parts).split())


def classify_page(
    status_code: int,
    final_url: str,
    original_url: str,
    html_text: str | None,
) -> str:
    """Pure classification — no I/O. Returns one of
    ``KNOWN_REMOVAL_REASONS`` or ``"active"`` (listing still live; not
    a removal).

    Ladder (first hit wins):
      1. 404/410                                  → delisted
      2. redirect landed far from the listing
         (final path is root/near-root while the
         original had a deeper path)              → delisted
      3. 200 + sold marker in the page's FOCUSED
         text (<title>/og:title/<h1>)             → sold
      4. 200, no marker anywhere in the body
         (legal "derechos reservados" boilerplate
         stripped first)                          → active
      5. 200, marker in the body but NOT in the
         focused text — could be a "recently
         sold" related-listings widget            → unknown (LLM decides)
      6. anything else                            → unknown (LLM-eligible)

    Steps 3-5 exist because of a live pre-merge finding (2026-06-12):
    scanning the whole body with the shared ``_SOLD_RE`` classified two
    KNOWN-LIVE listings as sold — goodlife's related-properties widget
    lists other "*SOLD*" listings, and bienesraices' footer says
    "Todos los derechos reservados" on every page. The regex stays
    shared with ingest on purpose (one pattern, one test surface);
    what differs here is WHICH text it runs against.
    """
    if status_code in (404, 410):
        return "delisted"
    # Deliberately dumb redirect heuristic: brokers that pull a listing
    # typically 301 it to the homepage or a /search|/category index —
    # i.e. a near-root path — while live listings keep their deep slug.
    if (
        final_url
        and original_url
        and final_url.rstrip("/") != original_url.rstrip("/")
        and _path_depth(original_url) >= 2
        and _path_depth(final_url) <= 1
    ):
        return "delisted"
    if status_code == 200 and html_text:
        if _SOLD_RE.search(_focused_text(html_text)):
            return "sold"
        body = _RIGHTS_RESERVED_RE.sub(" ", _strip_tags(html_text))
        if not _SOLD_RE.search(body):
            return "active"
        # Marker somewhere in the body but not on the page's own
        # title/headings — ambiguous (related-listings widget vs. an
        # un-headlined sold ribbon). Hand to the LLM fallback.
        return "unknown"
    return "unknown"


# ── Default fetch: reuse the scrapers' transport policy ───────────────

def _default_fetch(url: str, source: str) -> tuple[int, str, str]:
    """Single best-effort GET via the source's transport policy.

    Returns ``(status_code, final_url, text)``. Raises on transport
    error — the caller counts it as a fetch_error and moves on.
    ``retry_max`` is forced to 1: a probe is best-effort; a failed
    fetch is simply retried next nightly. Rate limits / jitter / UA
    pools from the policy still apply, so the probe is exactly as
    polite as the scraper for the same host.

    Playwright-policy sources (encuentra24) fall through to the httpx
    path — a probe doesn't drive a browser. If the host 403s plain
    httpx, the result classifies as ``unknown`` (never ``delisted``),
    which is the safe failure mode.
    """
    from pulpo.scrapers._policy import get_policy
    from pulpo.scrapers._runtime import polite_curl_cffi_get, polite_get

    policy = dataclasses.replace(get_policy(source), retry_max=1)
    if policy.transport == "curl_cffi":
        resp = polite_curl_cffi_get(
            url, source=source, policy=policy, timeout=15.0,
        )
        return resp.status_code, str(getattr(resp, "url", "") or url), resp.text

    import httpx

    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        resp = polite_get(client, url, source=source, policy=policy)
        return resp.status_code, str(resp.url), resp.text


# ── Default LLM fallback: DeepSeek, json_object, budget-capped ───────

def _make_default_llm_classify() -> t.Callable[[str], tuple[str, float]] | None:
    """Build the DeepSeek classifier, or None when the token / SDK is
    unavailable (the probe then ships ``unknown`` for ladder-5 pages)."""
    token = os.environ.get("DEEPSEEK_API_TOKEN")
    if not token:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(base_url="https://api.deepseek.com", api_key=token)

    def _classify(page_text: str) -> tuple[str, float]:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": page_text},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=50,
        )
        cost = 0.0
        usage = getattr(resp, "usage", None)
        if usage is not None:
            cost = _cost_usd(
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
            )
        try:
            parsed = json.loads((resp.choices[0].message.content or "").strip())
            state = str(parsed.get("state", "unknown"))
        except (json.JSONDecodeError, IndexError, AttributeError, TypeError):
            state = "unknown"
        if state not in _VALID_LLM_STATES:
            state = "unknown"
        return state, cost

    return _classify


def _llm_input(html_text: str | None) -> str:
    """``<title> + first 1500 chars of tag-stripped text`` per plan 012."""
    html = html_text or ""
    m = _TITLE_RE.search(html)
    title = _strip_tags(m.group(1)).strip() if m else ""
    body = " ".join(_strip_tags(html).split())[:1500]
    return f"{title}\n{body}".strip()


# ── The probe ─────────────────────────────────────────────────────────

def probe_missing_listings(
    ledger: dict[str, LedgerEntry],
    *,
    urls_by_key: t.Mapping[str, str],
    max_probes: int = 40,
    llm_budget: int = 20,
    now_iso: str,
    fetch: t.Callable[[str, str], tuple[int, str, str]] | None = None,
    llm_classify: t.Callable[[str], tuple[str, float]] | None = None,
) -> dict:
    """Probe up to ``max_probes`` entries whose existence_status is
    ``missing_recently`` or ``stale`` AND ``removal_reason is None``.

    Returns metrics ``{probed, sold, delisted, unknown, active,
    fetch_errors, skipped_no_url, llm_calls, cost_usd}`` and replaces
    the classified entries in ``ledger`` with copies carrying
    ``removal_reason`` / ``removal_detected_at`` (LedgerEntry is
    frozen, so mutation is by replacement). ``active`` results leave
    the entry un-classified on purpose — a missing-from-scrape but
    live page is ambiguous (scraper drift?) and worth re-checking.
    A terminal ``unknown`` IS written so one bad page can't eat a
    probe slot every night. ``fetch``/``llm_classify`` are injectable
    for tests; fetch attempts (successes + errors) are what consume
    the ``max_probes`` cap.
    """
    fetch = fetch or _default_fetch
    if llm_classify is None:
        llm_classify = _make_default_llm_classify()

    metrics = {
        "probed": 0, "sold": 0, "delisted": 0, "unknown": 0, "active": 0,
        "fetch_errors": 0, "skipped_no_url": 0, "llm_calls": 0,
        "cost_usd": 0.0,
    }

    candidates = [
        key for key, entry in ledger.items()
        if entry.existence_status in ("missing_recently", "stale")
        and entry.removal_reason is None
    ]
    # Most-recently-missing first: fresh transitions are the ones still
    # user-visible (carry-forward / recent), so their labels matter most.
    candidates.sort(
        key=lambda k: (ledger[k].missing_since or "", k), reverse=True,
    )

    attempts = 0
    for key in candidates:
        if attempts >= max_probes:
            break
        url = urls_by_key.get(key)
        if not url:
            metrics["skipped_no_url"] += 1
            continue
        source = key.split("|", 1)[0]
        attempts += 1
        try:
            status_code, final_url, text = fetch(url, source)
        except Exception:  # noqa: BLE001 — probe is best-effort by design
            metrics["fetch_errors"] += 1
            continue

        state = classify_page(status_code, final_url, url, text)
        if (
            state == "unknown"
            and llm_classify is not None
            and metrics["llm_calls"] < llm_budget
        ):
            metrics["llm_calls"] += 1
            try:
                state, cost = llm_classify(_llm_input(text))
                metrics["cost_usd"] = round(metrics["cost_usd"] + cost, 8)
            except Exception:  # noqa: BLE001 — LLM failure ⇒ keep "unknown"
                state = "unknown"
            if state not in _VALID_LLM_STATES:
                state = "unknown"

        metrics["probed"] += 1
        metrics[state] += 1
        if state in KNOWN_REMOVAL_REASONS:
            ledger[key] = dataclasses.replace(
                ledger[key],
                removal_reason=state,
                removal_detected_at=now_iso,
            )

    return metrics
