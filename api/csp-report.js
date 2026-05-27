// POST /api/csp-report
//
// Browser-side CSP failures are otherwise silent on the server. This
// endpoint accepts both the legacy `application/csp-report` payload
// and the newer Reporting API shape, captures a compact event to
// PostHog, and stays best-effort: reports are unauthenticated browser
// telemetry, not user-facing product state.

const { makeRateLimiter, send429, ipFromRequest } = require("./_rate_limit");
let posthog = require("./_posthog");

const limiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 60,
  name: "csp_report",
});

const MAX_FIELD = 1_000;

function safeStr(v) {
  if (typeof v !== "string") return "";
  return v.length > MAX_FIELD ? v.slice(0, MAX_FIELD) : v;
}

function reportBodyFromPayload(payload) {
  if (!payload) return null;
  if (Array.isArray(payload)) {
    const first = payload.find((item) => item && (item.type === "csp-violation" || item.body));
    return first && first.body ? first.body : null;
  }
  if (payload["csp-report"] && typeof payload["csp-report"] === "object") {
    return payload["csp-report"];
  }
  if (payload.body && typeof payload.body === "object") {
    return payload.body;
  }
  if (payload["report-body"] && typeof payload["report-body"] === "object") {
    return payload["report-body"];
  }
  return null;
}

function normalizeReport(payload) {
  const body = reportBodyFromPayload(payload);
  if (!body) return null;

  const blockedUri = body["blocked-uri"] || body.blockedURL || body.blockedURLForViolation || body.blocked_uri;
  const violatedDirective = body["violated-directive"] || body.effectiveDirective || body.violated_directive;
  const documentUri = body["document-uri"] || body.documentURL || body.document_uri;
  const originalPolicy = body["original-policy"] || body.originalPolicy || body.original_policy;
  const sourceFile = body["source-file"] || body.sourceFile || body.source_file;
  const lineNumber = body["line-number"] || body.lineNumber || body.line_number;

  if (!blockedUri && !violatedDirective && !documentUri) return null;

  return {
    blocked_uri: safeStr(blockedUri),
    violated_directive: safeStr(violatedDirective),
    document_uri: safeStr(documentUri),
    original_policy: safeStr(originalPolicy),
    source_file: safeStr(sourceFile),
    line_number: Number.isFinite(Number(lineNumber)) ? Number(lineNumber) : null,
  };
}

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "csp_report");

  const payload = await readJsonBody(req);
  const report = normalizeReport(payload);
  if (!report) return res.status(400).json({ error: "invalid_report" });

  posthog.capture("server:csp-report", "csp.violation", report);
  await posthog.flush();
  return res.status(200).json({ ok: true });
}

handler.__testing__ = {
  normalizeReport,
  limiter,
  setPosthogClient(client) {
    posthog = client;
  },
};

module.exports = handler;
