// Temporary diagnostic endpoint. Probes the three WAF-blocked Pulpo
// sources from Vercel's serverless runtime (AWS Lambda) and returns
// a tiny JSON verdict matrix.
//
// Purpose
// -------
// Yesterday's nightly + the 2026-05-30 GH-runner experiment confirmed
// the three sources block Azure GitHub-runner IPs at the WAF. From
// Google Cloud Shell IPs all three pass. This endpoint extends the
// experiment to AWS Lambda (Vercel's underlying runtime) — if AWS IPs
// also pass, a Vercel cron fallback is the cheapest fix path. If they
// don't, we need a GCP VM instead.
//
// Usage
// -----
// Hit the Vercel preview URL once after deploy:
//   curl https://<preview-url>/api/scrape-probe
// Three rows of {host, status, body_excerpt_token_present}.
//
// Lifecycle
// ---------
// This file is intentionally short-lived. Delete it (or gate it
// behind an admin token) after the AWS-vs-Azure question is settled.
// No telemetry, no caching, no rate limit — single-shot diagnostic.

const PROBES = [
  {
    host:     "realtyelsalvador",
    url:      "https://realtyelsalvador.com/tipo-de-propiedad/terrenos/",
    ok_token: "/propiedades/",
  },
  {
    host:     "elagente",
    url:      "https://www.elagenteinmobiliario.com/estado/for-sale/",
    ok_token: "/propiedad/",
  },
  {
    host:     "nexo",
    url:      "https://nexo.com.sv/api/v1/public/listings?skip=0&limit=10",
    ok_token: "listing_code",
  },
];

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 " +
  "(KHTML, like Gecko) Version/17.2 Safari/605.1.15";

async function probe(host, url, ok_token) {
  let status = null;
  let bytes = 0;
  let token_present = false;
  let error = null;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    const resp = await fetch(url, {
      headers: { "User-Agent": UA },
      signal:  controller.signal,
      redirect: "follow",
    });
    clearTimeout(timeout);
    status = resp.status;
    const text = await resp.text();
    bytes = text.length;
    token_present = text.includes(ok_token);
  } catch (e) {
    error = `${e.name}: ${e.message}`;
  }
  return {
    host,
    url,
    status,
    bytes,
    ok_token,
    token_present,
    verdict: status === 200 && token_present ? "PASS" : "FAIL",
    error,
  };
}

export default async function handler(req, res) {
  const results = [];
  for (const p of PROBES) {
    results.push(await probe(p.host, p.url, p.ok_token));
  }
  res.status(200).json({
    runtime: "vercel-serverless (AWS Lambda)",
    region:  process.env.VERCEL_REGION || "unknown",
    note:    "Diagnostic endpoint — delete after the WAF-vs-AWS experiment is settled.",
    results,
  });
}
