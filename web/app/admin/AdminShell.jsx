// AdminShell — the `/admin` hub layout.
//
// Renders one of two things:
//   - `/admin`             → widget grid (one card per ADMIN_WIDGETS entry)
//   - `/admin/<slug>`      → the matching widget's Component, wrapped in a
//                            consistent header with back-to-grid link
//
// Auth: NONE. Page is publicly reachable; discoverability is the only
// gate (robots-blocked, no nav link, no marketing surface). Widget
// backends carry their own guardrails (e.g. 5-recipient cap on the
// newsletter send endpoint) so the blast radius is bounded even if the
// URL leaks.
//
// Widgets that need state/coordination across pages can use sessionStorage
// or React context — this shell intentionally passes nothing in.

import React, { useEffect } from "react";
import { ADMIN_WIDGETS, findWidget } from "./widgets/registry.ts";

const SHELL_STYLES = `
.page-admin {
  max-width: 960px;
  margin: 0 auto;
  padding: 32px var(--section-pad, 24px) 96px;
  color: var(--ink);
  font-family: var(--font-sans);
}
.page-admin .admin-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin: 0 0 8px;
}
.page-admin h1.admin-title {
  font-family: var(--font-sans);
  font-size: 36px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0 0 12px;
  color: var(--ink);
}
.page-admin .admin-subhead {
  font-size: 15px;
  line-height: 22px;
  color: var(--ink-2);
  margin: 0 0 24px;
  max-width: 56ch;
}
.page-admin .admin-banner {
  border: 1px solid var(--line-2);
  background: var(--paper-2);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 20px;
  color: var(--ink-2);
  margin: 0 0 32px;
}
.page-admin .admin-banner strong { color: var(--ink); }

.page-admin .widget-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}
@media (min-width: 640px) {
  .page-admin .widget-grid { grid-template-columns: 1fr 1fr; }
}
.page-admin .widget-card {
  display: block;
  text-align: left;
  width: 100%;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: border-color 120ms ease, transform 120ms ease;
  color: inherit;
  font: inherit;
}
.page-admin .widget-card:hover { border-color: var(--accent); }
.page-admin .widget-card .wc-category {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin: 0 0 8px;
}
.page-admin .widget-card .wc-label {
  font-size: 17px;
  line-height: 22px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--ink);
}
.page-admin .widget-card .wc-desc {
  font-size: 14px;
  line-height: 20px;
  color: var(--ink-2);
  margin: 0;
}

.page-admin .widget-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-size: 13px;
  color: var(--ink-3);
  cursor: pointer;
  margin: 0 0 12px;
}
.page-admin .widget-back:hover { color: var(--accent); }

.page-admin .widget-empty {
  border: 1px dashed var(--line-2);
  border-radius: 12px;
  padding: 32px;
  text-align: center;
  color: var(--ink-3);
  font-size: 14px;
}
`;

export function AdminPage({ app }) {
  const adminWidget = app?.routeParams?.adminWidget ?? null;
  const widget = findWidget(adminWidget);

  // Belt-and-braces noindex — `robots.txt` already disallows /admin
  // for compliant crawlers; this meta tag covers anyone who skips it.
  // Synchronously set on mount so the head reflects admin even if the
  // page is the cold-load entry.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const prevTitle = document.title;
    document.title = widget ? `${widget.label} · Pulpo admin` : "Pulpo admin";
    let robots = document.querySelector('meta[name="robots"]');
    const createdRobots = !robots;
    if (!robots) {
      robots = document.createElement("meta");
      robots.setAttribute("name", "robots");
      document.head.appendChild(robots);
    }
    const prevRobots = robots.getAttribute("content");
    robots.setAttribute("content", "noindex, nofollow");
    return () => {
      document.title = prevTitle;
      if (createdRobots) {
        robots.remove();
      } else if (prevRobots != null) {
        robots.setAttribute("content", prevRobots);
      }
    };
  }, [widget?.slug, widget?.label]);

  // The widget grid lives at /admin; clicking a card navigates to
  // /admin/<slug>. We use app.go() if the host wires it, otherwise fall
  // back to history.pushState. The shell stays usable even if the host
  // hasn't routed admin sub-pages yet.
  const goToWidget = (slug) => {
    if (app && typeof app.go === "function") {
      app.go("admin", { adminWidget: slug });
      return;
    }
    if (typeof window !== "undefined") {
      window.history.pushState({}, "", `/admin/${slug}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  };

  const goToGrid = () => {
    if (app && typeof app.go === "function") {
      app.go("admin", { adminWidget: null });
      return;
    }
    if (typeof window !== "undefined") {
      window.history.pushState({}, "", "/admin");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  };

  useEffect(() => {
    // Re-render is driven by app routeParams when host wires it. The
    // popstate dispatch above triggers the app's existing listener.
  }, []);

  return (
    <>
      <style>{SHELL_STYLES}</style>
      <main className="page-admin" aria-labelledby="admin-title">
        <p className="admin-eyebrow">Pulpo · internal tools</p>
        {widget ? (
          <>
            <button type="button" className="widget-back" onClick={goToGrid} aria-label="Back to admin home"> {/* i18n-allow: admin-only, internal tools, EN-only */}
              ← Back to admin home
            </button>
            <h1 id="admin-title" className="admin-title">{widget.label}</h1>
            <p className="admin-subhead">{widget.description}</p>
            <div className="admin-banner">
              <strong>Heads up —</strong> this page is open at <code>/admin</code> with no
              login. Actions taken here send real emails and write to production telemetry.
              The send pipeline is capped at 5 recipients per call; audience-wide sending
              stays in the GitHub Actions workflow.
            </div>
            <widget.Component />
          </>
        ) : (
          <>
            <h1 id="admin-title" className="admin-title">Admin</h1>
            <p className="admin-subhead">
              Internal Pulpo tools. Pick a widget below to get started.
            </p>
            <div className="admin-banner">
              <strong>Heads up —</strong> this page is open at <code>/admin</code> with no
              login. Each widget guards its own blast radius (e.g. the newsletter widget
              caps at 5 test recipients per send).
            </div>
            {ADMIN_WIDGETS.length === 0 ? (
              <div className="widget-empty">No widgets registered yet.</div>
            ) : (
              <div className="widget-grid">
                {ADMIN_WIDGETS.map((w) => (
                  <button
                    type="button"
                    key={w.slug}
                    className="widget-card"
                    onClick={() => goToWidget(w.slug)}
                  >
                    <p className="wc-category">{w.category}</p>
                    <p className="wc-label">{w.label}</p>
                    <p className="wc-desc">{w.description}</p>
                  </button>
                ))}
                {adminWidget && !widget && (
                  <div className="widget-empty">
                    Unknown widget <code>{adminWidget}</code> — pick one above.
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
