/* ── inline-block #1 ── */
'use strict';
const DATA_URL = 'data/ranked.json';
const META_URL = 'data/last_updated.json';

const SOURCE_NAMES = {
  oceanside:'Oceanside El Salvador', goodlife:'GoodLife El Salvador',
  century21:'Century 21 El Salvador', bienesraices:'Bienes Raíces El Salvador',
  kazu:'Kazu Real Estate', remax:'RE/MAX El Salvador',
};

/* ── Zone groups (mirrors automation/zones.py) ───────── */
const ZONE_GROUPS = {
  'surf-city-1':  {label:'Surf City 1',    zones:['el-tunco','el-sunzal','el-zonte','san-diego','mizata']},
  'surf-city-2':  {label:'Surf City 2',    zones:['el-cuco','las-flores','punta-mango','el-espino','conchagua']},
  'other-coastal':{label:'Other coastal',  zones:['la-libertad','puerto-la-libertad','jiquilisco','tamanique','acajutla','costa-del-sol','san-luis-la-herradura']},
  'inland':       {label:'Inland',         zones:['la-union','san-salvador','ahuachapan','santa-ana','sonsonate','chalatenango','la-paz','tonacatepeque','soyapango','mejicanos','nejapa','apopa','san-martin','ilopango','zacatecoluca','olocuilta','nueva-concepcion','cojutepeque','suchitoto','chalchuapa','santa-tecla','izalco','armenia','ataco','apaneca','tacuba','juayua','san-jose-villanueva','nahuizalco','tejutla','sesori','usulutan','san-miguel']},
};
const ZONE_GROUP_ORDER = ['surf-city-1','surf-city-2','other-coastal','inland'];

// Build zone → group reverse lookup
const ZONE_TO_GROUP = {};
for (const [gk,g] of Object.entries(ZONE_GROUPS))
  for (const z of g.zones) ZONE_TO_GROUP[z] = gk;

/* ── Zone colors ─────────────────────────────────────── */
const ZONE_PALETTE = [
  {bg:'#E1F5EE',fg:'#085041'}, // 0 teal
  {bg:'#E6F1FB',fg:'#0C447C'}, // 1 blue
  {bg:'#EAF3DE',fg:'#27500A'}, // 2 green
  {bg:'#FAECE7',fg:'#712B13'}, // 3 coral
  {bg:'#FAEEDA',fg:'#633806'}, // 4 amber
  {bg:'#EEEDFE',fg:'#3C3489'}, // 5 purple
  {bg:'#FBEAF0',fg:'#72243E'}, // 6 pink
  {bg:'#F1EFE8',fg:'#2C2C2A'}, // 7 gray
];
const ZONE_COLORS = {
  'el-tunco':ZONE_PALETTE[3],'el-sunzal':ZONE_PALETTE[4],'el-zonte':ZONE_PALETTE[6],
  'san-diego':ZONE_PALETTE[1],'mizata':ZONE_PALETTE[7],'el-cuco':ZONE_PALETTE[3],
  'las-flores':ZONE_PALETTE[6],'punta-mango':ZONE_PALETTE[4],'el-espino':ZONE_PALETTE[0],
  'jiquilisco':ZONE_PALETTE[1],'tamanique':ZONE_PALETTE[0],'conchagua':ZONE_PALETTE[5],
  'ahuachapan':ZONE_PALETTE[4],'la-union':ZONE_PALETTE[1],'san-salvador':ZONE_PALETTE[7],
  'la-libertad':ZONE_PALETTE[2],'puerto-la-libertad':ZONE_PALETTE[2],
  'santa-ana':ZONE_PALETTE[4],'sonsonate':ZONE_PALETTE[0],'costa-del-sol':ZONE_PALETTE[2],
};

function _hashZone(z) {
  let h = 5381;
  for (let i = 0; i < z.length; i++) h = ((h << 5) + h + z.charCodeAt(i)) >>> 0;
  return h % ZONE_PALETTE.length;
}
function zoneColor(z) { return ZONE_COLORS[z] || ZONE_PALETTE[_hashZone(z)]; }
function zoneColor_bg(z) { return zoneColor(z).bg; }

/* ── State ───────────────────────────────────────────── */
let ALL_DATA = [], FILTER = 'all', ZONE_F = null;
let SORT_COL = 'ppm', SORT_DIR = 'asc', OPEN_ID = null;

/* ── Tune-panel state: price range ─────────────────────── */
// Snap points calibrated to the live data distribution: median $250K,
// 95th percentile $4.1M. Index 0 = no min ($0); last index = no max (Infinity).
// Indices into PRICE_SNAPS are what's stored in URL state, not raw USD,
// so the snap labels stay stable even if we re-tune the snap points later.
const PRICE_SNAPS = [0, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000, Infinity];
const PRICE_LABELS = ['$0', '$25K', '$50K', '$100K', '$250K', '$500K', '$1M', '$2.5M', '$5M', 'No max'];
let PRICE_MIN_IDX = 0, PRICE_MAX_IDX = PRICE_SNAPS.length - 1;
const isDefaultPriceRange = () =>
  PRICE_MIN_IDX === 0 && PRICE_MAX_IDX === PRICE_SNAPS.length - 1;

/* ── Tune-panel state: size range ──────────────────────── */
// Log-spaced snap points calibrated to live data (live spread is ~67 m² →
// 6.8M m², median 2,516 m², 95th %ile 482K m²). Index 0 = no min;
// last index = no max (Infinity). Same URL-as-index encoding as price.
const SIZE_SNAPS  = [0, 100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000, Infinity];
const SIZE_LABELS = ['No min', '100 m²', '500 m²', '1K m²', '5K m²', '10K m²', '50K m²', '100K m²', '500K m²', 'No max'];
let SIZE_MIN_IDX = 0, SIZE_MAX_IDX = SIZE_SNAPS.length - 1;
const isDefaultSizeRange = () =>
  SIZE_MIN_IDX === 0 && SIZE_MAX_IDX === SIZE_SNAPS.length - 1;

/* ── Minimum-score filter ──────────────────────────────
   Single-handle slider [0..100]: only show listings with rank_score ≥ MIN_SCORE.
   Default 0 = pass-through (no filter). The user can crank this up to see
   only the top N% of listings — useful for the curation use case ("only show
   me listings strong enough to be worth a phone call").
   URL key: ?min_score=NN. Default omitted from URL to keep shareable URLs
   clean. */
let MIN_SCORE = 0;
const isDefaultMinScore = () => MIN_SCORE === 0;

/* ── Tune-panel state: V/L/M weight sliders ────────────── */
// Defaults match pulpo/ranker.py composite weights (0.40 / 0.35 / 0.25).
// Slider values are stored as integer percentages 0..100 — re-blended
// composite per row is `Σ(w_i * leg_i) / Σ(w_i)` so they don't need to
// sum to 100. Encoded in URL as `?w=40,35,25` to keep shareable URLs
// stable across rebalance.
const WEIGHT_DEFAULTS = {value: 40, location: 35, momentum: 25};
const WEIGHT_KEYS = ['value', 'location', 'momentum'];  // stable order matches URL
const WEIGHTS = {...WEIGHT_DEFAULTS};
const isDefaultWeights = () =>
  WEIGHT_KEYS.every(k => WEIGHTS[k] === WEIGHT_DEFAULTS[k]);

// Re-blend the composite using current slider weights. Falls back to the
// listing's static rank_score when any leg is missing — same null
// semantics as the original Python ranker.
function recomputeComposite(li, w = WEIGHTS) {
  const fields = {value: li.value_score, location: li.location_score, momentum: li.momentum_score};
  let weighted = 0, total = 0;
  for (const k of WEIGHT_KEYS) {
    const score = fields[k];
    const wt = w[k];
    if (score == null || !wt) continue;
    weighted += wt * score;
    total += wt;
  }
  if (total === 0) return li.rank_score; // all weights at zero → preserve original order
  return weighted / total;
}

/* ── Helpers ─────────────────────────────────────────── */
const fmtUSD  = v => v==null ? '—' : '$'+Math.round(v).toLocaleString('en-US');
const fmtPPM  = v => (v==null||v<=0) ? '—' : '$'+Math.round(v).toLocaleString('en-US');
// Salvadoran vara² is 0.836m × 0.836m = 0.698896 m². Conversion lives in
// pulpo/units.py:19 (Python) and is duplicated here for client-side render
// of the alternate unit. Keep in sync.
const M2_PER_VARA2 = 0.698896;
const fmtPPV2 = v => (v==null||v<=0) ? '—' : '$'+Math.round(v*M2_PER_VARA2).toLocaleString('en-US');
const fmtArea = v => v==null ? '—' : Math.round(v).toLocaleString('en-US')+' m²';
const fmtDays = d => d==null ? '—' : d===0 ? 'Today' : d===1 ? '1 day ago' : `${d} days ago`;
function esc(s){ return String(s??'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])) }
function zoneLabel(z){ return z ? z.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase()) : 'No zone'; }
const isNoZone = r => r.zone_confidence ? r.zone_confidence === 'unresolved' : (!r.zone && !r.department);

function zonePillHTML(r) {
  if (r.zone) {
    const {bg,fg} = zoneColor(r.zone);
    const label = zoneLabel(r.zone);
    return `<span class="zone-pill" style="background:${bg};color:${fg}">${esc(label)}</span>`;
  }
  if (r.department) {
    const slug = r.department.toLowerCase().replace(/\s+/g,'-');
    const {bg,fg} = zoneColor(slug);
    return `<span class="zone-pill" style="background:${bg};color:${fg};opacity:.85">${esc(r.department)}</span>`;
  }
  return `<span class="zone-pill zone-pill--nozone">No zone</span>`;
}

/* ── "NEW" badge ─────────────────────────────────────── */
// Rendered next to the zone pill when first_seen_at is within NEW_BADGE_DAYS.
// Returns '' for older or missing timestamps so the existing pill layout is
// unchanged on rows that don't qualify.
const NEW_BADGE_DAYS = 14;
const NEW_BADGE_MS = NEW_BADGE_DAYS * 24 * 60 * 60 * 1000;
function isNewListing(r, nowMs = Date.now()) {
  if (!r || !r.first_seen_at) return false;
  const t = Date.parse(r.first_seen_at);
  if (Number.isNaN(t)) return false;
  return (nowMs - t) <= NEW_BADGE_MS;
}
function newBadgeHTML(r) {
  return isNewListing(r) ? '<span class="new-badge" title="Listed in the last 14 days">NEW</span>' : '';
}

/* ── Score → Stars ───────────────────────────────────── */
function scoreToStars(s) {
  if (s==null) return 0;
  return Math.max(0,Math.min(5,Math.round(s/10)/2));
}
function renderStars(score) {
  const stars = scoreToStars(score);
  const pct = (stars/5*100).toFixed(1)+'%';
  return `<span class="stars-wrap"><span class="stars"><span class="stars-bg">★★★★★</span><span class="stars-fg" style="width:${pct}">★★★★★</span></span><span class="stars-val">${stars.toFixed(1)}</span></span>`;
}

/* ── URL state ───────────────────────────────────────── */
function _parseSnapIdx(raw, snaps) {
  // URL carries snap-point indices, not raw USD/m², so the encoding survives
  // re-tuning the snap array. Out-of-range / non-numeric → null (use default).
  const n = parseInt(raw, 10);
  if (!Number.isInteger(n) || n < 0 || n >= snaps.length) return null;
  return n;
}
function readURL() {
  const p = new URLSearchParams(location.search);
  FILTER = ['all','open','gated'].includes(p.get('filter')) ? p.get('filter') : 'all';
  const s = p.get('sort')||'ppm_asc';
  const m = s.match(/^(zone|price|area|ppm|stars|newest|deal|location|momentum|composite)_(asc|desc)$/);
  if (m) { SORT_COL=m[1]; SORT_DIR=m[2]; }
  const zg=p.get('zone_group'), z=p.get('zone');
  if (zg==='no-zone') ZONE_F={type:'no-zone',value:'no-zone'};
  else if (zg&&ZONE_GROUPS[zg]) ZONE_F={type:'group',value:zg};
  else if (z) ZONE_F={type:'zone',value:z};
  else ZONE_F=null;
  const pmin = _parseSnapIdx(p.get('price_min'), PRICE_SNAPS);
  const pmax = _parseSnapIdx(p.get('price_max'), PRICE_SNAPS);
  PRICE_MIN_IDX = pmin ?? 0;
  PRICE_MAX_IDX = pmax ?? PRICE_SNAPS.length - 1;
  if (PRICE_MIN_IDX > PRICE_MAX_IDX) {
    // Defensive: malformed URL with min>max collapses to defaults rather
    // than zero-listings empty state, which would look broken on first load.
    PRICE_MIN_IDX = 0;
    PRICE_MAX_IDX = PRICE_SNAPS.length - 1;
  }
  const smin = _parseSnapIdx(p.get('size_min'), SIZE_SNAPS);
  const smax = _parseSnapIdx(p.get('size_max'), SIZE_SNAPS);
  SIZE_MIN_IDX = smin ?? 0;
  SIZE_MAX_IDX = smax ?? SIZE_SNAPS.length - 1;
  if (SIZE_MIN_IDX > SIZE_MAX_IDX) {
    SIZE_MIN_IDX = 0;
    SIZE_MAX_IDX = SIZE_SNAPS.length - 1;
  }
  // Min-score filter: ?min_score=NN (integer 0..100). Anything malformed
  // or out-of-range silently drops to the default 0 (pass-through).
  const msRaw = p.get('min_score');
  if (msRaw) {
    const ms = parseInt(msRaw, 10);
    MIN_SCORE = (Number.isInteger(ms) && ms >= 0 && ms <= 100) ? ms : 0;
  } else {
    MIN_SCORE = 0;
  }
  // Weight sliders: ?w=V,L,M (integers 0..100). Reject malformed input
  // by reverting to defaults — silently dropping the URL is friendlier
  // than rendering a confusing "weights all zero → no sort change" state.
  const wRaw = p.get('w');
  if (wRaw) {
    const parts = wRaw.split(',');
    if (parts.length === WEIGHT_KEYS.length) {
      const parsed = parts.map(x => parseInt(x, 10));
      if (parsed.every(n => Number.isInteger(n) && n >= 0 && n <= 100)) {
        WEIGHT_KEYS.forEach((k, i) => { WEIGHTS[k] = parsed[i]; });
      }
    }
  }
  OPEN_ID=p.get('listing')||null;
}
function pushURL(replace=true) {
  const p=new URLSearchParams();
  if (FILTER!=='all') p.set('filter',FILTER);
  if (SORT_COL!=='ppm'||SORT_DIR!=='asc') p.set('sort',`${SORT_COL}_${SORT_DIR}`);
  if (ZONE_F) {
    if (ZONE_F.type==='no-zone') p.set('zone_group','no-zone');
    else if (ZONE_F.type==='group') p.set('zone_group',ZONE_F.value);
    else p.set('zone',ZONE_F.value);
  }
  if (PRICE_MIN_IDX !== 0)                    p.set('price_min', String(PRICE_MIN_IDX));
  if (PRICE_MAX_IDX !== PRICE_SNAPS.length-1) p.set('price_max', String(PRICE_MAX_IDX));
  if (SIZE_MIN_IDX  !== 0)                    p.set('size_min',  String(SIZE_MIN_IDX));
  if (SIZE_MAX_IDX  !== SIZE_SNAPS.length-1)  p.set('size_max',  String(SIZE_MAX_IDX));
  if (!isDefaultMinScore())                   p.set('min_score', String(MIN_SCORE));
  if (!isDefaultWeights()) {
    p.set('w', WEIGHT_KEYS.map(k => WEIGHTS[k]).join(','));
  }
  if (OPEN_ID) p.set('listing',OPEN_ID);
  const qs=p.toString();
  const url=qs?`${location.pathname}?${qs}`:location.pathname;
  replace?history.replaceState(null,'',url):history.pushState(null,'',url);
}

/* ── Filter + Sort ───────────────────────────────────── */
// Predicate: a listing's price falls within the active range. Listings
// without a price (price_usd === null) are excluded only when the user has
// narrowed the range from defaults — full-range = "show everything,
// including unpriced." That way the price filter doesn't silently hide
// unpriced listings just because the panel was opened.
function _priceInRange(r) {
  if (isDefaultPriceRange()) return true;
  const p = r.price_usd;
  if (p == null) return false;
  return p >= PRICE_SNAPS[PRICE_MIN_IDX] && p <= PRICE_SNAPS[PRICE_MAX_IDX];
}
function _sizeInRange(r) {
  // Same defaults-pass-everything semantics as _priceInRange. When the
  // user narrows either handle, listings without area_m2 drop out — a
  // null area can't satisfy "between X and Y m²".
  if (isDefaultSizeRange()) return true;
  const a = r.area_m2;
  if (a == null) return false;
  return a >= SIZE_SNAPS[SIZE_MIN_IDX] && a <= SIZE_SNAPS[SIZE_MAX_IDX];
}
function _scoreAtLeastMin(r) {
  // Minimum-score filter — pass-through when MIN_SCORE === 0. Listings
  // without rank_score (None / null) drop only when the user has set a
  // non-default threshold, matching the "default-passes-everything"
  // pattern of _priceInRange / _sizeInRange.
  if (isDefaultMinScore()) return true;
  return (r.rank_score ?? -Infinity) >= MIN_SCORE;
}
function filteredRows() {
  return ALL_DATA.filter(r => {
    if (FILTER==='open'  && r.is_in_development)  return false;
    if (FILTER==='gated' && !r.is_in_development) return false;
    if (!_priceInRange(r)) return false;
    if (!_sizeInRange(r))  return false;
    if (!_scoreAtLeastMin(r)) return false;
    if (!ZONE_F) return true;
    if (ZONE_F.type==='no-zone') return isNoZone(r);
    if (ZONE_F.type==='zone')    return r.zone===ZONE_F.value;
    if (ZONE_F.type==='group') {
      const zones=ZONE_GROUPS[ZONE_F.value]?.zones||[];
      return zones.includes(r.zone);
    }
    return true;
  });
}
function sortedRows(rows) {
  const dir=SORT_DIR==='asc'?1:-1, nil=SORT_DIR==='asc'?Infinity:-Infinity;
  return [...rows].sort((a,b) => {
    if (SORT_COL==='zone') {
      // No-zone → end; dept-only → before pure no-zone; resolved zone → normal
      const az=a.zone||(a.department?'￾'+a.department:'￿');
      const bz=b.zone||(b.department?'￾'+b.department:'￿');
      return az.localeCompare(bz,'es')*dir;
    }
    if (SORT_COL==='newest') {
      // ISO8601 strings sort lexicographically === chronologically. Nulls sink
      // regardless of direction — listings without first_seen_at are always
      // less informative than ones that have it.
      const sentinel = SORT_DIR==='asc' ? '￿' : '';
      const av = a.first_seen_at || sentinel;
      const bv = b.first_seen_at || sentinel;
      return av.localeCompare(bv) * dir;
    }
    let va,vb;
    if      (SORT_COL==='price')    {va=a.price_usd      ??nil;vb=b.price_usd      ??nil;}
    else if (SORT_COL==='area')     {va=a.area_m2        ??nil;vb=b.area_m2        ??nil;}
    else if (SORT_COL==='stars')    {va=recomputeComposite(a) ?? nil; vb=recomputeComposite(b) ?? nil;}
    else if (SORT_COL==='deal')     {va=a.value_score    ??nil;vb=b.value_score    ??nil;}
    else if (SORT_COL==='location') {va=a.location_score ??nil;vb=b.location_score ??nil;}
    else if (SORT_COL==='momentum') {va=a.momentum_score ??nil;vb=b.momentum_score ??nil;}
    else if (SORT_COL==='composite') {
      // Composite uses live slider weights. Recomputed per-row each
      // sort because WEIGHTS may have changed between sorts and the
      // recomputed value is cheap.
      const av = recomputeComposite(a);
      const bv = recomputeComposite(b);
      va = av ?? nil; vb = bv ?? nil;
    }
    else {va=(a.price_per_m2>0)?a.price_per_m2:nil;vb=(b.price_per_m2>0)?b.price_per_m2:nil;}
    return (va-vb)*dir;
  });
}

/* ── Sort header UI ──────────────────────────────────── */
function updateSortHeaders() {
  document.querySelectorAll('thead th.sortable').forEach(th => {
    const col=th.dataset.col, ic=document.getElementById(`ic-${col}`);
    if (col===SORT_COL) { th.classList.add('sorted'); if(ic)ic.textContent=SORT_DIR==='asc'?'↑':'↓'; }
    else { th.classList.remove('sorted'); if(ic)ic.textContent='↕'; }
  });
  const sel=document.getElementById('mobile-sort');
  if (sel) sel.value=`${SORT_COL}_${SORT_DIR}`;
}

/* ── Zone filter render ──────────────────────────────── */
function buildZoneFilter(data) {
  const groupCounts={}, zoneCounts={};
  let noZoneCount=0;
  for (const r of data) {
    if (isNoZone(r)) { noZoneCount++; continue; }
    const z=r.zone; if(!z) continue;
    zoneCounts[z]=(zoneCounts[z]||0)+1;
    const gk=ZONE_TO_GROUP[z];
    if(gk) groupCounts[gk]=(groupCounts[gk]||0)+1;
  }
  // .zone-filter exists once per panel body (desktop + mobile both render
  // the section); update them all so toggling the panel between viewports
  // doesn't show stale chip state.
  const wraps=document.querySelectorAll('.zone-filter');
  if (!wraps.length) return;
  let html='';
  for (const gk of ZONE_GROUP_ORDER) {
    const g=ZONE_GROUPS[gk], cnt=groupCounts[gk]||0;
    if(!cnt) continue;
    const isGA=ZONE_F?.type==='group'&&ZONE_F?.value===gk;
    const pills=g.zones.filter(z=>zoneCounts[z]).map(z=>{
      const {bg,fg}=zoneColor(z), label=zoneLabel(z);
      const active=ZONE_F?.type==='zone'&&ZONE_F?.value===z?' pill-active':'';
      return `<span class="zone-pill clickable${active}" data-zone="${esc(z)}" style="background:${bg};color:${fg}">${esc(label)}</span>`;
    }).join('');
    html+=`<div class="zf-group${isGA?' active':''}" data-group="${esc(gk)}">
      <span class="zg-label" data-group="${esc(gk)}">${esc(g.label)}</span>
      <div class="zg-pills">${pills}</div>
      <span class="zg-count">${cnt.toLocaleString('en-US')}</span>
    </div>`;
  }
  // Synthetic "No zone" group
  const isNZ=ZONE_F?.type==='no-zone';
  const nzRing=isNZ?' pill-active':'';
  html+=`<div class="zf-group${isNZ?' active':''}" data-group="no-zone">
    <span class="zg-label" data-group="no-zone">No zone</span>
    <div class="zg-pills"><span class="zone-pill zone-pill--nozone clickable${nzRing}" data-zone="__no-zone__">No zone</span></div>
    <span class="zg-count">${noZoneCount.toLocaleString('en-US')}</span>
  </div>`;
  for (const wrap of wraps) {
    wrap.innerHTML=html;
    wrap.querySelectorAll('.zg-label').forEach(el=>el.addEventListener('click',()=>toggleGroupFilter(el.dataset.group)));
    wrap.querySelectorAll('.zone-pill.clickable').forEach(el=>el.addEventListener('click',e=>{
      e.stopPropagation();
      const z=el.dataset.zone;
      if(z==='__no-zone__') toggleGroupFilter('no-zone');
      else toggleZoneFilter(z);
    }));
  }
}
function toggleGroupFilter(gk) {
  ZONE_F=(gk==='no-zone')
    ? (ZONE_F?.type==='no-zone' ? null : {type:'no-zone',value:'no-zone'})
    : (ZONE_F?.type==='group'&&ZONE_F?.value===gk ? null : {type:'group',value:gk});
  OPEN_ID=null;
  document.getElementById('side-panel').classList.remove('open');
  pushURL(true); render();
}
function toggleZoneFilter(z) {
  ZONE_F=(ZONE_F?.type==='zone'&&ZONE_F?.value===z) ? null : {type:'zone',value:z};
  OPEN_ID=null;
  document.getElementById('side-panel').classList.remove('open');
  pushURL(true); render();
}

/* ── Side panel ──────────────────────────────────────── */
// reasonFor extracts the per-leg explanation from rank_reasons. Each leg's
// score() returns a string like "value 100 ($35.77/m² = 0th pct of el-zonte
// land, 3 comps)"; we strip the leading "<name> <num>" and the parens to
// surface the substantive part as the bar's caption.
function reasonFor(prefix, reasons) {
  if (!Array.isArray(reasons)) return '';
  const m = reasons.find(r => typeof r === 'string' && r.startsWith(prefix + ' '));
  if (!m) return '';
  const i = m.indexOf('(');
  if (i < 0) return '';
  const close = m.lastIndexOf(')');
  return close > i ? m.slice(i + 1, close).trim() : m.slice(i + 1).trim();
}

// ── Score breakdown components ─────────────────────────
// Canonical display labels for the three V/L/M dimensions. Single source of
// truth — sort dropdown, score breakdown bars, and any future surface that
// names a leg should reference SCORE_DIMENSIONS so renaming a label is one
// edit, not a hunt across the file.
const SCORE_DIMENSIONS = [
  // [slug,         displayName,           color,      tooltip]
  ['value',    'Price vs Comps', '#059669', 'How cheap this listing is versus similar lots in the same area'],
  ['location', 'Location',       '#2563eb', 'Zone tier, beachfront access, infrastructure, and distance to the airport'],
  ['momentum', 'Momentum',       '#ea580c', 'Whether this area is gaining or losing steam right now'],
];

// One score bar (label + track + value + per-listing reason). Clicking the
// label opens the methodology modal — replaces the prior cursor:help that
// had no actionable click target. The native title attribute is kept as a
// hover hint while the click is the canonical interaction.
function scoreBarHTML(opts) {
  // opts: { name, value, color, tooltip, reason }
  const reason = opts.reason ? `<div class="score-reason">${esc(opts.reason)}</div>` : '';
  return `<div class="score-block">
    <div class="score-row">
      <button type="button" class="score-name js-open-methodology" title="${esc(opts.tooltip)} — click for details">${esc(opts.name)}</button>
      <span class="score-track"><span class="score-fill" style="width:${opts.value}%;background:${opts.color}"></span></span>
      <span class="score-n">${Math.round(opts.value)}</span>
    </div>
    ${reason}
  </div>`;
}

function panelHTML(r) {
  // Three legs (Price vs Comps / Location / Momentum) with the V/L/M
  // canonical fields populated by pulpo/ranker.py. Per-listing reason is
  // pulled from rank_reasons; clicking the label opens the methodology.
  const scoreField = {value: r.value_score, location: r.location_score, momentum: r.momentum_score};
  const scoreBars = SCORE_DIMENSIONS
    .filter(([slug]) => scoreField[slug] != null)
    .map(([slug, name, color, tooltip]) => scoreBarHTML({
      name, value: scoreField[slug], color, tooltip,
      reason: reasonFor(slug, r.rank_reasons),
    }))
    .join('');
  const warnings=r.validation_warnings||[];
  const warnHTML=warnings.length
    ? `<span class="warn-icon" title="Validation warnings">⚠<span class="warn-tooltip">${warnings.map(esc).join('<br>')}</span></span>`
    : '';
  const zoneDisplay=r.zone ? zoneLabel(r.zone) : (r.department||'No zone');
  const devTag=r.is_in_development
    ? `<span class="panel-dev-tag">🏘 ${esc(r.development_name||'Gated / Development')}</span><br>` : '';
  const broker=[r.broker_name,r.broker_phone,r.broker_email].filter(Boolean);
  const brokerHTML=broker.length
    ? `<div class="panel-section-label" style="margin-top:16px">Broker</div><div style="font-size:13px;color:var(--t2);line-height:1.8">${broker.map(esc).join('<br>')}</div>` : '';
  const description=r.description
    ? `<div class="panel-section-label" style="margin-top:16px">Description</div><div class="panel-desc">${esc(r.description.slice(0,600))}${r.description.length>600?'…':''}</div>` : '';
  const cta=r.url
    ? `<a class="panel-cta" href="${esc(r.url)}" target="_blank" rel="noopener" style="margin-top:20px">View on ${esc(SOURCE_NAMES[r.source]||r.source)} →</a>` : '';
  // Hero photo block
  const photoUrls = r.photo_urls || [];
  const hero = r.hero_photo_path;
  const totalPhotos = photoUrls.length;
  let photoBlock = '';
  if (hero) {
    const counter = totalPhotos > 1 ? `<span class="panel-hero-counter">1 of ${totalPhotos}</span>` : '';
    const zoom = `<span class="panel-hero-zoom"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg></span>`;
    photoBlock = `<div class="panel-hero" onclick="openLightbox(${JSON.stringify(photoUrls)},0)">
      <img src="${esc(hero)}" alt="" loading="eager"/>
      ${zoom}${counter}
    </div>`;
    if (totalPhotos > 1) {
      const thumbs = photoUrls.slice(1, 9).map((u, i) =>
        `<div class="gallery-thumb" onclick="openLightbox(${JSON.stringify(photoUrls)},${i+1})">
          <img src="${esc(u)}" alt="" loading="lazy" data-loading="1" onload="this.removeAttribute('data-loading')"/>
        </div>`
      ).join('');
      photoBlock += `<div class="panel-gallery">${thumbs}</div>`;
    }
  } else {
    // No local hero — try broker URLs directly, or show placeholder
    if (photoUrls.length > 0) {
      const counter = `<span class="panel-hero-counter">1 of ${totalPhotos}</span>`;
      const zoom = `<span class="panel-hero-zoom"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg></span>`;
      photoBlock = `<div class="panel-hero" onclick="openLightbox(${JSON.stringify(photoUrls)},0)">
        <img src="${esc(photoUrls[0])}" alt="" loading="lazy"/>
        ${zoom}${counter}
      </div>`;
      if (totalPhotos > 1) {
        const thumbs = photoUrls.slice(1, 9).map((u, i) =>
          `<div class="gallery-thumb" onclick="openLightbox(${JSON.stringify(photoUrls)},${i+1})">
            <img src="${esc(u)}" alt="" loading="lazy" data-loading="1" onload="this.removeAttribute('data-loading')"/>
          </div>`
        ).join('');
        photoBlock += `<div class="panel-gallery">${thumbs}</div>`;
      }
    } else {
      const zoneColor = r.zone ? zoneColor_bg(r.zone) : '#E1F5EE';
      photoBlock = `<div class="panel-no-photo" style="background:linear-gradient(180deg,${zoneColor} 50%,var(--s2) 50%)">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 15l6-6 4 4 3-3 5 5"/><circle cx="8.5" cy="8.5" r="1.5"/></svg>
        <span>No photos available — <a href="${esc(r.url)}" target="_blank" rel="noopener" style="color:var(--accent)">view on ${esc(SOURCE_NAMES[r.source]||r.source)}</a></span>
      </div>`;
    }
  }
  return `${photoBlock}<div class="panel-full-title">${esc(r.title)}${warnHTML}</div>
    ${devTag}
    <div class="panel-meta">
      <div class="panel-meta-item"><span class="panel-meta-label">Zone</span><span class="panel-meta-value">${esc(zoneDisplay)}</span></div>
      <div class="panel-meta-item"><span class="panel-meta-label">Source</span><span class="panel-meta-value">${esc(SOURCE_NAMES[r.source]||r.source||'—')}</span></div>
      <div class="panel-meta-item"><span class="panel-meta-label">Price</span><span class="panel-meta-value">${fmtUSD(r.price_usd)}</span></div>
      <div class="panel-meta-item"><span class="panel-meta-label">Area</span><span class="panel-meta-value">${fmtArea(r.area_m2)}</span></div>
      <div class="panel-meta-item"><span class="panel-meta-label">$/m²</span><span class="panel-meta-value">${fmtPPM(r.price_per_m2)}</span></div>
      <div class="panel-meta-item"><span class="panel-meta-label">$/vrs²</span><span class="panel-meta-value">${fmtPPV2(r.price_per_m2)}</span></div>
      <div class="panel-meta-item"><span class="panel-meta-label">Listed</span><span class="panel-meta-value">${fmtDays(r.days_listed)}</span></div>
    </div>
    <div class="panel-section-label">Score ${renderStars(recomputeComposite(r))}</div>
    <div class="panel-scores" style="margin-top:8px">${scoreBars}</div>
    ${description}${brokerHTML}${cta}`;
}
function openPanel(r) {
  // Close the tune panel first — they share desktop layout space and only
  // one slide-in panel can be visible at a time without the table reflowing.
  closeTunePanel();
  OPEN_ID=r.source_id; pushURL(true);
  const html=panelHTML(r);
  if(window.innerWidth<=640){
    document.getElementById('mobile-panel-body').innerHTML=html;
    document.getElementById('mobile-overlay').classList.add('open');
  } else {
    document.getElementById('panel-body').innerHTML=html;
    document.getElementById('side-panel').classList.add('open');
  }
  document.querySelectorAll('tbody tr,.card').forEach(el=>
    el.classList.toggle('selected',el.dataset.id===r.source_id));
}
function closePanel() {
  OPEN_ID=null; pushURL(true);
  document.getElementById('side-panel').classList.remove('open');
  document.getElementById('mobile-overlay').classList.remove('open');
  document.querySelectorAll('tbody tr,.card').forEach(el=>el.classList.remove('selected'));
}

/* ── Tune panel (filters/sort) ───────────────────────── */
// The Tune panel is mutually exclusive with the listing-detail side panel:
// opening one closes the other so the layout never tries to host both.
function _rangeSectionHTML(opts) {
  // Generic range-slider section. Used for both Price and Size — anything
  // with snap-point indices and a paired (min, max) shape can plug in.
  const minLabel = opts.labels[opts.minIdx];
  const maxLabel = opts.labels[opts.maxIdx];
  const display  = `${minLabel} – ${maxLabel}`;
  const lastIdx  = opts.snaps.length - 1;
  // Overlay-fill positions (left/right percentages of the track).
  const fillLeft  = (opts.minIdx / lastIdx) * 100;
  const fillRight = ((lastIdx - opts.maxIdx) / lastIdx) * 100;
  const titleLow = opts.title.toLowerCase();
  const hint = opts.hint || '';
  return `
    <div class="tune-section">
      <div class="tune-section-title">${opts.title}</div>
      ${hint ? `<div class="tune-section-hint">${esc(hint)}</div>` : ''}
      <div class="tune-range-display" id="${opts.id}-range-display">${display}</div>
      <div class="tune-range-controls">
        <div class="tune-range-track"></div>
        <div class="tune-range-fill" id="${opts.id}-range-fill" style="left:${fillLeft}%;right:${fillRight}%"></div>
        <input type="range" id="${opts.id}-min" min="0" max="${lastIdx}" step="1" value="${opts.minIdx}" aria-label="Minimum ${titleLow}">
        <input type="range" id="${opts.id}-max" min="0" max="${lastIdx}" step="1" value="${opts.maxIdx}" aria-label="Maximum ${titleLow}">
      </div>
      ${opts.isDefault ? '' : `<button class="tune-reset" id="${opts.id}-reset" type="button">Reset ${titleLow}</button>`}
    </div>
  `;
}
// Per-slider hints — one line each, consistent verb pattern: "Right: X
// matters more · Left: less". The dimension labels in SCORE_DIMENSIONS
// already tell users what each one is; the hint just tells them which
// direction means "matters more."
const WEIGHT_SLIDER_HINTS = {
  value:    'Right: cheap-vs-comparable matters more · Left: less',
  location: 'Right: location matters more · Left: less',
  momentum: 'Right: market activity matters more · Left: less',
};
// One weight slider (label, 0–100 input, current value badge). Reuses the
// SCORE_DIMENSIONS palette so V/L/M look consistent everywhere they're
// surfaced. Returns just one row — multiple are stacked by _weightSectionHTML.
function _weightSliderHTML(slug, label, color) {
  const hint = WEIGHT_SLIDER_HINTS[slug] || '';
  return `
    <div class="weight-row">
      <label class="weight-name" for="weight-${slug}" style="border-left:3px solid ${color}">${esc(label)}</label>
      <input type="range" id="weight-${slug}" class="weight-slider" min="0" max="100" step="1" value="${WEIGHTS[slug]}" aria-label="${esc(label)} weight">
      <span class="weight-value" id="weight-${slug}-value">${WEIGHTS[slug]}</span>
    </div>
    ${hint ? `<div class="weight-hint">${esc(hint)}</div>` : ''}
  `;
}
// The whole weight-sliders section. Reads SCORE_DIMENSIONS for canonical
// labels + colors so the names here stay in sync with the score breakdown.
// Section title is provided by the .tune-section-divider rendered just
// above this in _tuneBodyHTML — that's also the visual break between
// filters (which narrow) and weights (which reorder).
function _weightSectionHTML() {
  const rows = SCORE_DIMENSIONS
    .map(([slug, name, color]) => _weightSliderHTML(slug, name, color))
    .join('');
  return `
    <div class="tune-section">
      ${rows}
      ${isDefaultWeights() ? '' : '<button class="tune-reset" id="weights-reset" type="button">Reset weights</button>'}
    </div>
  `;
}
function _zoneFilterSectionHTML() {
  // Containers for buildZoneFilter() to populate. The desktop and mobile
  // bodies both render this section, so we can't rely on a single id —
  // buildZoneFilter() now targets every .zone-filter on the page.
  // No hint here — the chip block is self-explanatory and a hint would
  // just take up vertical space.
  return `<div class="tune-section">
    <div class="tune-section-title">Zone</div>
    <div class="zone-filter"></div>
  </div>`;
}
function _minScoreSectionHTML() {
  // Single-handle slider [0..100]. At 0 it's a no-op; cranking it up
  // hides anything below the threshold. Useful for the curation use case
  // ("only show me listings strong enough to be worth a phone call").
  const isDefault = isDefaultMinScore();
  const display = MIN_SCORE === 0 ? 'Show all' : `≥ ${MIN_SCORE}`;
  return `
    <div class="tune-section">
      <div class="tune-section-title">Score floor</div>
      <div class="tune-section-hint">Hide listings below this score.</div>
      <div class="tune-range-display" id="min-score-display">${display}</div>
      <div class="tune-range-controls min-score-controls">
        <div class="tune-range-track"></div>
        <div class="tune-range-fill" id="min-score-fill" style="left:0;right:${100 - MIN_SCORE}%"></div>
        <input type="range" id="min-score-slider" min="0" max="100" step="1" value="${MIN_SCORE}" aria-label="Minimum score">
      </div>
      ${isDefault ? '' : `<button class="tune-reset" id="min-score-reset" type="button">Reset score floor</button>`}
    </div>
  `;
}
function _rerankingDividerHTML() {
  // Visual + verbal break between filters (which narrow what's shown) and
  // the weight sliders (which change the order). Section title comes from
  // the ::before pseudo-element on .tune-section-divider so the heading
  // floats inline with the rule.
  return `<div class="tune-section-divider"></div>
    <div class="tune-divider-hint">These sliders change the order, not what's shown.</div>`;
}
function _tuneBodyHTML() {
  // Composed from independent sections so adding a new filter is a one-line
  // append rather than a rewrite of the panel. Section order matches
  // mental model: where → how-much → how-big → how-good → reranking.
  return _zoneFilterSectionHTML() + _rangeSectionHTML({
    id: 'price', title: 'Price (USD)',
    snaps: PRICE_SNAPS, labels: PRICE_LABELS,
    minIdx: PRICE_MIN_IDX, maxIdx: PRICE_MAX_IDX,
    isDefault: isDefaultPriceRange(),
  }) + _rangeSectionHTML({
    id: 'size', title: 'Size (m²)',
    hint: 'Sizes shown in square meters (m²).',
    snaps: SIZE_SNAPS, labels: SIZE_LABELS,
    minIdx: SIZE_MIN_IDX, maxIdx: SIZE_MAX_IDX,
    isDefault: isDefaultSizeRange(),
  }) + _minScoreSectionHTML() + _rerankingDividerHTML() + _weightSectionHTML();
}
function _wireRangeSection(container, opts) {
  const minEl   = container.querySelector(`#${opts.id}-min`);
  const maxEl   = container.querySelector(`#${opts.id}-max`);
  const display = container.querySelector(`#${opts.id}-range-display`);
  const fill    = container.querySelector(`#${opts.id}-range-fill`);
  if (!minEl || !maxEl) return;
  const lastIdx = opts.snaps.length - 1;
  function update() {
    let lo = parseInt(minEl.value, 10);
    let hi = parseInt(maxEl.value, 10);
    // Crossover: whichever side the user is dragging pulls the other
    // along instead of locking up. Uses document.activeElement to detect
    // direction; falls back to clamping high to low.
    if (lo > hi) {
      if (document.activeElement === minEl) hi = lo;
      else lo = hi;
      minEl.value = lo; maxEl.value = hi;
    }
    opts.setMin(lo); opts.setMax(hi);
    display.textContent = `${opts.labels[lo]} – ${opts.labels[hi]}`;
    if (fill) {
      fill.style.left  = `${(lo / lastIdx) * 100}%`;
      fill.style.right = `${((lastIdx - hi) / lastIdx) * 100}%`;
    }
    pushURL(true); render(); _updateTuneButtonState();
  }
  minEl.addEventListener('input', update);
  maxEl.addEventListener('input', update);
  const reset = container.querySelector(`#${opts.id}-reset`);
  if (reset) reset.addEventListener('click', () => {
    opts.setMin(0); opts.setMax(lastIdx);
    renderTunePanel(); pushURL(true); render(); _updateTuneButtonState();
  });
}
function _wireWeightSliders(container) {
  // Wire one slider per dimension. On change: update WEIGHTS, refresh the
  // numeric badge, push URL, re-render — and auto-switch the sort to
  // "composite" if it isn't already, so the user sees their reweighting
  // take effect immediately. Otherwise the page stays sorted by whatever
  // it was (e.g. $/m² ascending), and the slider would silently no-op
  // from the user's POV. This was a real complaint in the wild.
  for (const [slug] of SCORE_DIMENSIONS) {
    const sliderEl = container.querySelector(`#weight-${slug}`);
    const valueEl  = container.querySelector(`#weight-${slug}-value`);
    if (!sliderEl || !valueEl) continue;
    sliderEl.addEventListener('input', () => {
      const v = parseInt(sliderEl.value, 10);
      WEIGHTS[slug] = Number.isInteger(v) ? v : WEIGHT_DEFAULTS[slug];
      valueEl.textContent = WEIGHTS[slug];
      // Snap the active sort to the live-weight composite so the table
      // visibly reorders. Reflect the change in the desktop sort-icons
      // and the mobile dropdown so the UI never lies about what's
      // actually being sorted.
      if (SORT_COL !== 'composite') {
        SORT_COL = 'composite';
        SORT_DIR = 'desc';
        updateSortHeaders();
      }
      pushURL(true); render(); _updateTuneButtonState();
    });
  }
  const reset = container.querySelector('#weights-reset');
  if (reset) reset.addEventListener('click', () => {
    Object.assign(WEIGHTS, WEIGHT_DEFAULTS);
    renderTunePanel(); pushURL(true); render(); _updateTuneButtonState();
  });
}
function _wireMinScore(container) {
  const sl = container.querySelector('#min-score-slider');
  const display = container.querySelector('#min-score-display');
  const fill = container.querySelector('#min-score-fill');
  if (!sl) return;
  const update = () => {
    const v = parseInt(sl.value, 10);
    MIN_SCORE = Number.isInteger(v) ? v : 0;
    if (display) display.textContent = MIN_SCORE === 0 ? 'Show all' : `≥ ${MIN_SCORE}`;
    if (fill) fill.style.right = `${100 - MIN_SCORE}%`;
    pushURL(true); render(); _updateTuneButtonState();
  };
  sl.addEventListener('input', update);
  const reset = container.querySelector('#min-score-reset');
  if (reset) reset.addEventListener('click', () => {
    MIN_SCORE = 0;
    renderTunePanel(); pushURL(true); render(); _updateTuneButtonState();
  });
}
function _wireTuneControls(container) {
  _wireRangeSection(container, {
    id: 'price', snaps: PRICE_SNAPS, labels: PRICE_LABELS,
    setMin: v => { PRICE_MIN_IDX = v; },
    setMax: v => { PRICE_MAX_IDX = v; },
  });
  _wireRangeSection(container, {
    id: 'size', snaps: SIZE_SNAPS, labels: SIZE_LABELS,
    setMin: v => { SIZE_MIN_IDX = v; },
    setMax: v => { SIZE_MAX_IDX = v; },
  });
  _wireMinScore(container);
  _wireWeightSliders(container);
}
function renderTunePanel() {
  const html = _tuneBodyHTML();
  const desktopBody = document.getElementById('tune-body');
  const mobileBody  = document.getElementById('mobile-tune-body');
  if (desktopBody) { desktopBody.innerHTML = html; _wireTuneControls(desktopBody); }
  if (mobileBody)  { mobileBody.innerHTML = html;  _wireTuneControls(mobileBody); }
  // The zone-filter section in the panel is empty until buildZoneFilter()
  // populates it. ALL_DATA is the in-memory dataset; mirrors the call from
  // render() which keeps the chips in sync with the active dataset.
  if (typeof ALL_DATA !== 'undefined' && Array.isArray(ALL_DATA)) {
    buildZoneFilter(ALL_DATA);
  }
}
function openTunePanel() {
  // Close the listing-detail panel first — they share desktop layout space.
  closePanel();
  renderTunePanel();
  if (window.innerWidth <= 640) {
    document.getElementById('mobile-tune-overlay').classList.add('open');
  } else {
    document.getElementById('tune-panel').classList.add('open');
  }
}
function closeTunePanel() {
  document.getElementById('tune-panel').classList.remove('open');
  document.getElementById('mobile-tune-overlay').classList.remove('open');
}
function _activeFilterCount() {
  // Counts non-default sections in the panel. Zone / Price / Size / Min
  // score / Weights — each section that's been touched contributes 1.
  // Grouped this way (rather than per-handle) so the badge reads as
  // "how many things did I change," not as a slider count.
  let n = 0;
  if (ZONE_F) n++;
  if (!isDefaultPriceRange()) n++;
  if (!isDefaultSizeRange()) n++;
  if (!isDefaultMinScore()) n++;
  if (!isDefaultWeights()) n++;
  return n;
}
function _updateTuneButtonState() {
  const btn = document.getElementById('tune-open');
  if (!btn) return;
  const count = _activeFilterCount();
  btn.classList.toggle('has-filters', count > 0);
  // Replace the prior dot-only indicator with a badge showing the count.
  // The button text is rebuilt rather than hunted-and-replaced because
  // the funnel SVG is also in there.
  let badge = btn.querySelector('.filter-count-badge');
  if (count > 0) {
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'filter-count-badge';
      btn.appendChild(badge);
    }
    badge.textContent = `· ${count}`;
  } else if (badge) {
    badge.remove();
  }
  // Toggle the "Clear all" link in the panel header — same active state.
  ['filters-reset-all-desktop', 'filters-reset-all-mobile'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.toggleAttribute('hidden', count === 0);
  });
}
function _resetAllFilters() {
  // Snap every panel-controlled state back to defaults.
  ZONE_F = null;
  PRICE_MIN_IDX = 0; PRICE_MAX_IDX = PRICE_SNAPS.length - 1;
  SIZE_MIN_IDX  = 0; SIZE_MAX_IDX  = SIZE_SNAPS.length - 1;
  MIN_SCORE = 0;
  Object.assign(WEIGHTS, WEIGHT_DEFAULTS);
  renderTunePanel(); pushURL(true); render(); _updateTuneButtonState();
}

/* ── Render ──────────────────────────────────────────── */
function renderTable(rows) {
  const tbody=document.getElementById('table-body');
  tbody.innerHTML=rows.map(r=>`
    <tr data-id="${esc(r.source_id)}" class="${r.source_id===OPEN_ID?'selected':''}">
      <td>${zonePillHTML(r)}${newBadgeHTML(r)}</td>
      <td class="td-num">${fmtUSD(r.price_usd)}</td>
      <td class="td-num">${fmtArea(r.area_m2)}</td>
      <td class="td-ppm">${fmtPPM(r.price_per_m2)}</td>
      <td class="td-stars">${renderStars(recomputeComposite(r))}</td>
      <td class="td-chev">›</td>
    </tr>`).join('');
  tbody.querySelectorAll('tr').forEach((tr,i)=>tr.addEventListener('click',()=>{
    if(OPEN_ID===rows[i].source_id){closePanel();return;}
    openPanel(rows[i]);
  }));
}
function renderCards(rows) {
  const wrap=document.getElementById('cards-wrap');
  wrap.innerHTML=rows.map(r=>`
    <div class="card" data-id="${esc(r.source_id)}" style="${r.source_id===OPEN_ID?'border-color:var(--accent);background:var(--accent-bg)':''}">
      <div class="card-zone-row">${zonePillHTML(r)}${newBadgeHTML(r)} ${renderStars(recomputeComposite(r))}</div>
      <div class="card-row2">
        <span>${fmtUSD(r.price_usd)}</span>
        <span>${fmtArea(r.area_m2)}</span>
        <span class="card-ppm">${fmtPPM(r.price_per_m2)}/m²</span>
      </div>
    </div>`).join('');
  wrap.querySelectorAll('.card').forEach((card,i)=>card.addEventListener('click',()=>openPanel(rows[i])));
}
function updateCounts(filtered, total) {
  const label=FILTER==='all'?'All listings':FILTER==='open'?'Open land':'Gated / developments';
  const zLabel=!ZONE_F?'':ZONE_F.type==='no-zone'?' · No zone':ZONE_F.type==='group'?` · ${ZONE_GROUPS[ZONE_F.value]?.label||''}`:(` · ${zoneLabel(ZONE_F.value)}`);
  document.getElementById('filter-count').innerHTML=`<strong>${filtered.toLocaleString()}</strong> of ${total.toLocaleString()} — ${label}${zLabel}`;
  document.getElementById('footer-count').textContent=`${filtered.toLocaleString()} listing${filtered!==1?'s':''}`;
}
function render() {
  const filtered=filteredRows(), sorted=sortedRows(filtered);
  updateSortHeaders(); updateCounts(filtered.length,ALL_DATA.length);
  buildZoneFilter(ALL_DATA);
  if(window.innerWidth>640) renderTable(sorted); else renderCards(sorted);
  if(OPEN_ID){const r=ALL_DATA.find(r=>r.source_id===OPEN_ID);if(r)openPanel(r);}
}

/* ── Wire events ─────────────────────────────────────── */
function wireSegment() {
  document.querySelectorAll('.seg-btn').forEach(btn=>{
    btn.classList.toggle('active',btn.dataset.filter===FILTER);
    btn.addEventListener('click',()=>{
      FILTER=btn.dataset.filter;
      document.querySelectorAll('.seg-btn').forEach(b=>b.classList.toggle('active',b===btn));
      OPEN_ID=null; document.getElementById('side-panel').classList.remove('open');
      pushURL(true); render();
    });
  });
}
function wireSortHeaders() {
  document.querySelectorAll('thead th.sortable').forEach(th=>th.addEventListener('click',()=>{
    const col=th.dataset.col;
    if(SORT_COL===col){SORT_DIR=SORT_DIR==='asc'?'desc':'asc';}
    else{SORT_COL=col;SORT_DIR=th.dataset.def||'asc';}
    pushURL(true); render();
  }));
}
function wireMobileSort() {
  const sel=document.getElementById('mobile-sort');
  sel.value=`${SORT_COL}_${SORT_DIR}`;
  sel.addEventListener('change',()=>{
    // Keep this regex in sync with readURL()'s match — both must accept the
    // same set of sort columns or selecting an option silently no-ops while
    // pushing the URL anyway. Newest was already broken here pre-Phase-7.
    const m=sel.value.match(/^(zone|price|area|ppm|stars|newest|deal|location|momentum)_(asc|desc)$/);
    if(m){SORT_COL=m[1];SORT_DIR=m[2];}
    pushURL(true); render();
  });
}
function wireClose() {
  document.getElementById('panel-close').addEventListener('click',closePanel);
  document.getElementById('mobile-close').addEventListener('click',closePanel);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closePanel();closeTunePanel();}});
  document.getElementById('table-wrap')?.addEventListener('click',e=>{if(!e.target.closest('tr')&&OPEN_ID)closePanel();});
}
function wireTune() {
  // Toggle: a second click on "Filters" closes the panel rather than re-opening it.
  document.getElementById('tune-open').addEventListener('click', () => {
    const panel = document.getElementById('tune-panel');
    const overlay = document.getElementById('mobile-tune-overlay');
    const isOpen = panel.classList.contains('open') || overlay.classList.contains('open');
    if (isOpen) closeTunePanel(); else openTunePanel();
  });
  document.getElementById('tune-close').addEventListener('click', closeTunePanel);
  document.getElementById('mobile-tune-close').addEventListener('click', closeTunePanel);
  // "Clear all" link — visible only when at least one filter is non-default.
  // Snaps every panel-controlled state back to defaults in one shot.
  ['filters-reset-all-desktop', 'filters-reset-all-mobile'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', _resetAllFilters);
  });
  _updateTuneButtonState();
}
let _lastMobile=window.innerWidth<=640;
window.addEventListener('resize',()=>{const m=window.innerWidth<=640;if(m!==_lastMobile){_lastMobile=m;render();}});

/* ── Meta ────────────────────────────────────────────── */
function fmtUpdated(isoStr) {
  const d = new Date(isoStr);
  const now = new Date();
  const time = d.toLocaleString('en-US', {hour:'numeric', minute:'2-digit', hour12:true});
  if (d.toDateString() === now.toDateString()) return `Today, ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;
  const date = d.toLocaleString('en-US', {month:'short', day:'numeric'});
  return `${date}, ${time}`;
}

async function loadMeta() {
  try {
    const meta=await fetch(META_URL,{cache:'no-store'}).then(r=>r.json());
    // Updated stat
    document.getElementById('hdr-updated').textContent = fmtUpdated(meta.last_updated);
    document.getElementById('footer-updated').textContent =
      new Date(meta.last_updated).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short'});
    // Listings stat
    const count = meta.total_listings || ALL_DATA.length;
    document.getElementById('hdr-listings').textContent = count.toLocaleString('en-US');
    // Sources stat
    const st=meta.source_status||{};
    const live=Object.values(st).filter(v=>v==='green').length;
    const total_src=Object.keys(st).length;
    if (total_src > 0) {
      document.getElementById('hdr-sources').textContent = `${live} / ${total_src} live`;
    }
  } catch {}
}

/* ── Methodology modal wiring ────────────────────────── */
// Imperative open/close so multiple call sites can share the modal without
// duplicating dialog-vs-fallback logic. Score-name labels in the side panel
// call openMethodologyModal() too — clicking a "Price vs Comps" / "Location"
// / "Momentum" name jumps straight here, replacing the prior cursor:help
// pattern that did nothing actionable on click.
function openMethodologyModal() {
  const dlg = document.getElementById('methodology-modal');
  if (!dlg) return;
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');  // older-browser fallback
}
function closeMethodologyModal() {
  const dlg = document.getElementById('methodology-modal');
  if (!dlg) return;
  if (typeof dlg.close === 'function') dlg.close();
  else dlg.removeAttribute('open');
}
function wireMethodology() {
  const dlg = document.getElementById('methodology-modal');
  const open = document.getElementById('open-methodology');
  const close = document.getElementById('close-methodology');
  if (!dlg || !open || !close) return;
  open.addEventListener('click', openMethodologyModal);
  close.addEventListener('click', closeMethodologyModal);
  // Click on backdrop closes (native dialogs treat backdrop clicks as on the
  // <dialog> element itself; clicks on inner content bubble to the inner box).
  dlg.addEventListener('click', e => { if (e.target === dlg) closeMethodologyModal(); });
  // Delegated click for any score-name button rendered later by panelHTML().
  // Keeps the handler stable across panel re-renders (which clobber the
  // score-name nodes each time openPanel() runs).
  document.body.addEventListener('click', e => {
    const t = e.target instanceof Element ? e.target.closest('.js-open-methodology') : null;
    if (t) openMethodologyModal();
  });
}

/* ── Filters help modal wiring ───────────────────────── */
// "?" buttons in the desktop and mobile Filters panel headers open a modal
// that explains each control point-by-point. Same <dialog> pattern as the
// methodology modal — backdrop + ESC close for free.
function wireFiltersHelp() {
  const dlg = document.getElementById('filters-help-modal');
  const close = document.getElementById('filters-help-close');
  if (!dlg || !close) return;
  const open = () => {
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
  };
  ['filters-help-desktop', 'filters-help-mobile'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener('click', open);
  });
  close.addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
}

/* ── Init ────────────────────────────────────────────── */
async function init() {
  readURL();
  try {
    ALL_DATA=await fetch(DATA_URL,{cache:'no-store'}).then(r=>r.json());
  } catch {
    document.getElementById('table-body').innerHTML=
      '<tr><td colspan="6" style="padding:40px;text-align:center;color:var(--t3)">Failed to load data.</td></tr>';
    return;
  }
  document.querySelectorAll('.seg-btn').forEach(btn=>btn.classList.toggle('active',btn.dataset.filter===FILTER));
  wireSegment(); wireSortHeaders(); wireMobileSort(); wireClose(); wireTune(); wireMethodology(); wireFiltersHelp();
  render(); loadMeta();
}
init();

/* ── inline-block #2 ── */
/* ── Lightbox ──────────────────────────────────────────────────────── */
(function(){
  let _urls=[], _idx=0;

  function _show(urls, idx){
    _urls=urls; _idx=idx;
    _render();
    document.getElementById('lightbox-wrap').classList.add('open');
    document.body.style.overflow='hidden';
  }
  function _render(){
    const img=document.getElementById('lb-img');
    img.src=_urls[_idx]||'';
    document.getElementById('lb-counter').textContent=_urls.length>1?`${_idx+1} of ${_urls.length}`:'';
    document.getElementById('lb-prev').style.display=_urls.length>1?'':'none';
    document.getElementById('lb-next').style.display=_urls.length>1?'':'none';
  }
  function _close(){
    document.getElementById('lightbox-wrap').classList.remove('open');
    document.body.style.overflow='';
    document.getElementById('lb-img').src='';
  }
  function _prev(){if(_urls.length>1){_idx=(_idx-1+_urls.length)%_urls.length;_render();}}
  function _next(){if(_urls.length>1){_idx=(_idx+1)%_urls.length;_render();}}

  document.getElementById('lb-close').addEventListener('click',_close);
  document.getElementById('lightbox-backdrop').addEventListener('click',_close);
  document.getElementById('lb-prev').addEventListener('click',_prev);
  document.getElementById('lb-next').addEventListener('click',_next);
  document.addEventListener('keydown',function(e){
    const open=document.getElementById('lightbox-wrap').classList.contains('open');
    if(!open)return;
    if(e.key==='Escape')_close();
    if(e.key==='ArrowLeft')_prev();
    if(e.key==='ArrowRight')_next();
  });

  // Expose globally so panelHTML() can open it
  window.openLightbox=_show;
})();