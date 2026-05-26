// Admin widget registry — the single source of truth for everything
// that renders under `/admin/<slug>`.
//
// Adding a new widget:
//   1. Drop your component at `web/app/admin/widgets/<slug>/<Slug>Widget.jsx`.
//   2. Append a row to ADMIN_WIDGETS below.
//   3. Done. AdminShell handles routing, the grid card, and the title bar.
//
// No central if/else, no router patch, no API allow-list per widget.
// The registry pattern keeps `/admin` additive — each new tool is a
// folder + one line.

import type { ComponentType } from "react";
import { NewsletterWidget } from "./newsletter/NewsletterWidget.jsx";
import { SourcesHealthWidget, SourcesHealthPreview } from "./sources/SourcesHealthWidget.jsx";
import { IgReviewWidget, IgReviewPreview } from "./ig-review/IgReviewWidget.jsx";

// Widget-author contract. Components take no props — they own their own
// state. AdminShell renders them inside a consistent card layout (title
// bar, back-to-grid link, body). Keep the surface narrow on purpose so
// each widget can iterate without touching the shell.
//
// `Preview` is optional. When provided, AdminShell renders it on the
// /admin grid card *instead of* the static `description` — giving the
// widget a live at-a-glance summary (counts, recency, status) before
// the user clicks in. Widgets without a Preview still work; they keep
// the description fallback. Keep Preview output narrow — it shows
// inside a card that's roughly 280px wide.
export type AdminWidget = {
  slug: string;                 // URL segment: `/admin/<slug>`
  label: string;                // grid card title + page title
  description: string;          // grid card subhead (one sentence) — fallback when no Preview
  category: AdminWidgetCategory;
  Component: ComponentType<{}>;
  Preview?: ComponentType<{}>;
};

export type AdminWidgetCategory = "comms" | "data" | "ops";

export const ADMIN_WIDGETS: readonly AdminWidget[] = [
  {
    slug: "newsletter",
    label: "Newsletter preview",
    description:
      "Trigger the production newsletter pipeline to send three cohort variants (anonymous, free, pro) of the next issue to any email. Routes through GitHub Actions — ~30–60s lag, real Resend send.",
    category: "comms",
    Component: NewsletterWidget,
  },
  {
    slug: "sources",
    label: "Source health",
    description:
      "Per-scraper card with status, listing count, supply-mix pies, and a live fix-state banner (recently fixed / open PR / auto-repair running / shadow suggestion / needs human) for red sources.",
    category: "ops",
    Component: SourcesHealthWidget,
    Preview: SourcesHealthPreview,
  },
  {
    slug: "ig-review",
    label: "IG batch review",
    description:
      "Read-only review of the 14-post IG drop assembled by automation/ig_queue_builder.py. Approve/skip decisions persist in local storage until PR-4 wires the workflow_dispatch submission flow.",
    category: "comms",
    Component: IgReviewWidget,
    Preview: IgReviewPreview,
  },
] as const;

export function findWidget(slug: string | null | undefined): AdminWidget | null {
  if (!slug) return null;
  return ADMIN_WIDGETS.find((w) => w.slug === slug) ?? null;
}
