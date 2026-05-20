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

// Widget-author contract. Components take no props — they own their own
// state. AdminShell renders them inside a consistent card layout (title
// bar, back-to-grid link, body). Keep the surface narrow on purpose so
// each widget can iterate without touching the shell.
export type AdminWidget = {
  slug: string;                 // URL segment: `/admin/<slug>`
  label: string;                // grid card title + page title
  description: string;          // grid card subhead (one sentence)
  category: AdminWidgetCategory;
  Component: ComponentType<{}>;
};

export type AdminWidgetCategory = "comms" | "data" | "ops";

export const ADMIN_WIDGETS: readonly AdminWidget[] = [
  {
    slug: "newsletter",
    label: "Newsletter preview & send",
    description:
      "Compose a one-off newsletter from current listings — pick any filter combination, preview the cut, and send a test email to yourself.",
    category: "comms",
    Component: NewsletterWidget,
  },
] as const;

export function findWidget(slug: string | null | undefined): AdminWidget | null {
  if (!slug) return null;
  return ADMIN_WIDGETS.find((w) => w.slug === slug) ?? null;
}
