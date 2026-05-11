import React from "react";
import { captureException } from "./telemetry/client";

// Top-level error boundary. Catches any render-time exception and renders a
// branded fallback instead of blanking the page. Wired in app.jsx around
// <App />. Forwards the error to PostHog (Error Tracking surface) via
// captureException so the team gets paged via PostHog alerts.
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
    try {
      captureException(error, { componentStack: info?.componentStack, kind: "react.errorBoundary" });
    } catch { /* never let telemetry break the fallback render */ }
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" style={fallbackStyle}>
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

const fallbackStyle = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 16,
  minHeight: "60vh",
  padding: 24,
  textAlign: "center",
  fontFamily: "Inter, system-ui, sans-serif",
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
