import React from "react";
import { captureException } from "./telemetry/client";
import { sendErrorToServer } from "./telemetry/error-sink";

// Top-level error boundary. Catches any render-time exception and renders a
// branded fallback instead of blanking the page. Wired in app.jsx around
// <App />.
//
// Errors are forwarded to TWO sinks in parallel (audit P0-7):
//   1. PostHog Error Tracking — funnel breaks, alerts, session replay link.
//   2. /api/client-error → Vercel runtime logs — always-on backstop for
//      when PostHog is blocked (ad-blockers, declined consent, SDK fail).
// Both fire fire-and-forget; neither blocks the fallback render.
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[pulpo] uncaught error", error, info);
    const extra = {
      componentStack: info?.componentStack,
      kind: "react.errorBoundary",
      // `section` is opt-in. Section-scoped boundaries (homepage v2)
      // tag PostHog with the failing surface so dashboards can split
      // "hero crashed" from "shelf crashed" cleanly.
      section: this.props.section || undefined,
    };
    try {
      captureException(error, extra);
    } catch { /* never let telemetry break the fallback render */ }
    try {
      sendErrorToServer(error, extra);
    } catch { /* same — telemetry must never throw */ }
  }

  render() {
    if (this.state.error) {
      // Compact fallback — a single section failed inside a larger
      // tree. Renders inline so the rest of the page is unaffected.
      if (this.props.compact) {
        return (
          <div
            role="alert"
            data-testid="error-boundary-fallback"
            data-section={this.props.section || undefined}
            style={compactStyle}
          >
            This section is unavailable.
          </div>
        );
      }
      return (
        <div role="alert" data-testid="error-boundary-fallback" style={fallbackStyle}>
          <h1 style={{ margin: 0, fontSize: 22 }}>Something went wrong.</h1>
          <p style={{ margin: 0, color: "#555", maxWidth: 420 }}>
            We hit an unexpected error. Reload the page — if it persists, the
            team has been notified.
          </p>
          <button onClick={() => window.location.reload()} style={btnStyle}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const compactStyle = {
  padding: "24px 20px",
  textAlign: "center",
  color: "#5A5650",
  fontSize: 13,
  fontFamily: "var(--font-sans)",
  background: "#F8F4EC",
  borderRadius: 8,
  margin: "16px auto",
  maxWidth: 480,
};

const fallbackStyle = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 16,
  minHeight: "60vh",
  padding: 24,
  textAlign: "center",
  fontFamily: "var(--font-sans)",
};

const btnStyle = {
  padding: "10px 18px",
  borderRadius: 8,
  border: "1px solid #ccc",
  background: "#111",
  color: "#fff",
  fontSize: 14,
  cursor: "pointer",
};
