# Pulpo newsletter components

**Template version:** see `TEMPLATE_VERSION` in [`_common.py`](_common.py)
**Last updated:** see `LAST_UPDATED` in [`_common.py`](_common.py)

Every Pulpo newsletter is composed from the components in this package.
The canonical reference is the **Pulpo Pro General** template — the
weekly digest every Pro subscriber gets. Future newsletters (Pro
Welcome, Free Welcome, Free Weekly) build on top of these same
components.

## Latest revision (v4.3 · 2026-05-31)

Operator-driven polish + hard data-quality gate:

- **Photo-eligibility filter** — listings without a card-eligible
  photo (broker-logo source, text-overlay watermark, no `photo_urls`
  AND no `hero_photo_path`) are dropped from the picks pool BEFORE
  selection runs. Implemented in
  [`build_issue._listing_has_eligible_photo`](../build_issue.py).
  Operator policy: a listing can only appear in the newsletter if
  every field needed to render its card — photo included — is
  available. The v4.1 placeholder-band fallback is removed.
- **Chrome alignment** — header, hero, body, and footer all use 24px
  horizontal padding now. The v3 `.pad`/`.pad-sm` 36px classes are
  no longer used by chrome blocks (the header used to sit 12px
  further out than the body, producing a "floating" effect).
- **Brand marks** — three inline SVGs (header / spotlight / footer)
  are replaced with hosted PNG `<img>` tags pointing at
  `https://pulpo.club/assets/email-logo-32@2x.png`. Gmail iOS app,
  Outlook desktop, Yahoo, and AOL strip inline SVG; the hosted PNG
  renders everywhere.
- **Save button** — `&hearts;` gets the U+FE0E text variation
  selector appended so Apple Mail / iOS Mail render it as text, not
  a full-size red emoji. Both CTAs (Save + See-on-Pulpo) carry
  `white-space: nowrap` so the button content never wraps to 2 lines.

## Component map

| Module | Renders | Locked contract |
|---|---|---|
| [`_common`](_common.py) | `TEMPLATE_VERSION`, `CSS`, `escape`, `site_root_from_issue` | Shared helpers — bumped together when the template revs |
| [`brand`](brand.py) | Header strip + footer | Pulpo octopus + gold `PRO` pill + wordmark · Footer pill buttons (Change filters / Change cadence / Unsubscribe) |
| [`hero`](hero.py) | Hero block | Eyebrow + serif H1 + 2-sentence lede + filter chip |
| [`favorites`](favorites.py) | Saved-listings cards | Cream block · numeric headline · editorial summary · per-save cards · "Open all favorites →" |
| [`picks`](picks.py) | THE listing card + section intros | One `pick_card_html` for all 10 picks. Rank label unified: "Top deal · NN" (EN) / "Mejor oferta · NN" (ES) on all 10. Only background color (sage vs white) + pill chrome (forest-on-cream vs sand-on-grey) differ between top 3 and next 7. Title carries `text-wrap: balance` + post-escape `&nbsp;` widow guard to keep trailing short words glued to their preceding word. Section intros are big serif H2s |
| [`editorial`](editorial.py) | Market context + Weekly News Spotlight | Market = 3 numbered editorial mini-blocks (01/02/03) · Spotlight = Pulpo icon + eyebrow + "Reported by …" + H2 + body |
| [`personal`](personal.py) | "Pick up where you left off" | Up to 4 stacked cream action cards (saved / filter / browse / welcome) |
| [`paywall`](paywall.py) | Pro upsell band | Free-cohort only · forest green band · "Go Pro — $9.99/month →" CTA |

## Where the locked design lives

Open [`docs/design-references/pulpo-pro-general-en.html`](../../../docs/design-references/pulpo-pro-general-en.html)
in a browser — that's the snapshot the v4 design contract was built
against. Same file in [Spanish](../../../docs/design-references/pulpo-pro-general-es.html).
Both files are committed and updated whenever the template revs.

## How to add a new template

A new template usually swaps **2-3 blocks** of the General template
and keeps everything else (brand chrome, typography, color palette).

**Example — Pulpo Pro Welcome** (the first onboarding email when a
Free user upgrades):

1. Decide what changes from General. Probably:
   - Hero: a "Welcome to Pulpo Pro" variant (no scan-size lede)
   - Body: NO market context, NO picks, NO favorites
   - Adds: a "Get started" action card stack (set filter, save first
     listing, …)
   - Closes: same Your Pulpo + footer as General

2. Create `automation/newsletter/templates/pulpo_pro_welcome.py`:

   ```python
   from ..components import brand, personal
   from ..components._common import CSS, TEMPLATE_VERSION

   def render(issue):
       # compose body from imported components in the order you want
       ...
   ```

3. Register it in [`templates/__init__.py`](../templates/__init__.py):

   ```python
   from . import pulpo_pro_welcome

   TEMPLATES = {
       "pulpo-pro-general": pulpo_pro_general.render,
       "pulpo-pro-welcome": pulpo_pro_welcome.render,
   }
   ```

4. Point the admin widget at it. Edit
   [`web/app/admin/widgets/newsletter/NewsletterWidget.jsx`](../../../web/app/admin/widgets/newsletter/NewsletterWidget.jsx)
   and update the `template` field on the relevant `NEWSLETTERS` row:

   ```js
   { id: "pro-welcome", ..., template: "pulpo-pro-welcome",
     templateLabel: "Pulpo Pro Welcome", ... }
   ```

5. Add a snapshot test in `tests/newsletter/components/` so the
   design can't drift silently.

6. The CI alignment check in
   [`tests/newsletter/test_templates.py`](../../../tests/newsletter/test_templates.py)
   will fail if you forget step 3 or step 4 — every `template` id in
   the widget must be a key in the Python `TEMPLATES` registry.

## Why the components currently re-export

For the v4.2 architecture pass, the component modules **re-export**
the existing private helpers from `render_html.py` rather than owning
the implementation. The function bodies stay in one place to minimize
blast radius while the scaffolding beds in.

For template authors this is invisible: import paths and function
signatures are stable. A follow-up PR will lift the function bodies
out of `render_html.py` and into each component module so every
block becomes truly self-contained.

## Adding a new component

If you're building a template that needs a block that doesn't exist
yet, add it as a new module here. **Do not** duplicate code across
templates. If two templates would render the same block with minor
variations, parameterize the component.
