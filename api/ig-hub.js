// GET /ig — the Instagram link-in-bio hub.
//
// Instagram allows exactly one clickable link (the bio). This page IS that
// link's destination: it lists Pulpo's recent posts, and each links to its
// per-post /go/<code> redirector so a click → signup traces back to the
// exact post + content lever (the attribution loop's front door).
//
// Server-rendered, self-contained HTML (no SPA build dependency, like
// api/l/[token].js). Robust by construction: a missing/empty queue, a post
// with no attribution_code, or a post with no poster all degrade to a valid
// page — worst case, just the "join free" CTA. Every dynamic string is
// HTML-escaped (captions are our own copy, but we never trust-render).

const fs = require("fs");
const path = require("path");

const QUEUE_CANDIDATES = [
  path.join(__dirname, "..", "web", "data", "ig_queue.json"),
  path.join(process.cwd(), "web", "data", "ig_queue.json"),
];

const MAX_POSTS = 12; // the "active drop" the single bio link covers
const JOIN_CODE = "ig-d0-education"; // generic first-touch code for the top CTA

function readQueue() {
  for (const p of QUEUE_CANDIDATES) {
    try {
      const text = fs.readFileSync(p, "utf8");
      if (text && text.trim()) return JSON.parse(text);
    } catch (_) { /* try next */ }
  }
  return null;
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function publicUrl(p) {
  if (!p) return null;
  return "/" + String(p).replace(/^web\//, "");
}

// First bold **hook** or first non-empty line of a caption, plain text.
function hookOf(caption) {
  const s = String(caption || "");
  const bold = s.match(/\*\*(.+?)\*\*/);
  if (bold) return bold[1].trim();
  const line = s.split("\n").map((l) => l.trim()).find(Boolean);
  return line || "Ver en Pulpo";
}

// The recent live posts the bio link covers: posted, newest first, capped.
function activePosts(queue) {
  const items = (queue && Array.isArray(queue.items)) ? queue.items : [];
  return items
    .filter((it) => it && it.posted === true && it.poster_path)
    .sort((a, b) => String(b.posted_at || b.scheduled_for || "").localeCompare(
      String(a.posted_at || a.scheduled_for || "")))
    .slice(0, MAX_POSTS);
}

// Each post links to its /go code (attribution). Missing code → homepage,
// never a dead link.
function postHref(it) {
  return it.attribution_code ? `/go/${encodeURIComponent(it.attribution_code)}` : "/";
}

function renderCard(it) {
  const img = publicUrl(it.poster_path);
  const hook = esc(hookOf(it.caption));
  const href = postHref(it);
  const media = img
    ? `<img src="${esc(img)}" alt="" loading="lazy" />`
    : `<div class="noimg">🐙</div>`;
  return `<a class="card" href="${esc(href)}">
    <div class="thumb">${media}</div>
    <div class="hook">${hook}</div>
    <span class="go">Ver →</span>
  </a>`;
}

function renderPage(posts) {
  const cards = posts.map(renderCard).join("\n");
  const grid = posts.length
    ? `<section class="grid">${cards}</section>`
    : `<p class="empty">Muy pronto, más propiedades. Mientras, sumate gratis 👇</p>`;
  return `<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Pulpo · tu pedazo de paraíso</title>
<style>
  :root{--coral:#e8462a;--ink:#161c20;--paper:#fbf7f0;--card:#fff;--muted:#6b625a;}
  @media (prefers-color-scheme:dark){:root{--ink:#f2ede6;--paper:#141210;--card:#211d1a;--muted:#a89e94;}}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:"Nunito",-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
    background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased;
    line-height:1.4;padding:0 16px 48px}
  .wrap{max-width:600px;margin:0 auto}
  header{text-align:center;padding:36px 0 8px}
  .oct{font-size:44px;line-height:1}
  h1{font-size:26px;font-weight:900;margin:8px 0 2px}
  .tag{color:var(--muted);font-weight:700;font-size:15px}
  .join{display:block;background:var(--coral);color:#fff;text-decoration:none;
    text-align:center;font-weight:900;font-size:18px;padding:16px;border-radius:16px;
    margin:20px 0 8px;box-shadow:0 10px 24px -12px rgba(232,70,42,.7)}
  .join small{display:block;font-weight:700;font-size:13px;opacity:.9;margin-top:2px}
  .lead{color:var(--muted);font-weight:700;font-size:14px;text-align:center;margin:22px 0 12px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .card{display:flex;flex-direction:column;background:var(--card);border-radius:16px;
    overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 6px 18px -12px rgba(0,0,0,.4)}
  .thumb{aspect-ratio:4/5;background:#0a97ab22;overflow:hidden}
  .thumb img{width:100%;height:100%;object-fit:cover;display:block}
  .noimg{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:40px}
  .hook{font-weight:800;font-size:14px;padding:10px 12px 4px;flex:1}
  .go{font-weight:900;font-size:13px;color:var(--coral);padding:0 12px 12px}
  .empty{text-align:center;color:var(--muted);font-weight:700;padding:24px 0}
  footer{text-align:center;color:var(--muted);font-size:13px;margin-top:28px;font-weight:700}
  a.plain{color:var(--coral);text-decoration:none}
</style></head>
<body><div class="wrap">
  <header>
    <div class="oct">🐙</div>
    <h1>Pulpo</h1>
    <div class="tag">Tu pedazo de paraíso · Your piece of paradise</div>
  </header>
  <a class="join" href="/go/${esc(JOIN_CODE)}">Sumate gratis
    <small>El Top 10 de El Salvador en tu correo, cada domingo · free</small></a>
  <p class="lead">Lo que viste en el feed 👇</p>
  ${grid}
  <footer>pulpo.club · <a class="plain" href="/go/${esc(JOIN_CODE)}">sumate gratis</a></footer>
</div></body></html>`;
}

module.exports = function handler(req, res) {
  let posts = [];
  try {
    posts = activePosts(readQueue());
  } catch (_) {
    posts = []; // never break the bio link
  }
  res.statusCode = 200;
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  // short cache: the drop rotates but not every second
  res.setHeader("Cache-Control", "public, s-maxage=300, stale-while-revalidate=600");
  res.end(renderPage(posts));
};

// Exported for tests (pure).
module.exports.activePosts = activePosts;
module.exports.hookOf = hookOf;
module.exports.postHref = postHref;
module.exports.renderPage = renderPage;
