#!/usr/bin/env python3
"""Agent-driven new-source onboarding — Train B of the scraper-agent plan.

Wires the real ``propose`` (Claude via the Anthropic SDK) and the
live/offline ``evaluate`` on top of the ``automation.scraper_agent`` harness,
so an agent can author a ``SkeletonScraper`` for a new source, iterate against
the acceptance gate, and stop when it passes:

    propose (Claude writes a scraper module)
      -> sandbox.apply  (only pulpo/scrapers/<slug>.py)
      -> evaluate        (lab_run + field_audit -> EvalReport.fitness)
      -> keep best / discard regressions
      -> repeat until passed | budget | max_iters

Why onboarding is the honest first target (see the plan): a brand-new source
has no prior fixture, so a ``--live`` evaluate runs on genuinely
representative data — there's no stale-fixture trap the way there is for
repair. The agent fills the declarative ``SkeletonConfig`` (95% of authoring),
overriding ``_extract_detail`` only for quirks.

The proposer is provider-agnostic. It defaults to **DeepSeek** — Pulpo already
pays for it (DEEPSEEK_API_TOKEN, used by enrichment) and it's ~20x cheaper than
Opus; the strict acceptance gate compensates for a weaker model by iterating a
few more times. Pass ``--provider anthropic`` for the harder sites.

Usage:

    # Real run (default DeepSeek; needs DEEPSEEK_API_TOKEN + network):
    python3 scripts/scraper_onboard.py --slug acme --url https://acme.com/ventas --live

    # Use Claude instead (needs ANTHROPIC_API_KEY):
    python3 scripts/scraper_onboard.py --slug acme --url https://acme.com/ventas --live --provider anthropic

    # Show the first-iteration prompt and exit, no API call, no edits:
    python3 scripts/scraper_onboard.py --slug acme --url https://acme.com/ventas --dry-run

On success the winning scraper is left in the worktree (committed in the
sandbox sense) and a draft PR body is written next to it — a human reviews and
opens the PR. This script never opens PRs or merges.

NOTE: each ``--live`` evaluate currently re-fetches the source. The plan's
"fetch once, then iterate parsing offline against cached HTML" optimization is
a follow-up (B2); it cuts network + latency but does not change correctness.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.scraper_agent import (  # noqa: E402
    Budget,
    ProposedEdit,
    Sandbox,
    agent_loop,
    evaluate_scraper,
)
from automation.scraper_agent.eval import EvalReport  # noqa: E402
from automation.scraper_agent.loop import LoopContext  # noqa: E402

# Provider config. DeepSeek is the DEFAULT: Pulpo already pays for it
# (DEEPSEEK_API_TOKEN, used by the enrichment pipeline) and it's ~20x cheaper
# than Opus. The autoresearch design tolerates a weaker proposer because the
# acceptance gate filters bad output — a cheap model just iterates a few more
# times against the eval. Anthropic stays available for the harder sites.
PROVIDERS = {
    "deepseek": {
        "default_model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_TOKEN",
        "base_url": "https://api.deepseek.com",
    },
    "anthropic": {
        "default_model": "claude-opus-4-8",
        "key_env": "ANTHROPIC_API_KEY",
        "base_url": None,
    },
}
DEFAULT_PROVIDER = os.environ.get("SCRAPER_ONBOARD_PROVIDER", "deepseek")

# Onboarding should clear the product's min-shelf bar, not just parse a couple
# of listings. field_audit's hard-gate is the quality gate; this is the volume
# floor (matches the min-shelf-listings rule).
DEFAULT_MIN_RANKED = 10


# ── site probe (so the proposer reads the structure, not guesses it) ──
#
# The single biggest lever for onboarding quality: fetch the live catalog +
# one sample detail page + the sitemap ONCE, and put them in the prompt. The
# model then picks extract_strategy / detail_url_pattern by reading the markup
# instead of guessing from listing counts. A JS-rendered catalog (detail URLs
# absent from the HTML) becomes obvious, and the sitemap's <loc> entries hand
# the model the detail-URL shape directly.

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")
# URL fragments that suggest a listing-detail page.
_DETAIL_HINT_RE = re.compile(
    r"(ficha|propiedad|inmueble|listing|property|detalle|aviso|anuncio|"
    r"venta|vende|/p/|/id/)", re.IGNORECASE)
# Utility / navigation pages that also contain listing-ish words but are NOT
# listings (e.g. "publicar-propiedad" = a 'post your property' page). These
# must be excluded or the probe shows the model a junk page and it authors a
# wrong detail_url_pattern — the exact bug the bienesonline run hit.
_NAV_DENY_RE = re.compile(
    r"(publicar|dashboard|login|logout|registr|cuenta|account|contacto|contact|"
    r"about|nosotros|quienes|sell\b|vender|favorit|ayuda|help|terminos|privac|"
    r"sitemap|/tag/|/categoria/|/blog/|noticia|facebook|twitter|instagram|"
    r"whatsapp|mailto:|tel:|javascript:)", re.IGNORECASE)


def _http_get(url: str, *, cap: int = 200_000, timeout: float = 20.0) -> Optional[str]:
    try:
        import httpx
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=timeout,
                      follow_redirects=True)
        if r.status_code >= 400:
            return None
        return r.text[:cap]
    except Exception:  # noqa: BLE001 — a probe failure must not abort onboarding
        return None


def _clean_html(html: str, *, cap: int) -> str:
    """Drop non-JSON-LD <script>, <style>, and comments so the budget is spent
    on structural markup (links, JSON-LD, og: tags), then truncate."""
    html = re.sub(r"<script(?![^>]*ld\+json)\b[^>]*>.*?</script>", "", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"[ \t]+\n", "\n", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()[:cap]


def _detail_candidates(catalog_url: str, raw_html: str) -> list[str]:
    """Listing-detail URLs discovered in the catalog HTML: hint-matching,
    nav-denylisted, deduped, for-sale (venta) preferred. Real listings recur;
    nav links are filtered, so the head of this list is a good sample."""
    seen: list[str] = []
    for href in re.findall(r'href="([^"#]+)"', raw_html):
        full = urljoin(catalog_url, href)
        if full == catalog_url or full in seen:
            continue
        if not _DETAIL_HINT_RE.search(full) or _NAV_DENY_RE.search(full):
            continue
        seen.append(full)
    venta = [u for u in seen if re.search(r"venta|vende|for-sale", u, re.IGNORECASE)]
    return (venta or seen)[:6]


def _probe_site(catalog_url: str) -> dict:
    """Fetch catalog + sample detail URLs + one detail page + sitemap <loc>s.
    Best-effort: any field may be None/empty; onboarding proceeds regardless."""
    out: dict = {"catalog_html": None, "detail_url": None, "detail_html": None,
                 "sample_detail_urls": [], "sitemap_locs": []}
    raw = _http_get(catalog_url)
    if raw:
        out["catalog_html"] = _clean_html(raw, cap=9000)
        out["sample_detail_urls"] = _detail_candidates(catalog_url, raw)
        if out["sample_detail_urls"]:
            best = out["sample_detail_urls"][0]
            draw = _http_get(best)
            if draw:
                out["detail_url"] = best
                out["detail_html"] = _clean_html(draw, cap=9000)
    base = "{0.scheme}://{0.netloc}".format(urlsplit(catalog_url))
    for sm in ("/sitemap.xml", "/sitemap_index.xml"):
        smraw = _http_get(base + sm, cap=120_000)
        if smraw and "<loc>" in smraw:
            out["sitemap_locs"] = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", smraw)[:40]
            break
    return out


def _render_probe(probe: Optional[dict]) -> str:
    """Render the probe into the prompt. Empty when no probe was run."""
    if not probe:
        return ""
    catalog = probe.get("catalog_html") or "<catalog fetch failed>"
    locs = probe.get("sitemap_locs") or []
    sitemap = "\n".join(locs) if locs else "<no sitemap.xml found>"
    samples = probe.get("sample_detail_urls") or []
    sample_block = "\n".join(samples) if samples else "<none found in the catalog HTML>"
    detail_url = probe.get("detail_url") or "<no detail page discovered from the catalog>"
    detail = probe.get("detail_html") or "<none>"
    return f"""
What the live site actually looks like — READ THIS to choose extract_strategy
and detail_url_pattern (don't guess):

REAL detail-page URLs found in the catalog — derive detail_url_pattern from
these EXACT examples (do NOT invent a path like /inmueble/ that isn't here):
{sample_block}

Catalog HTML (cleaned + truncated). If the listing links are JS anchors
(href="#...") rather than real detail URLs, the catalog is JS-rendered — use
extract_strategy="sitemap" and the <loc> URLs below:
```html
{catalog}
```

sitemap.xml <loc> sample (a detail-URL source if the catalog is JS-rendered):
{sitemap}

Sample detail page ({detail_url}) — look for application/ld+json (use
"detail_jsonld") or og: meta tags (use "detail_og_meta"), and the exact price
/ area text to match:
```html
{detail}
```
"""


# ── prompt construction ──────────────────────────────────────────────

_SKELETON_REFERENCE = """\
SkeletonConfig (pulpo.scrapers._skeleton_helper) — the declarative surface.
Key fields:
  slug: str                      # MUST equal the target slug
  base_url: str
  list_url: str                  # the for-sale catalog URL (apply site filters here)
  page_param: str = "page"       # pagination query param; ignored for sitemap/static_urls
  max_pages: int = 50
  extract_strategy: one of
      "detail_jsonld"  (default) — walk catalog -> detail URLs -> parse JSON-LD
      "detail_og_meta"           — same walk, parse og: meta + og_price/area regex
      "sitemap"                  — enumerate <loc> from sitemap_url -> JSON-LD
      "static_urls"              — iterate a hardcoded static_urls tuple
  detail_url_pattern: str        # regex finding detail-page hrefs in catalog HTML
  jsonld_schema_types: tuple     # accepted @type values (case-insensitive)
  og_price_patterns / og_area_patterns: tuple[str, ...]   # for detail_og_meta
  sitemap_url / sitemap_url_filter                        # for sitemap
  static_urls: tuple             # for static_urls
  force_vacation_gate: bool = True   # set False for broad national for-sale sources
Override hooks (subclass methods) for quirks:
  _extract_detail(self, body, url, *, strategy) -> Optional[dict]
  _extract_detail_urls_from_catalog_page(self, body, page_num) -> list[str]
  _post_finalize_filter(self, record) -> bool

A record dict should carry at least: source, source_id, url, title, description,
price_usd, area_m2, photo_urls, property_type, location_text.

The module MUST end with these two side effects, verbatim shape:
    register(SOURCES, "<slug>", <Class>())
    def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
        return <Class>(offline=offline).crawl(limit)
"""

_EXEMPLAR = '''\
from __future__ import annotations
from typing import Optional
from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper, _parse_number as _to_float
from pulpo.scrapers.lib import extract_og


class XitiosScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="xitios",
        base_url="https://www.xitios.com.sv",
        list_url="https://www.xitios.com.sv/propiedades/buscar?categoria%5B%5D=VEN&tipo%5B%5D=RAN",
        page_param="page",
        detail_url_pattern=r'href="((?:https?://www\\.xitios\\.com\\.sv)?/propiedad/detalles/[a-z0-9\\-]+)"',
        extract_strategy="detail_og_meta",
        og_price_patterns=(r"US\\$\\s*([\\d.,]+)", r"\\$\\s*([\\d.,]+)"),
        og_area_patterns=(r"([\\d.,]+)\\s*(?:m\\s*[²2])", r"([\\d.,]+)\\s*varas?\\s*cuadradas?"),
        max_pages=100,
        force_vacation_gate=False,
    )

    def _extract_detail(self, body: str, url: str, *, strategy: str) -> Optional[dict]:
        og = extract_og(body) or {}
        if not og:
            return None
        # ... per-source field extraction ...
        return {"source": self.CONFIG.slug, "source_id": url.rsplit("/", 1)[-1],
                "url": url, "title": og.get("title") or "", "description": og.get("description") or "",
                "price_usd": None, "area_m2": None, "photo_urls": [], "property_type": None,
                "location_text": ""}


register(SOURCES, "xitios", XitiosScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return XitiosScraper(offline=offline).crawl(limit)
'''


def _eval_feedback(report: EvalReport) -> str:
    """Render the last EvalReport as actionable feedback for the next prompt."""
    if not report.ok:
        return (
            f"The funnel FAILED to run. Error:\n{report.error or '<none>'}\n"
            "Most likely the fetch returned nothing (wrong list_url, wrong "
            "detail_url_pattern, or the site needs a different strategy), or "
            "the module has a Python error."
        )
    gates = ", ".join(f"{k}={int(v * 100)}%" for k, v in report.hard_gate_pct.items())
    fails = ", ".join(f"{k}={n}" for k, n in sorted(report.failures.items())) or "none"
    return (
        f"fetched={report.raw_count} normalized={report.normalized_count} "
        f"validated={report.validation} ranked={report.ranked_count}\n"
        f"hard-gate coverage: {gates}  (need >= 85% on every gate)\n"
        f"drop reasons: {fails}\n"
        "If ranked is 0 with fetched>0, normalize/validate is rejecting the "
        "records — check price_usd parsing and that property_type/location are "
        "populated. If fetched is 0, the catalog walk or detail_url_pattern is "
        "wrong."
    )


def build_onboard_prompt(ctx: LoopContext, *, source_url: str,
                         probe: Optional[dict] = None) -> str:
    """Construct the per-iteration prompt for the model. ``probe`` (from
    :func:`_probe_site`) injects the live catalog/detail/sitemap so the model
    reads the structure instead of guessing."""
    if ctx.iteration <= 1 and ctx.current_source is None:
        situation = (
            "There is NO scraper for this source yet. Author one from scratch."
        )
    else:
        situation = (
            "A previous attempt exists below. Improve it based on the eval "
            "feedback — change selectors / strategy / regex; keep what worked."
        )
    current = ctx.current_source or "<none yet>"
    feedback = _eval_feedback(ctx.last)
    return f"""You are onboarding a new real-estate FOR-SALE source to Pulpo (a \
Salvadoran land/property aggregator). Write a Python scraper module that the \
pipeline can run.

Target slug: {ctx.slug}
Source URL: {source_url}

{situation}

{_SKELETON_REFERENCE}

Canonical output shape (a real skeleton-based scraper — match this structure):
```python
{_EXEMPLAR}
```
{_render_probe(probe)}
Latest eval feedback (iteration {ctx.iteration}):
{feedback}

Current module (pulpo/scrapers/{ctx.slug}.py):
```python
{current}
```

Constraints:
- Only output ONE complete Python module for pulpo/scrapers/{ctx.slug}.py.
- It MUST define a SkeletonScraper subclass with CONFIG.slug == "{ctx.slug}",
  call register(SOURCES, "{ctx.slug}", <Class>()), and define crawl().
- Filter the list_url to FOR SALE listings (venta), not rentals.
- Do not import or edit any other module under pulpo/.

Reply with EXACTLY:
## Rationale
<2-4 sentences: what strategy you chose and what you changed vs the feedback>

## Module
```python
<the complete module source>
```
"""


# ── response parsing ─────────────────────────────────────────────────

_PY_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
_RATIONALE_RE = re.compile(r"##\s*Rationale\s*\n(.*?)(?:\n##\s|\Z)", re.DOTALL | re.IGNORECASE)


def parse_proposal(text: str) -> Optional[tuple[str, str]]:
    """Extract ``(module_source, rationale)`` from a model reply, or None if no
    code block is present (treated as 'agent declined')."""
    blocks = _PY_BLOCK_RE.findall(text)
    if not blocks:
        return None
    # The module is the largest fenced python block (the exemplar in the prompt
    # is not echoed; the model's own block is the answer).
    module = max(blocks, key=len).strip() + "\n"
    rat_match = _RATIONALE_RE.search(text)
    rationale = (rat_match.group(1).strip() if rat_match else "").splitlines()
    rationale_line = rationale[0] if rationale else "(no rationale given)"
    return module, rationale_line


# ── model calls (provider-agnostic) ──────────────────────────────────
#
# Each returns ``(text, usage_dict)`` where usage_dict uses the budget's field
# names (input_tokens / output_tokens / cache_*), so budget.charge_usage works
# uniformly regardless of provider.

def _call_anthropic(prompt: str, *, model: str) -> tuple[str, dict]:
    """One Claude call. The repo pins anthropic 0.42.x (no named
    ``thinking`` / ``output_config`` params), so we route adaptive-thinking +
    high-effort through ``extra_body`` and fall back to the basic call shape
    ``scraper_autorepair.py`` already uses on this SDK if that fails."""
    from anthropic import Anthropic

    client = Anthropic()
    messages = [{"role": "user", "content": prompt}]
    try:
        msg = client.messages.create(
            model=model, max_tokens=12000, messages=messages,
            extra_body={"thinking": {"type": "adaptive"},
                        "output_config": {"effort": "high"}},
        )
    except Exception:  # noqa: BLE001 — enhanced call is best-effort; basic call's errors propagate
        msg = client.messages.create(model=model, max_tokens=12000, messages=messages)
    text = "\n".join(b.text for b in msg.content if getattr(b, "text", ""))
    u = msg.usage
    return text or "<empty>", {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


def _call_deepseek(prompt: str, *, model: str) -> tuple[str, dict]:
    """One DeepSeek call via the OpenAI-compatible SDK — same base_url + token
    Pulpo's enrichment pipeline uses. ``prompt_tokens`` is billed in full
    (conservative for a budget guard; ignores the small cache-hit discount)."""
    from openai import OpenAI

    cfg = PROVIDERS["deepseek"]
    client = OpenAI(base_url=cfg["base_url"], api_key=os.environ[cfg["key_env"]])
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8000,
        temperature=0.2,
    )
    text = resp.choices[0].message.content or "<empty>"
    u = resp.usage
    return text, {
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
    }


def _call_model(prompt: str, *, provider: str, model: str) -> tuple[str, dict]:
    if provider == "anthropic":
        return _call_anthropic(prompt, model=model)
    if provider == "deepseek":
        return _call_deepseek(prompt, model=model)
    raise ValueError(f"unknown provider {provider!r}")


def make_propose(source_url: str, *, provider: str = DEFAULT_PROVIDER, model: Optional[str] = None):
    """Build the real ``propose`` callable. ``provider`` picks the LLM backend
    (default DeepSeek); ``model`` defaults to that provider's default model.
    The live site is probed ONCE (catalog + detail + sitemap) and the result is
    reused across iterations so the model authors against real markup."""
    model = model or PROVIDERS[provider]["default_model"]
    cache: dict = {}

    def propose(ctx: LoopContext) -> Optional[ProposedEdit]:
        if "probe" not in cache:
            cache["probe"] = _probe_site(source_url)
        prompt = build_onboard_prompt(ctx, source_url=source_url, probe=cache["probe"])
        text, usage = _call_model(prompt, provider=provider, model=model)
        parsed = parse_proposal(text)
        if parsed is None:
            return None
        module, rationale = parsed
        return ProposedEdit(content=module, rationale=rationale, model=model, usage=usage)

    return propose


def make_evaluate(slug: str, *, live: bool, limit: int, min_ranked: int):
    """Build the ``evaluate`` callable. ``live=True`` fetches the source;
    ``live=False`` runs against offline fixtures (only useful once they exist)."""

    def evaluate() -> EvalReport:
        return evaluate_scraper(slug, live=live, limit=limit, min_ranked=min_ranked)

    return evaluate


# ── PR body ──────────────────────────────────────────────────────────

def render_pr_body(slug: str, source_url: str, result) -> str:
    best = result.best
    gates = "\n".join(
        f"  - `{k}`: {int(v * 100)}%" for k, v in best.hard_gate_pct.items()
    )
    return f"""## New source: `{slug}` ({source_url})

Authored by the scraper-agent onboarding loop ({result.iterations} iteration(s),
stop_reason=`{result.stop_reason}`, {result.budget_summary}).

**Acceptance (field_audit hard gates, need ≥85%):**
{gates}

- fetched/ranked: {best.raw_count} → {best.ranked_count}
- validation: {best.validation}

### Reviewer checklist
- [ ] Eyeball 3 records for correctness (not just count > 0).
- [ ] `PULPO_OFFLINE=1 pytest tests/scrapers/test_{slug}.py` (add fixtures/test — PR-AR-B2).
- [ ] Add the `_policy.py` entry + `source_watchdog_floors.py` floor.
- [ ] Confirm dedup overlap vs existing sources is acceptable.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""


# ── orchestration ────────────────────────────────────────────────────

def run_onboarding(
    slug: str,
    source_url: str,
    *,
    propose,
    live: bool,
    max_iters: int,
    budget_usd: float,
    limit: int = 50,
    min_ranked: int = DEFAULT_MIN_RANKED,
    log=print,
):
    """Run the onboarding loop and, on success, leave the scraper on disk +
    return ``(LoopResult, pr_body_or_None)``."""
    evaluate = make_evaluate(slug, live=live, limit=limit, min_ranked=min_ranked)
    with Sandbox(REPO, slug) as sb:
        result = agent_loop(
            slug, propose=propose, evaluate=evaluate, sandbox=sb,
            budget=Budget(limit_usd=budget_usd), kind="onboard",
            max_iters=max_iters, log=log,
        )
        pr_body = None
        if result.passed:
            sb.commit()
            pr_body = render_pr_body(slug, source_url, result)
            (REPO / f"PR_BODY_{slug}.md").write_text(pr_body, encoding="utf-8")
    return result, pr_body


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Agent-driven new-source onboarding.")
    p.add_argument("--slug", required=True, help="Source slug (a-z0-9_).")
    p.add_argument("--url", required=True, help="For-sale catalog URL of the source.")
    p.add_argument("--max-iters", type=int, default=6)
    p.add_argument("--budget", type=float, default=2.0, help="Per-run USD ceiling.")
    p.add_argument("--provider", choices=sorted(PROVIDERS), default=DEFAULT_PROVIDER,
                   help="LLM backend for the proposer (default: deepseek — already paid for, cheap).")
    p.add_argument("--model", default=None,
                   help="Override the provider's default model.")
    p.add_argument("--min-ranked", type=int, default=DEFAULT_MIN_RANKED)
    p.add_argument("--limit", type=int, default=50, help="Listings to fetch per eval.")
    p.add_argument("--live", action="store_true",
                   help="Fetch the source each eval (required for a real new source).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the first-iteration prompt and exit. No API call, no edits.")
    args = p.parse_args(argv)

    if not re.fullmatch(r"[a-z0-9_]+", args.slug):
        print(f"error: --slug must be [a-z0-9_]+, got {args.slug!r}")
        return 2

    if args.dry_run:
        ctx = LoopContext(slug=args.slug, kind="onboard", iteration=1,
                          current_source=None,
                          best=evaluate_scraper(args.slug, live=False),
                          last=evaluate_scraper(args.slug, live=False), history=[])
        print(build_onboard_prompt(ctx, source_url=args.url))
        return 0

    key_env = PROVIDERS[args.provider]["key_env"]
    if not os.environ.get(key_env):
        print(f"error: {key_env} unset for --provider {args.provider} "
              f"(use --dry-run to preview the prompt, or pick another --provider).")
        return 2
    if not args.live:
        print("warning: --live not set; a brand-new source has no offline "
              "fixtures, so the eval cannot make progress. Pass --live for a "
              "real onboarding run.")

    propose = make_propose(args.url, provider=args.provider, model=args.model)
    result, _ = run_onboarding(
        args.slug, args.url, propose=propose, live=args.live,
        max_iters=args.max_iters, budget_usd=args.budget, limit=args.limit,
        min_ranked=args.min_ranked,
    )
    print("\n" + result.summary())
    if result.passed:
        print(f"\n✅ scraper left at pulpo/scrapers/{args.slug}.py — review & PR.")
        print(f"   draft PR body: PR_BODY_{args.slug}.md")
        return 0
    print("\n❌ did not reach the acceptance gate — nothing committed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
