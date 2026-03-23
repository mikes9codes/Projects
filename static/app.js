/* ============================================================
   Dining Room Chair Search 2026  |  app.js
   ============================================================ */

'use strict';

// Source badge colours
const SOURCE_COLOURS = {
  'eBay':              '#e53238',
  'eBay UK':           '#c0392b',
  'eBay Canada':       '#c0392b',
  'eBay Australia':    '#c0392b',
  'eBay Germany':      '#c0392b',
  'eBay France':       '#c0392b',
  'eBay Italy':        '#c0392b',
  'Craigslist':        '#4a90d9',
  'Chairish':          '#c27d4c',
  '1stDibs':           '#1a1a2e',
  'Etsy':              '#f1641e',
  'LiveAuctioneers':   '#7c4dff',
  'Pamono':            '#2d6a4f',
};

let ALL_LISTINGS = [];
let LAST_UPDATED = null;

// ---------------------------------------------------------------------------
// Fetch & render
// ---------------------------------------------------------------------------

async function fetchListings() {
  try {
    const res = await fetch('/api/listings');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    ALL_LISTINGS  = data.listings || [];
    LAST_UPDATED  = data.last_updated;
    const stats   = data.search_stats || {};

    updateStats(stats);
    applyFilters();
    updateTimestamp();
  } catch (err) {
    console.error('fetchListings failed:', err);
    showStateMsg('usaGrid',  'error', '&#x26A0;', 'Could not load listings. Try refreshing.');
    showStateMsg('intlGrid', 'error', '&#x26A0;', 'Could not load listings. Try refreshing.');
  }
}

function updateStats(stats) {
  const usa   = ALL_LISTINGS.filter(l => l.is_usa);
  const intl  = ALL_LISTINGS.filter(l => !l.is_usa);
  const srcs  = new Set(ALL_LISTINGS.map(l => l.source));
  const priced = ALL_LISTINGS.filter(l => l.price_numeric);
  const avg   = priced.length ? priced.reduce((s,l)=>s+l.price_numeric,0)/priced.length : 0;

  set('statTotal',   ALL_LISTINGS.length || '\u2014');
  set('statUSA',     usa.length  || '\u2014');
  set('statIntl',    intl.length || '\u2014');
  set('statSources', srcs.size   || '\u2014');
  set('statAvgPrice', avg ? '$' + avg.toLocaleString('en-US', {maximumFractionDigits:0}) : '\u2014');
}

function updateTimestamp() {
  const el = document.getElementById('lastUpdated');
  if (!el) return;
  if (!LAST_UPDATED) { el.textContent = 'Never updated'; return; }
  const d = new Date(LAST_UPDATED);
  el.textContent = 'Updated ' + d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})
    + ' at ' + d.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
}

// ---------------------------------------------------------------------------
// Filters & sorting
// ---------------------------------------------------------------------------

function applyFilters() {
  let list = [...ALL_LISTINGS];

  const minP   = parseFloat(document.getElementById('minPrice').value) || 0;
  const maxP   = parseFloat(document.getElementById('maxPrice').value) || Infinity;
  const src    = document.getElementById('sourceFilter').value;
  const sort   = document.getElementById('sortBy').value;
  const cond   = document.getElementById('condFilter').value.toLowerCase();

  if (minP) list = list.filter(l => (l.price_numeric || 0) >= minP);
  if (maxP < Infinity) list = list.filter(l => !l.price_numeric || l.price_numeric <= maxP);
  if (src)  list = list.filter(l => l.source === src);
  if (cond) list = list.filter(l => (l.condition||'').toLowerCase().includes(cond));

  if (sort === 'price_asc')  list.sort((a,b) => (a.price_numeric||Infinity) - (b.price_numeric||Infinity));
  if (sort === 'price_desc') list.sort((a,b) => (b.price_numeric||0) - (a.price_numeric||0));
  if (sort === 'date')       list.sort((a,b) => (b.date_found||'').localeCompare(a.date_found||''));

  const usa  = list.filter(l =>  l.is_usa);
  const intl = list.filter(l => !l.is_usa);

  renderGrid('usaGrid',  usa);
  renderGrid('intlGrid', intl);

  set('usaBadge',  usa.length  + ' listing' + (usa.length  !== 1 ? 's' : ''));
  set('intlBadge', intl.length + ' listing' + (intl.length !== 1 ? 's' : ''));
}

function clearFilters() {
  document.getElementById('minPrice').value    = '';
  document.getElementById('maxPrice').value    = '';
  document.getElementById('sourceFilter').value = '';
  document.getElementById('sortBy').value      = 'price_asc';
  document.getElementById('condFilter').value  = '';
  applyFilters();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderGrid(id, listings) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!listings.length) {
    el.innerHTML = stateMsg('&#x1F4ED;', 'No listings match your filters.');
    return;
  }
  el.innerHTML = listings.map(buildCard).join('');
}

function buildCard(l) {
  const color   = SOURCE_COLOURS[l.source] || '#555';
  const hasImg  = l.image_url && l.image_url.startsWith('http');
  const priceHtml = l.price_numeric
    ? `<div class="card-price">${esc(l.price)}</div>`
    : `<div class="card-price no-price">${esc(l.price || 'Price on request')}</div>`;

  const imgHtml = hasImg
    ? `<img src="${esc(l.image_url)}" alt="${esc(l.title)}" loading="lazy"
            onerror="this.parentNode.innerHTML='<div class=\'card-no-img\'><span>&#x1FA91;</span><span>No Image</span></div>'">`
    : `<div class="card-no-img"><span>&#x1FA91;</span><span>No Image</span></div>`;

  const desc = l.description && l.description !== l.title
    ? `<p class="card-desc">${esc(l.description.slice(0,200))}${l.description.length>200?'&hellip;':''}</p>`
    : '';

  const flag = l.is_usa ? '&#x1F1FA;&#x1F1F8;' : '&#x1F30D;';

  return `
<div class="card">
  <div class="card-img">
    ${imgHtml}
    <span class="card-badge" style="background:${color}">${esc(l.source)}</span>
    ${l.condition ? `<span class="card-cond">${esc(l.condition)}</span>` : ''}
  </div>
  <div class="card-body">
    <h3 class="card-title">${esc(l.title)}</h3>
    ${priceHtml}
    <div class="card-meta">
      <span class="card-location">${flag} ${esc(l.location || l.country || '')}</span>
      <span class="card-type">${esc(l.source_type || '')}</span>
    </div>
    ${desc}
    <div class="card-footer">
      <span class="card-source-lbl">via ${esc(l.source)}</span>
      <a class="btn-view" href="${esc(l.listing_url)}" target="_blank" rel="noopener noreferrer">
        View Listing &rarr;
      </a>
    </div>
  </div>
</div>`;
}

// ---------------------------------------------------------------------------
// Refresh
// ---------------------------------------------------------------------------

async function refreshData() {
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="refresh-icon" style="animation:spin 1s linear infinite">&#x21BB;</span> Searching&hellip;';
  showToast('Running search across all platforms...');

  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    const data = await res.json();
    await fetchListings();
    showToast(`Done! Found ${data.total} listings.`);
  } catch (e) {
    showToast('Refresh failed. Please try again.');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="refresh-icon">&#x21BB;</span> Refresh Now';
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

function set(id, val) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = val;
}

function stateMsg(icon, msg, cls='') {
  return `<div class="state-msg ${cls}"><span class="icon">${icon}</span>${msg}</div>`;
}

function showStateMsg(gridId, cls, icon, msg) {
  const el = document.getElementById(gridId);
  if (el) el.innerHTML = stateMsg(icon, msg, cls);
}

function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3500);
}

// Add spin animation dynamically
const style = document.createElement('style');
style.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
document.head.appendChild(style);

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', fetchListings);
