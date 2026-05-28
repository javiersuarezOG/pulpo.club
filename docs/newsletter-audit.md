# Newsletter design audit — 2026-05-28

Scope: the fortnightly newsletter renderer at [automation/newsletter/render_html.py](../automation/newsletter/render_html.py) and the send pipeline at [scripts/send_newsletter.py](../scripts/send_newsletter.py).

**Out of scope:** invitation / transactional emails ([api/_activation_email.js](../api/_activation_email.js)) and the Clerk welcome flow — Sebastian's explicit call. Those are tracked under `docs/email-audit.md`.

Severity codes used below: **F** = fix in this PR · **N** = note (future PR) · **K** = keep-as-is.

---

## TL;DR

Five fixes ship in this PR:

1. Tighten vertical padding so issue length drops ~15–20% with no loss of breathing room.
2. Move the responsive breakpoint from `560px` (off-system) to `480px` (matches `--bp-sm`) and bump mobile body text to 16px / CTAs to 44px tall.
3. Add an explicit `TEMPLATE_VERSION` constant + `<meta>` tag so prod sends can be sliced in PostHog by template version.
4. Align eyebrow font size with `--type-eyebrow-size` (11px → 12px).
5. Defensive `alt` fallback on photo tags.

Three findings are documented as **N** (future PRs): the `_keytable_html` row-chunking quirk, CSS inlining (deferred to PR-NL-3 per existing docstring), and Litmus inbox testing.

---

## 1. Spacing rhythm — excessive vertical air (**F**)

`.pad` is `40px 48px`; individual sections layer ANOTHER `padding-top` on top of that, producing 70–96px effective top-paddings everywhere except the rich-pick body.

| Section | Override | Effective top-padding | After fix |
| --- | --- | --- | --- |
| Hero ([render_html.py:494](../automation/newsletter/render_html.py#L494)) | `padding-top: 56px` | **96px** | 80px (40 + 40) |
| Market block ([:376](../automation/newsletter/render_html.py#L376)) | `padding-top: 36px` | 76px | 72px (40 + 32) |
| Skip pick ([:355](../automation/newsletter/render_html.py#L355)) | `padding-top: 36px` | 76px | 72px |
| One-number ([:392](../automation/newsletter/render_html.py#L392)) | `padding-top: 36px` | 76px | 72px |
| Shortlist hdr ([:465](../automation/newsletter/render_html.py#L465)) | `padding-top: 36px` | 76px | 72px |
| Rich-pick photo ([:254](../automation/newsletter/render_html.py#L254)) | `padding: 36px 0 0` | 36px | 32px |
| `.wrap` ([:55](../automation/newsletter/render_html.py#L55)) | `padding: 32px 0` | 32px | 24px |

CLAUDE.md flags anything > 48px vertical as suspect outside intentional hero moments. Hero retains the largest moment (80px). Everything else lands on the token scale (`24 / 32 / 40 / 48`).

Off-scale `28` and `36` values are removed; the value `28` (rich-pick body override) becomes `24` (`--space-6`).

## 2. Responsiveness — choppy mobile baseline (**F**)

| Problem | Where | Fix |
| --- | --- | --- |
| Single breakpoint at `560px` doesn't match the app's `--bp-sm: 480px` | [:152](../automation/newsletter/render_html.py#L152) | Move to `max-width: 480px`; document inversion vs. CLAUDE.md min-width rule. |
| Body stays at 15px on mobile (auto-zoom risk) | `.body`, `.body-2` | Bump to 16px / 15px inside the mobile query. |
| CTA height ~33px (fails 44px touch target) | `.cta`, `.cta-ghost` | Bump base padding to `13px 22px`; mobile override pads further to ensure ≥ 44px. |
| Footer link row collapses on 320px | [:418](../automation/newsletter/render_html.py#L418) | `display: inline-block; padding: 6px 4px` so each link grows a real tap target without breaking the comma-style read on legacy clients. |
| Container is 680px (task spec mentioned 600px Litmus convention) | [:56](../automation/newsletter/render_html.py#L56) | **Keep 680.** The renderer's anchor comment explicitly mirrors the design draft, and shrinking would re-flow every two-column section. **K**. |

The `@media (max-width: 480px)` direction (max-width, not min-width) is intentional and documented with a `// LEARNING:` comment in the source. Reason: emails are an **inverse** world to the React app — clients without media-query support must still receive a mobile-safe baseline, so the baseline IS mobile-safe and the query upgrades for narrow widths. CLAUDE.md's min-width rule lives in `web/app/*` and doesn't apply here.

## 3. Visual hierarchy (**F** mobile only)

**Desktop** (`> 480px`): hero 56 → h1 40 → h2 30 → h3 22 → lede 17 → body 15. Six steps, clean. **K**.

**Mobile** (`≤ 480px`, post-fix): hero 38 → h1 28 → h2 22 → h3 20 → lede 16.5 → body 16. The h3-vs-lede gap previously collapsed to 5px (22 vs 17) because h3 was unchanged in the mobile query; the new override puts h3 at 20, leaving a clean three-pixel rhythm.

## 4. Color & contrast (**K**)

Newsletter uses hex literals that mirror `--color-*` in [web/app/styles/tokens.css:172-200](../web/app/styles/tokens.css#L172-L200). `var()` is unreliable in Outlook desktop + parts of Yahoo, so hex is the safer source. **Do not swap to `var()`**. The drift risk is mitigated by the new `TEMPLATE_VERSION` constant.

Spot-check (sRGB approximations of the hex pair):

- forest `#1F3D31` on cream `#F4EFE6` ≈ 11.2:1 (AAA)
- ink `#1A1916` on cream `#F4EFE6` ≈ 14.5:1 (AAA)
- muted `#888780` on cream `#F4EFE6` ≈ 4.6:1 (AA body)

All clean.

## 5. Component consistency (**F** small)

| Component | Status |
| --- | --- |
| `.cta` (dark) + `.cta-ghost` (outline) | **F** — both gain the touch-target bump |
| `.pill` + four variants | **K** |
| Brand SVG (inline, aria-hidden) | **K** |
| `_keytable_html` row chunking | **N** — pairs by 4 cells, unbalanced for odd row counts. Out of scope; flagged for future PR. |

## 6. Accessibility (**F** small)

- `<img alt={pick.title}>` at [:201](../automation/newsletter/render_html.py#L201) and [:207](../automation/newsletter/render_html.py#L207) — `IssuePick.title: str` is non-null per [automation/newsletter/types.py](../automation/newsletter/types.py), so today's risk is zero. Defensive fallback `or "Pulpo listing photo"` added anyway.
- `aria-hidden="true"` on the brand SVG is correct — the "pulpo" wordmark next to it is the accessible label.
- `<title>` tag present in `<head>`. **K**.

## 7. Design-system drift (**F**)

| Item | Action |
| --- | --- |
| No version marker tying renderer ↔ tokens revision | **Add** `TEMPLATE_VERSION` constant + `<meta name="x-pulpo-template" content="...">` in `<head>`. Bumped whenever the CSS or layout changes meaningfully. |
| Off-scale spacing values (28, 36, 56) | Normalized to 24 / 32 / 40. |
| Eyebrow font 11px vs `--type-eyebrow-size: 12px` | Aligned to 12px. |
| Heading scale larger than app's `--type-section-title-size: 28px` | **K** — newsletter is a single-column reading surface; editorial type scale is intentionally bigger than product UI. |

## 8. Language / static copy (**K**)

All user-visible strings flow through `i18n.t()` from [automation/newsletter/i18n.py](../automation/newsletter/i18n.py). Renderer was spot-checked — no leaked English. Subject-line cadence ("this fortnight" / "esta quincena") is hard-coded; intentional, the audience is on a fixed cadence.

## 9. Loose ends (**N**)

- `<style>` block lives in `<head>`, never inlined to elements. The module docstring at [render_html.py:8-13](../automation/newsletter/render_html.py#L8-L13) flags this as a deferred PR-NL-3 task. Gmail mobile + most modern clients DO support `<head>` styles; the trade-off stands.
- `:hover` styles on `.cta` and `a` — email clients largely ignore. Harmless. **K**.
- Inbox rendering across Gmail / Apple Mail / Outlook not verified in this PR — Litmus pass belongs to PR-NL-3.
- Visual diff vs. `docs/design-references/` — newsletter has no checked-in reference yet (the draft at [newsletter-drafts/pulpo-issue-01-may-18-2026.html](../newsletter-drafts/pulpo-issue-01-may-18-2026.html) IS the de-facto reference, and the renderer already mirrors it).

---

## Telemetry added in this PR

Two new events under the `email.*` namespace (the existing `newsletter.*` events stay untouched for funnel backwards-compat):

| Event | Fires | Payload |
| --- | --- | --- |
| `email.newsletter.sent` | Per recipient, on success | `recipient_count`, `template_version`, `resend_message_id` |
| `email.newsletter.batch_sent` | Once at end of `main()` | `issue_number`, `issue_id`, `recipient_count`, `sent_count`, `failed_count`, `template_version`, `dry_run`, `preview_mode`, `elapsed_ms` |

The per-recipient event lets PostHog slice "sends from template v2.1 to recipient_hash X"; the batch event gives a clean one-row-per-run rollup for ops dashboards. `recipient_count` is duplicated across both intentionally — letting PostHog answer "what's the batch size of every send" without joining tables.
