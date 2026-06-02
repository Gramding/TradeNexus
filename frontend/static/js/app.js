const API = 'http://localhost:8765';

// ── State ────────────────────────────────────────────────────────────────────
let activeUserId   = null;
let activeUserName = null;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const userList          = document.getElementById('user-list');
const userListSpinner   = document.getElementById('user-list-spinner');
const userListError     = document.getElementById('user-list-error');
const emptyState        = document.getElementById('empty-state');
const userPanel         = document.getElementById('user-panel');
const userPanelName     = document.getElementById('user-panel-name');
const userPanelEmail    = document.getElementById('user-panel-email');
const btnDeleteUser     = document.getElementById('btn-delete-user');

const btnAddUser        = document.getElementById('btn-add-user');
const addUserForm       = document.getElementById('add-user-form');
const newUserName       = document.getElementById('new-user-name');
const newUserEmail      = document.getElementById('new-user-email');
const addUserError      = document.getElementById('add-user-error');
const btnSaveUser       = document.getElementById('btn-save-user');
const btnCancelUser     = document.getElementById('btn-cancel-user');

const tabBtns           = document.querySelectorAll('.tab-btn');
const tabPanels         = document.querySelectorAll('.tab-panel');

const filterTicker      = document.getElementById('filter-ticker');
const filterTradeType   = document.getElementById('filter-trade-type');
const filterAction      = document.getElementById('filter-action');
const filterDateFrom    = document.getElementById('filter-date-from');
const filterDateTo      = document.getElementById('filter-date-to');
const btnClearFilters   = document.getElementById('btn-clear-filters');
const tradesSpinner     = document.getElementById('trades-spinner');
const tradesError       = document.getElementById('trades-error');
const tradesTbody       = document.getElementById('trades-tbody');
const tradesEmpty       = document.getElementById('trades-empty');
const tradesTableWrap   = document.getElementById('trades-table-wrap');
const tradesCountHeader = document.getElementById('trades-count-header');
const tradesCountText   = document.getElementById('trades-count-text');
const tradesHeaderSpin  = document.getElementById('trades-header-spinner');
const tradesLoadmore    = document.getElementById('trades-loadmore');

// ── Shared list pagination helpers ──────────────────────────────────────────────
const fmtCount = (n) => Number(n).toLocaleString();

// Renders the footer of a paginated list: a "Load N more" button, an "all loaded"
// note, or a cap notice when the DOM row limit is reached.
//   state: { loaded, total, hasMore, capped, pageSize, nounP, capNotice, onMore }
function renderListFooter(el, state) {
  el.innerHTML = '';
  if (state.capped) {
    el.className = 'list-loadmore';
    el.innerHTML = `<div class="list-notice">${escHtml(state.capNotice)}</div>`;
    el.classList.remove('hidden');
    return;
  }
  if (state.hasMore) {
    const btn = document.createElement('button');
    btn.className = 'secondary load-more-btn';
    btn.textContent = i18n.t('common.load_more', { n: state.pageSize });
    btn.addEventListener('click', () => {
      btn.disabled = true;
      btn.innerHTML = `<span class="mini-spinner"></span> ${escHtml(i18n.t('common.loading'))}`;
      Promise.resolve(state.onMore()).catch(() => {});
    });
    el.appendChild(btn);
    el.classList.remove('hidden');
    return;
  }
  if (!state.loaded) { el.classList.add('hidden'); return; }
  el.innerHTML = `<div class="list-notice">${escHtml(i18n.t('common.all_loaded', { n: fmtCount(state.total), noun: state.nounP }))}</div>`;
  el.classList.remove('hidden');
}

const addTradeForm      = document.getElementById('add-trade-form');
const instrumentInput   = document.getElementById('trade-instrument');
const instrumentIdField = document.getElementById('trade-instrument-id');
const instrumentDropdown = document.getElementById('instrument-dropdown');
const instrumentChip    = document.getElementById('instrument-chip');
const tradeType         = document.getElementById('trade-type');
const tradeAction       = document.getElementById('trade-action');
const tradeQuantity     = document.getElementById('trade-quantity');
const tradePrice        = document.getElementById('trade-price');
const tradeDate         = document.getElementById('trade-date');
const tradeNotes        = document.getElementById('trade-notes');
const tradeBrokerEl     = document.getElementById('trade-broker');
const tradeCommission   = document.getElementById('trade-commission');
const tradeCommOverride = document.getElementById('trade-commission-override');
const tradeCommFormula  = document.getElementById('trade-commission-formula');
const contractFields    = document.getElementById('contract-fields');
const tradeMultiplier   = document.getElementById('trade-multiplier');
const tradeStrike       = document.getElementById('trade-strike');
const tradeExpiration   = document.getElementById('trade-expiration');
const tradeUnderlying   = document.getElementById('trade-underlying');
const totalPreview      = document.getElementById('total-preview');
const cashWarning       = document.getElementById('cash-warning');
const btnResetTrade     = document.getElementById('btn-reset-trade');
const btnSubmitTrade    = document.getElementById('btn-submit-trade');
const addTradeError     = document.getElementById('add-trade-error');

const analyticsSpinner  = document.getElementById('analytics-spinner');
const analyticsError    = document.getElementById('analytics-error');
const analyticsContent  = document.getElementById('analytics-content');

// ── Confirm modal ─────────────────────────────────────────────────────────────
const modalOverlay = document.getElementById('modal-overlay');
const modalMessage = document.getElementById('modal-message');
const modalConfirm = document.getElementById('modal-confirm');
const modalCancel  = document.getElementById('modal-cancel');

function confirmDialog(message, confirmLabel) {
  return new Promise(resolve => {
    modalMessage.textContent = message;
    const prevLabel = modalConfirm.textContent;
    if (confirmLabel) modalConfirm.textContent = confirmLabel;
    modalOverlay.classList.remove('hidden');

    function onConfirm() { cleanup(); resolve(true);  }
    function onCancel()  { cleanup(); resolve(false); }
    function onKey(e)    { if (e.key === 'Escape') { cleanup(); resolve(false); } }

    function cleanup() {
      modalOverlay.classList.add('hidden');
      modalConfirm.textContent = prevLabel;
      modalConfirm.removeEventListener('click', onConfirm);
      modalCancel.removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onKey);
    }

    modalConfirm.addEventListener('click', onConfirm);
    modalCancel.addEventListener('click', onCancel);
    document.addEventListener('keydown', onKey);
    modalConfirm.focus();
  });
}

// ── Toast ────────────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = isError ? 'error' : '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ── Inline errors ─────────────────────────────────────────────────────────────
function showError(el, msg) {
  el.textContent = msg;
  el.classList.remove('hidden');
}
function clearError(el) {
  el.textContent = '';
  el.classList.add('hidden');
}

// ── API helper ────────────────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const error = new Error(err.detail || res.statusText);
    error.status = res.status;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

// ── Settings ──────────────────────────────────────────────────────────────────
// appSettings + the formatters (formatCurrency/formatNumber/formatDate) live in
// formatting.js. Here we just load the server values into that shared object on
// startup; every formatter reads it live, so nothing needs rebuilding.
async function loadAppSettings() {
  try {
    const s = await apiFetch('/settings');
    Object.assign(appSettings, s);
  } catch (e) {
    console.warn('Failed to load settings, using defaults:', e.message);
  }
  updateGreeting();
}

function badge(value) {
  // Class is lowercased so styling matches regardless of stored casing
  // (e.g. trade_type "Stock" → badge-stock); the label keeps its original case.
  return `<span class="badge badge-${String(value).toLowerCase()}">${value}</span>`;
}

const SOURCE_LABELS = { yahoo_finance: 'Yahoo Finance' };
function sourceBadge(source) {
  const label = SOURCE_LABELS[source] || source;
  return `<span class="badge badge-${source.replace(/_/g, '-')}">${label}</span>`;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── External links + clickable quote tickers ──────────────────────────────────
// In Electron, preload.js exposes a hardened window.shell.openExternal. In a
// plain browser (dev) it's absent, so provide an https-only equivalent that opens
// a new tab. Either way, never open http://, javascript:, or file: URLs.
if (!window.shell) {
  window.shell = {
    openExternal: (url) => {
      if (typeof url === 'string' && url.startsWith('https://')) {
        window.open(url, '_blank', 'noopener,noreferrer');
      }
    },
  };
}

// Single guarded entry point for opening external links. Prefers the hardened
// window.shell bridge (Electron), but never throws if it's missing — e.g. when an
// older preload is still loaded after a renderer-only reload — falling back to a
// new tab. https-only at every layer.
function openExternalLink(url) {
  if (typeof url !== 'string' || !url.startsWith('https://')) return;
  if (window.shell && typeof window.shell.openExternal === 'function') {
    window.shell.openExternal(url);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

// Resolved {url, source, label} cached by key so repeated clicks never re-fetch.
const quoteUrlCache = new Map();

async function resolveQuoteUrl(key, path) {
  if (quoteUrlCache.has(key)) return quoteUrlCache.get(key);
  const data = await apiFetch(path);
  quoteUrlCache.set(key, data);
  return data;
}

// Descriptor builders → {key, path} for the two quote-url endpoints.
function tradeQuoteDesc(tradeId) {
  return { key: `trade:${tradeId}`, path: `/trades/${tradeId}/quote-url` };
}
function instrumentQuoteDesc(instrumentId, brokerId) {
  const q = brokerId != null ? `?broker_id=${brokerId}` : '';
  return { key: `instr:${instrumentId}:${brokerId ?? ''}`, path: `/instruments/${instrumentId}/quote-url${q}` };
}

// Inner markup for a clickable ticker. `text` is shown; `hint` is the pre-fetch
// tooltip (the instrument name when known). The ↗ icon reveals on hover/focus.
function tickerLinkHtml(text, hint) {
  const title = hint || i18n.t('quote.open_default');
  return `<span class="ticker-link" role="link" tabindex="0" title="${escHtml(title)}">`
    + `<span class="ticker-link-text">${escHtml(text)}</span>`
    + `<span class="ticker-link-icon" aria-hidden="true">↗</span>`
    + `</span>`;
}

// Wire a .ticker-link: on click/Enter resolve its quote URL (cached, fetched only
// on demand — never on render), open it externally, and upgrade the tooltip to the
// API label. The .loading class swaps the ↗ for a spinner via CSS.
function wireTickerLink(el, desc) {
  if (!el || !desc) return;
  const activate = async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (el.classList.contains('loading')) return;
    el.classList.add('loading');
    try {
      const data = await resolveQuoteUrl(desc.key, desc.path);
      if (data && data.label) el.setAttribute('title', data.label);
      if (data && data.url) openExternalLink(data.url);
    } catch (e) {
      showToast(i18n.t('quote.failed', { error: e.message }), true);
    } finally {
      el.classList.remove('loading');
    }
  };
  el.addEventListener('click', activate);
  el.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') activate(ev);
  });
}

// ── Icons ───────────────────────────────────────────────────────────────────────
// A single consistent line-icon set (Lucide-style: 24×24, 2px stroke, currentColor)
// so every control reads the same instead of the mismatched Unicode glyphs we had.
const ICONS = {
  edit:        '<path d="M17 3a2.828 2.828 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
  copy:        '<rect x="8" y="8" width="14" height="14" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  trash:       '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  close:       '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  download:    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  refresh:     '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M21 21v-5h-5"/>',
  chevronUp:   '<path d="m18 15-6-6-6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  settings:    '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  plus:        '<path d="M5 12h14"/><path d="M12 5v14"/>',
  alert:       '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  check:       '<path d="M20 6 9 17l-5-5"/>',
  arrowRight:  '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  search:      '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
};

function icon(name, cls = '') {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
         `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(name, opts = {}) {
  tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  tabPanels.forEach(p => {
    const active = p.id === 'tab-' + name;
    p.classList.toggle('active', active);
    p.classList.toggle('hidden', !active);
  });
  if (name === 'trades')     loadTrades();
  if (name === 'positions')  loadPositions();
  if (name === 'cash')     { loadCash(); loadEvents(); }
  if (name === 'analytics')  loadAnalytics();
  if (name === 'add-trade') {
    loadFormCashBalance();  // cache the balance once, on open (re-fetched each open)
    // duplicateTrade() loads brokers + fills the form itself, so it skips this.
    if (!opts.skipInit) {
      loadBrokerOptions(tradeBrokerEl).then(() => {
        applyDefaultBroker();          // pre-select the configured default broker
        updateAddTradeCommission();    // show its commission estimate immediately
      });
    }
  }
}

tabBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

// ── Users ─────────────────────────────────────────────────────────────────────
async function loadUsers() {
  userListSpinner.classList.remove('hidden');
  clearError(userListError);

  try {
    const users = await apiFetch('/users');
    renderUserList(users);
  } catch (e) {
    showError(userListError, 'Failed to load users: ' + e.message);
  } finally {
    userListSpinner.classList.add('hidden');
  }
}

function renderUserList(users) {
  userList.innerHTML = '';
  if (!users.length) {
    const li = document.createElement('li');
    li.className = 'empty-msg';
    li.textContent = i18n.t('app.no_users');
    userList.appendChild(li);
    return;
  }
  users.forEach(u => {
    const li = document.createElement('li');
    if (u.id === activeUserId) li.classList.add('active');

    const name  = document.createElement('div');
    name.className   = 'user-item-name';
    name.textContent = u.name;

    const email = document.createElement('div');
    email.className   = 'user-item-email';
    email.textContent = u.email;

    li.append(name, email);
    li.addEventListener('click', e => selectUser(u, e.currentTarget));
    userList.appendChild(li);
  });
}

function selectUser(u, li) {
  activeUserId   = u.id;
  activeUserName = u.name;

  document.querySelectorAll('#user-list li').forEach(el => el.classList.remove('active'));
  li.classList.add('active');

  document.querySelectorAll('.settings-nav-item').forEach(i => i.classList.remove('active'));
  document.getElementById('settings-panel').classList.add('hidden');

  emptyState.classList.add('hidden');
  userPanel.classList.remove('hidden');
  updateGreeting();
  userPanelName.textContent  = u.name;
  userPanelEmail.textContent = u.email;

  clearSearchInput();   // results are user-scoped — reset on user switch

  switchTab('trades');
}

// ── Dashboard greeting ────────────────────────────────────────────────────────
function updateGreeting() {
  const el = document.getElementById('dashboard-greeting');
  if (!el) return;
  const hour = new Date().getHours();
  const key = hour < 12 ? 'dashboard.greeting_morning'
            : hour < 18 ? 'dashboard.greeting_afternoon'
            : 'dashboard.greeting_evening';
  const name = (appSettings.display_name || 'Trader').trim() || 'Trader';
  el.textContent = i18n.t(key, { name });
}

// ── Delete user ───────────────────────────────────────────────────────────────
btnDeleteUser.addEventListener('click', async () => {
  const ok = await confirmDialog(
    i18n.t('app.delete_user_confirm', { name: activeUserName })
  );
  if (!ok) return;

  try {
    await apiFetch(`/users/${activeUserId}`, { method: 'DELETE' });
    activeUserId   = null;
    activeUserName = null;
    userPanel.classList.add('hidden');
    emptyState.classList.remove('hidden');
    showToast(i18n.t('app.user_deleted'));
    loadUsers();
  } catch (e) {
    showToast(e.message, true);
  }
});

// ── Add user ──────────────────────────────────────────────────────────────────
btnAddUser.addEventListener('click', () => {
  addUserForm.classList.toggle('hidden');
  clearError(addUserError);
  if (!addUserForm.classList.contains('hidden')) newUserName.focus();
});

btnCancelUser.addEventListener('click', () => {
  addUserForm.classList.add('hidden');
  newUserName.value = newUserEmail.value = '';
  clearError(addUserError);
});

btnSaveUser.addEventListener('click', saveUser);
[newUserName, newUserEmail].forEach(el =>
  el.addEventListener('keydown', e => { if (e.key === 'Enter') saveUser(); })
);

async function saveUser() {
  clearError(addUserError);
  const name  = newUserName.value.trim();
  const email = newUserEmail.value.trim();

  if (!name || !email) {
    showError(addUserError, i18n.t('app.name_email_required'));
    return;
  }

  btnSaveUser.disabled = true;
  try {
    await apiFetch('/users', { method: 'POST', body: JSON.stringify({ name, email }) });
    newUserName.value = newUserEmail.value = '';
    addUserForm.classList.add('hidden');
    showToast(i18n.t('app.user_created'));
    loadUsers();
  } catch (e) {
    showError(addUserError, e.message);
  } finally {
    btnSaveUser.disabled = false;
  }
}

// ── Trades table ──────────────────────────────────────────────────────────────
// ── Trades: cursor pagination + server-side sort ────────────────────────────────
const TRADES_PAGE = 100;       // page size
const TRADES_DOM_CAP = 500;    // never render more than this many rows at once

// Header sort-key -> the API's sort_by value. Columns absent here are NOT
// server-sortable (the API only sorts on these five), so their headers are made
// inert at init — client-sorting a single page would mislead on the full dataset.
const TRADE_SORT_API = {
  date:     'trade_date',
  ticker:   'ticker',
  quantity: 'quantity',
  price:    'price_per_unit',
  total:    'total_value',
};

let currentTrades = [];     // accumulated rows currently in the DOM
let tradesCursor  = null;
let tradesHasMore = false;
let tradesTotal   = 0;
let tradesLoading = false;
// Active sort, or null for the API default (trade_date desc, no arrow shown).
let activeSort = null;

function buildTradeParams() {
  const params = new URLSearchParams();
  const ticker = filterTicker.value.trim();
  if (ticker)               params.set('ticker', ticker);
  if (filterTradeType.value) params.set('trade_type', filterTradeType.value);
  if (filterAction.value)    params.set('action', filterAction.value);
  if (filterDateFrom.value)  params.set('date_from', filterDateFrom.value);
  if (filterDateTo.value)    params.set('date_to', filterDateTo.value);
  params.set('limit', String(TRADES_PAGE));
  if (activeSort) {
    params.set('sort_by', TRADE_SORT_API[activeSort.key]);
    params.set('sort_dir', activeSort.dir);
  }
  return params;
}

// Fetch page 1, resetting any loaded rows + cursor. opts.sortRefetch keeps the
// table visible and dims it (used for sort changes) instead of the big spinner.
function loadTrades(opts = {}) {
  if (!activeUserId) return Promise.resolve();
  tradesLoading = true;
  clearError(tradesError);

  if (opts.sortRefetch) {
    tradesTableWrap.classList.add('list-loading');
    tradesHeaderSpin.classList.remove('hidden');
  } else {
    tradesSpinner.classList.remove('hidden');
    tradesTableWrap.classList.add('hidden');
    tradesCountHeader.classList.add('hidden');
    tradesLoadmore.classList.add('hidden');
  }

  return apiFetch(`/users/${activeUserId}/trades?${buildTradeParams()}`)
    .then(resp => {
      currentTrades = resp.trades;
      tradesTotal   = resp.total_count;
      tradesHasMore = resp.has_more;
      tradesCursor  = resp.next_cursor;
      renderTradesRows(currentTrades, { append: false });
      updateTradesChrome();
      tradesTableWrap.classList.remove('hidden');
    })
    .catch(e => showError(tradesError, 'Failed to load trades: ' + e.message))
    .finally(() => {
      tradesLoading = false;
      tradesSpinner.classList.add('hidden');
      tradesTableWrap.classList.remove('list-loading');
      tradesHeaderSpin.classList.add('hidden');
    });
}

// Fetch the next page and append it (never replacing the existing rows), capping
// the DOM at TRADES_DOM_CAP rows.
function loadMoreTrades() {
  if (tradesLoading || !tradesHasMore) return Promise.resolve();
  if (currentTrades.length >= TRADES_DOM_CAP) return Promise.resolve();
  tradesLoading = true;

  const url = `/users/${activeUserId}/trades?${buildTradeParams()}` +
              `&cursor=${encodeURIComponent(tradesCursor)}`;
  return apiFetch(url)
    .then(resp => {
      let newRows = resp.trades;
      tradesHasMore = resp.has_more;
      tradesCursor  = resp.next_cursor;
      currentTrades = currentTrades.concat(newRows);
      if (currentTrades.length > TRADES_DOM_CAP) {
        const overflow = currentTrades.length - TRADES_DOM_CAP;
        currentTrades = currentTrades.slice(0, TRADES_DOM_CAP);
        newRows = newRows.slice(0, newRows.length - overflow);
      }
      renderTradesRows(newRows, { append: true });
    })
    .catch(e => showToast(i18n.t('common.load_more_failed', { error: e.message }), true))
    .finally(() => {
      tradesLoading = false;
      updateTradesChrome();   // restores the button (or swaps to notice / all-loaded)
    });
}

// Updates the "Showing X of Y" header and the load-more / cap-notice footer.
function updateTradesChrome() {
  const loaded = currentTrades.length;
  if (tradesTotal === 0) {
    tradesCountHeader.classList.add('hidden');
    tradesLoadmore.classList.add('hidden');
    return;
  }
  tradesCountHeader.classList.remove('hidden');
  tradesCountText.textContent = i18n.t('trades.showing', { shown: fmtCount(loaded), total: fmtCount(tradesTotal) });

  const capped = loaded >= TRADES_DOM_CAP && (tradesHasMore || tradesTotal > loaded);
  renderListFooter(tradesLoadmore, {
    loaded, total: tradesTotal,
    hasMore: tradesHasMore && !capped,
    capped, pageSize: TRADES_PAGE, nounP: i18n.t('common.nouns.trades'),
    capNotice: i18n.t('trades.cap_notice'),
    onMore: loadMoreTrades,
  });
}

function compareTradeValues(a, b, type) {
  if (type === 'number') {
    const na = Number(a), nb = Number(b);
    const va = Number.isFinite(na) ? na : -Infinity;   // null/undefined sort first
    const vb = Number.isFinite(nb) ? nb : -Infinity;
    return va - vb;
  }
  if (type === 'date') {
    return (Date.parse(a) || 0) - (Date.parse(b) || 0);
  }
  const sa = (a ?? '').toString().toLowerCase();
  const sb = (b ?? '').toString().toLowerCase();
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

function updateSortIndicators() {
  document.querySelectorAll('#trades-table th[data-sort-key]').forEach(th => {
    const arrow = th.querySelector('.sort-arrow');
    if (!arrow) return;
    if (activeSort && activeSort.key === th.dataset.sortKey) {
      arrow.innerHTML = icon(activeSort.dir === 'asc' ? 'chevronUp' : 'chevronDown', 'icon-sort');
    } else {
      arrow.innerHTML = '';
    }
  });
}

// Cursor pagination means we only hold one server-sorted page set, so sorting must
// happen on the server: each click resets the cursor and re-fetches from page 1.
function onSortHeaderClick(key) {
  if (!TRADE_SORT_API[key]) return;            // header isn't server-sortable
  if (!activeSort || activeSort.key !== key) {
    activeSort = { key, dir: 'asc' };          // 1st click: ascending
  } else if (activeSort.dir === 'asc') {
    activeSort = { key, dir: 'desc' };         // 2nd click: descending
  } else {
    activeSort = null;                         // 3rd click: back to default
  }
  updateSortIndicators();
  loadTrades({ sortRefetch: true });
}

// Disable headers the API can't sort on (so client sorting a single page never
// misleads); wire the rest to re-fetch from the server.
document.querySelectorAll('#trades-table th[data-sort-key]').forEach(th => {
  if (!TRADE_SORT_API[th.dataset.sortKey]) {
    th.removeAttribute('data-sort-key');
    const a = th.querySelector('.sort-arrow');
    if (a) a.remove();
  } else {
    th.addEventListener('click', () => onSortHeaderClick(th.dataset.sortKey));
  }
});

// Renders trade rows. append=false replaces the tbody (page 1); append=true adds
// the next page's rows without disturbing the existing ones.
function renderTradesRows(trades, { append }) {
  if (!append) {
    tradesTbody.innerHTML = '';
    if (!trades.length) {
      tradesEmpty.classList.remove('hidden');
      return;
    }
  }
  tradesEmpty.classList.add('hidden');

  trades.forEach(t => {
    const tr = document.createElement('tr');
    tr.dataset.tradeId = t.id;
    tr.innerHTML = `
      <td>${formatDate(t.trade_date)}</td>
      <td class="ticker-cell">
        ${exchangeBadge(t.exchange)}
        ${tickerLinkHtml(t.ticker.toUpperCase(), t.name)}
      </td>
      <td>${badge(t.trade_type)}</td>
      <td><span class="badge badge-${t.action}">${escHtml(i18n.t('trades.actions.' + t.action))}</span></td>
      <td class="num">${formatNumber(t.quantity)}</td>
      <td class="num">${formatCurrency(t.price_per_unit)}</td>
      <td class="num">${formatCurrency(t.total_value)}</td>
      <td class="num">${formatCurrency(t.commission ?? 0)}</td>
      <td class="num">${t.net_total_value != null ? formatCurrency(t.net_total_value) : '—'}</td>
      <td class="notes-cell" title="${escHtml(t.notes ?? '')}">${escHtml(t.notes ?? '—')}</td>
      <td>
        <button class="icon-btn edit-btn" title="${escHtml(i18n.t('trades.edit_title'))}" aria-label="${escHtml(i18n.t('trades.edit_title'))}">${icon('edit')}</button>
        <button class="icon-btn edit-btn dup-btn" title="${escHtml(i18n.t('trades.duplicate_title'))}" aria-label="${escHtml(i18n.t('trades.duplicate_title'))}">${icon('copy')}</button>
        <button class="icon-btn danger" title="${escHtml(i18n.t('trades.delete_title'))}" aria-label="${escHtml(i18n.t('trades.delete_title'))}">${icon('trash')}</button>
      </td>
    `;
    if (t.broker_color) {
      tr.style.setProperty('--broker-color', t.broker_color);
      tr.classList.add('has-broker-color');
    }
    tr.querySelector('.edit-btn').addEventListener('click', () => openEditTradeModal(t));
    tr.querySelector('.dup-btn').addEventListener('click', () => duplicateTrade(t));
    tr.querySelector('button.danger').addEventListener('click', () => deleteTrade(t.id, t.ticker));
    wireTickerLink(tr.querySelector('.ticker-link'), tradeQuoteDesc(t.id));
    tradesTbody.appendChild(tr);
  });

  consumeSearchHighlight('trade');   // flash a row if search navigated here
}

async function deleteTrade(id, ticker) {
  const ok = await confirmDialog(i18n.t('trades.delete_confirm', { ticker }));
  if (!ok) return;
  try {
    await apiFetch(`/trades/${id}`, { method: 'DELETE' });
    showToast(i18n.t('trades.deleted'));
    loadTrades();
  } catch (e) {
    showToast(e.message, true);
  }
}

// Pre-fill the Add-trade form from an existing trade so the user can log a similar
// one. Does NOT submit — the user reviews and confirms.
async function duplicateTrade(t) {
  // Switch to the form, but skip its async broker reload — we load brokers
  // ourselves below so the dropdown is fully populated before we select one.
  switchTab('add-trade', { skipInit: true });
  await loadBrokerOptions(tradeBrokerEl);

  // Duplicate as a free-text ticker; the user can re-pick from search for a
  // price lookup if they want to re-link an instrument.
  clearInstrumentSelection();
  instrumentInput.value = (t.ticker || '').toUpperCase();
  tradeType.value     = t.trade_type;
  tradeAction.value   = t.action;
  tradeQuantity.value = t.quantity;
  tradePrice.value    = t.price_per_unit;
  tradeBrokerEl.value = t.broker_id != null ? String(t.broker_id) : '';
  tradeNotes.value    = t.notes ?? '';
  tradeDate.value     = todayISO();   // new trade is logged today, not the original date

  // Clear the commission override so it auto-recalculates from the broker.
  tradeCommOverride.checked = false;
  tradeCommission.readOnly  = true;
  tradeCommission.classList.remove('editable');

  // Carry the contract details across for option duplicates (strike/expiration
  // describe the same contract; the user can adjust before submitting).
  updateContractFields();       // show/seed fields for this trade type
  if (isOptionType(t.trade_type)) {
    if (t.multiplier)      tradeMultiplier.value = t.multiplier;
    if (t.strike_price != null)   tradeStrike.value     = t.strike_price;
    if (t.expiration_date)        tradeExpiration.value = t.expiration_date;
    if (t.underlying)             tradeUnderlying.value = t.underlying;
  }

  updateAddTradeCommission();   // recompute commission estimate + formula
  updateTotalPreview();         // refresh the total preview from qty * price * multiplier

  addTradeForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
  tradeQuantity.focus();
  tradeQuantity.select();
}

// ── Filters ───────────────────────────────────────────────────────────────────
let filterDebounce = null;
filterTicker.addEventListener('input', () => {
  clearTimeout(filterDebounce);
  filterDebounce = setTimeout(loadTrades, 300);
});
filterTradeType.addEventListener('change', loadTrades);
filterAction.addEventListener('change', loadTrades);
filterDateFrom.addEventListener('change', () => loadTrades());
filterDateTo.addEventListener('change', () => loadTrades());

btnClearFilters.addEventListener('click', () => {
  filterTicker.value = '';
  filterTradeType.value = '';
  filterAction.value = '';
  filterDateFrom.value = '';
  filterDateTo.value = '';
  loadTrades();
});

document.getElementById('btn-export-csv').addEventListener('click', async () => {
  if (!activeUserId) return;
  const btn = document.getElementById('btn-export-csv');
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/users/${activeUserId}/trades/export`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      showToast(err.detail || i18n.t('trades.export_failed'), true);
      return;
    }
    const disposition = res.headers.get('Content-Disposition') ?? '';
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : `trades_user${activeUserId}.csv`;

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    showToast(i18n.t('trades.export_failed_detail', { error: e.message }), true);
  } finally {
    btn.disabled = false;
  }
});

// ── Option / contract fields ───────────────────────────────────────────────────
// Trade types that carry a standard 100x contract multiplier (matches the
// backend's OPTION_TRADE_TYPES). Comparison is case-insensitive.
const OPTION_TYPES = ['call', 'put'];
const DEFAULT_OPTION_MULTIPLIER = 100;

function isOptionType(name) {
  return OPTION_TYPES.includes(String(name || '').toLowerCase());
}

// The multiplier currently in effect: the explicit field value when the contract
// fields are showing, else 100 for Call/Put, else 1. Mirrors _resolve_multiplier.
function effectiveMultiplier() {
  if (!contractFields.classList.contains('hidden')) {
    const m = parseFloat(tradeMultiplier.value);
    if (m > 0) return m;
  }
  return isOptionType(tradeType.value) ? DEFAULT_OPTION_MULTIPLIER : 1;
}

// Show the contract fields for option types and default the multiplier to 100;
// hide and clear them otherwise. Keeps total preview + cash warning in sync.
function updateContractFields() {
  if (isOptionType(tradeType.value)) {
    contractFields.classList.remove('hidden');
    if (!tradeMultiplier.value) tradeMultiplier.value = DEFAULT_OPTION_MULTIPLIER;
  } else {
    contractFields.classList.add('hidden');
    tradeMultiplier.value = '';
    tradeStrike.value = '';
    tradeExpiration.value = '';
    tradeUnderlying.value = '';
  }
  updateTotalPreview();
  updateCashWarning();
}

tradeType.addEventListener('change', updateContractFields);
tradeMultiplier.addEventListener('input', () => { updateTotalPreview(); updateCashWarning(); });

// ── Total preview ─────────────────────────────────────────────────────────────
function updateTotalPreview() {
  const qty   = parseFloat(tradeQuantity.value);
  const price = parseFloat(tradePrice.value);
  totalPreview.textContent =
    (qty > 0 && price >= 0) ? formatCurrency(qty * price * effectiveMultiplier()) : '—';
}
tradeQuantity.addEventListener('input', updateTotalPreview);
tradePrice.addEventListener('input', updateTotalPreview);

// ── Passive price autofill ──────────────────────────────────────────────────────
// Look up a cached price (regardless of age, no live fetch) by Yahoo symbol and
// pre-fill the price field if the user hasn't typed one. Fires once per symbol.
const priceAutofillHint = document.getElementById('price-autofill-hint');
let lastAutofillTicker = '';

function hidePriceAutofillHint() {
  priceAutofillHint.classList.add('hidden');
  priceAutofillHint.textContent = '';
}

// "just now" / "5m ago" / "2h ago" / "3 days ago" from a UTC "YYYY-MM-DD HH:MM:SS".
function relativeAge(utcString) {
  const then = new Date(String(utcString).replace(' ', 'T') + 'Z').getTime();
  if (!Number.isFinite(then)) return '';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60)    return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60)    return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24)   return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

async function autofillPriceFromCache(symbol) {
  symbol = (symbol || '').trim().toUpperCase();

  if (!symbol) { lastAutofillTicker = ''; return; }   // cleared → allow re-fire later
  if (symbol === lastAutofillTicker) return;          // already handled this entry
  lastAutofillTicker = symbol;

  // Never overwrite a price the user typed themselves.
  if (tradePrice.value.trim() !== '') return;

  try {
    const data = await apiFetch(`/prices/${encodeURIComponent(symbol)}?cache_only=true`);
    if (!data || data.price == null) return;          // no cache → do nothing
    if (tradePrice.value.trim() !== '') return;       // user typed while we waited

    tradePrice.value = data.price;
    updateTotalPreview();
    updateCashWarning();

    priceAutofillHint.textContent =
      `Autofilled from cached price (${formatCurrency(data.price)} as of ${relativeAge(data.fetched_at)}). You can edit this.`;
    priceAutofillHint.classList.remove('hidden');
  } catch (e) {
    // Purely convenience — never surface an error (e.g. 404 = no cache).
  }
}

// Once the user edits the price, the "autofilled" note no longer applies.
tradePrice.addEventListener('input', hidePriceAutofillHint);

// ── Instrument search combobox ────────────────────────────────────────────────
// The Instrument field is a combobox: typing searches GET /instruments/search and
// shows a dropdown. Picking a result upserts it (POST /instruments), links it to
// the trade via a hidden instrument_id, and locks the input. Typing without
// picking falls back to a free-text ticker (no instrument_id) for unlisted names.
let selectedInstrument = null;       // the picked instrument row, or null in free-text mode
let instrumentSearchDebounce = null;
let instrumentSearchSeq = 0;         // guards against out-of-order async responses

// Title-case an asset_class for display: "stock" → "Stock", "etf" → "ETF".
function assetClassLabel(ac) {
  const s = String(ac || '').toLowerCase();
  if (s === 'etf') return 'ETF';
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}

function assetClassBadge(ac) {
  if (!ac) return '';
  return `<span class="badge badge-asset-${String(ac).toLowerCase()}">${escHtml(assetClassLabel(ac))}</span>`;
}

function exchangeBadge(exchange) {
  if (!exchange) return '';
  return `<span class="exchange-badge">${escHtml(exchange)}</span>`;
}

function hideInstrumentDropdown() {
  instrumentDropdown.classList.add('hidden');
  instrumentDropdown.innerHTML = '';
  instrumentInput.setAttribute('aria-expanded', 'false');
}

function renderInstrumentDropdown(data) {
  const results = (data && data.results) || [];
  let html = '';

  if (data && data.source === 'local_only' && data.warning) {
    html += `<div class="combobox-banner">${escHtml(i18n.t('trade_form.search_cached_only'))}</div>`;
  }

  if (!results.length) {
    html += `<div class="combobox-empty">${escHtml(i18n.t('trade_form.instrument_no_match'))}</div>`;
  } else {
    results.forEach((r, i) => {
      const name = r.name || r.ticker || r.symbol;
      html += `
        <div class="combobox-row" role="option" data-idx="${i}">
          ${exchangeBadge(r.exchange)}
          <span class="cb-symbol">${escHtml(r.symbol)}</span>
          <span class="cb-name">— ${escHtml(name)}</span>
          ${assetClassBadge(r.asset_class)}
        </div>`;
    });
  }

  instrumentDropdown.innerHTML = html;
  instrumentDropdown.classList.remove('hidden');
  instrumentInput.setAttribute('aria-expanded', 'true');

  // Select on mousedown (not click) + preventDefault so the input keeps focus and
  // the blur-driven free-text fallback never fires for a deliberate pick.
  instrumentDropdown.querySelectorAll('.combobox-row').forEach(row => {
    row.addEventListener('mousedown', (e) => {
      e.preventDefault();
      selectInstrument(results[parseInt(row.dataset.idx, 10)]);
    });
  });
}

async function runInstrumentSearch(q) {
  const seq = ++instrumentSearchSeq;
  try {
    const data = await apiFetch(`/instruments/search?q=${encodeURIComponent(q)}`);
    if (seq !== instrumentSearchSeq) return;   // a newer query superseded this one
    if (selectedInstrument) return;            // user already picked while waiting
    renderInstrumentDropdown(data);
  } catch (e) {
    hideInstrumentDropdown();
  }
}

async function selectInstrument(result) {
  let inst = result;
  // 1. Upsert the instrument locally so it has a stable id we can reference.
  try {
    inst = await apiFetch('/instruments', {
      method: 'POST',
      body: JSON.stringify({
        symbol:      result.symbol,
        ticker:      result.ticker,
        name:        result.name ?? null,
        exchange:    result.exchange ?? null,
        asset_class: result.asset_class || 'stock',
        currency:    result.currency || 'USD',
        isin:        result.isin ?? null,
      }),
    });
  } catch (e) {
    showToast(i18n.t('trade_form.instrument_save_failed', { error: e.message }), true);
    return;
  }

  selectedInstrument = inst;
  // 2 + 3. Set the hidden id and lock the input to a friendly label.
  instrumentIdField.value = inst.id;
  instrumentInput.value = `${inst.ticker} — ${inst.name || inst.ticker}`;
  instrumentInput.readOnly = true;
  instrumentInput.classList.add('has-selection');
  hideInstrumentDropdown();

  // 4. Auto-fill the trade type from the asset class (stock→Stock, crypto→Crypto,
  //    etf→ETF, …), creating the type if the user's list doesn't have it. It stays
  //    editable so an option on this instrument can still be tagged Call/Put.
  await ensureAndSelectTradeType(inst.asset_class);

  // 5. Price autofill by the instrument's Yahoo symbol.
  lastAutofillTicker = '';
  autofillPriceFromCache(inst.symbol);

  // 6. Confirmation chip.
  renderInstrumentChip(inst);
}

// Select the trade type matching an asset class, creating it on the fly if the
// user-fillable list doesn't have it yet (defaults are pre-seeded, so this is a
// safety net for deleted/unknown classes). Reloads the list so the new type shows
// in every dropdown.
async function ensureAndSelectTradeType(assetClass) {
  const ac = String(assetClass || '').toLowerCase();
  if (!ac) return;

  let match = tradeTypesList.find(t => t.name.toLowerCase() === ac);
  if (!match) {
    try {
      await apiFetch('/trade-types', { method: 'POST', body: JSON.stringify({ name: assetClassLabel(ac) }) });
    } catch (e) {
      // 409 (already exists) or any failure: fall through and re-read the list.
    }
    await loadTradeTypes();   // refresh tradeTypesList + repopulate dropdowns
    match = tradeTypesList.find(t => t.name.toLowerCase() === ac);
  }
  if (match) {
    tradeType.value = match.name;
    updateAddTradeCommission();
  }
}

function renderInstrumentChip(inst) {
  const parts = [inst.symbol];
  if (inst.exchange) parts.push(`on ${inst.exchange}`);
  let text = parts.join(' ');
  const tail = [];
  if (inst.currency) tail.push(inst.currency);
  if (inst.isin) tail.push(`ISIN: ${inst.isin}`);
  if (tail.length) text += ` · ${tail.join(' · ')}`;

  instrumentChip.innerHTML =
    `<span class="chip-text">${tickerLinkHtml(text, inst.name)}</span>` +
    `<button type="button" class="chip-clear" aria-label="Clear instrument">${icon('close')}</button>`;
  instrumentChip.classList.remove('hidden');
  // Open the quote for the picked instrument, honoring the broker chosen in the form.
  const chipBrokerId = tradeBrokerEl && tradeBrokerEl.value ? parseInt(tradeBrokerEl.value, 10) : null;
  wireTickerLink(instrumentChip.querySelector('.ticker-link'), instrumentQuoteDesc(inst.id, chipBrokerId));
  instrumentChip.querySelector('.chip-clear').addEventListener('click', () => clearInstrumentSelection({ focus: true }));
}

function clearInstrumentSelection({ focus = false } = {}) {
  selectedInstrument = null;
  instrumentIdField.value = '';
  instrumentInput.readOnly = false;
  instrumentInput.classList.remove('has-selection');
  instrumentInput.value = '';
  instrumentChip.classList.add('hidden');
  instrumentChip.innerHTML = '';
  hideInstrumentDropdown();
  lastAutofillTicker = '';
  if (focus) instrumentInput.focus();
}

instrumentInput.addEventListener('input', () => {
  if (selectedInstrument) return;            // locked while a selection is active
  clearTimeout(instrumentSearchDebounce);
  const q = instrumentInput.value.trim();
  if (q.length < 2) { hideInstrumentDropdown(); return; }
  instrumentSearchDebounce = setTimeout(() => runInstrumentSearch(q), 400);
});

instrumentInput.addEventListener('blur', () => {
  // Defer so a dropdown mousedown selection is processed before we hide it.
  setTimeout(() => {
    hideInstrumentDropdown();
    // Free-text fallback: a typed-but-unpicked entry doubles as the ticker, and we
    // still try a cached-price autofill keyed by that raw value (symbol == ticker).
    if (!selectedInstrument) autofillPriceFromCache(instrumentInput.value);
  }, 150);
});

// Escape closes the dropdown without committing anything.
instrumentInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !instrumentDropdown.classList.contains('hidden')) {
    e.preventDefault();
    hideInstrumentDropdown();
  }
});

// ── Add-trade commission ──────────────────────────────────────────────────────
function updateAddTradeCommission() {
  const broker = getBroker(tradeBrokerEl.value);
  const qty    = parseFloat(tradeQuantity.value) || 0;
  tradeCommFormula.textContent = commissionFormula(broker, qty, tradeType.value);
  // While auto (not overridden), mirror the estimate into the field
  if (!tradeCommOverride.checked) {
    tradeCommission.value = estimateCommission(broker, qty).toFixed(2);
  }
  updateCashWarning();  // commission affects the net total
}

// ── Cash-pool warning ─────────────────────────────────────────────────────────
// Cached balance loaded when the Add-trade form opens; null until first fetched.
let formCashBalance = null;

async function loadFormCashBalance() {
  if (!activeUserId) { formCashBalance = null; updateCashWarning(); return; }
  try {
    const cash = await apiFetch(`/users/${activeUserId}/cash`);
    formCashBalance = Number(cash.balance);
  } catch (e) {
    formCashBalance = null;  // on failure, just don't warn
    console.warn('Failed to load cash balance:', e.message);
  }
  updateCashWarning();
}

function updateCashWarning() {
  // Only relevant for buys, and only once we know the balance.
  if (tradeAction.value !== 'buy' || formCashBalance == null) {
    cashWarning.classList.add('hidden');
    return;
  }

  if (formCashBalance <= 0) {
    cashWarning.classList.add('soft');
    cashWarning.innerHTML = `${icon('alert', 'icon-inline')} Your cash pool is empty. Consider adding a deposit first.`;
    cashWarning.classList.remove('hidden');
    return;
  }

  const qty   = parseFloat(tradeQuantity.value)   || 0;
  const price = parseFloat(tradePrice.value)      || 0;
  const comm  = parseFloat(tradeCommission.value) || 0;
  const net   = qty * price * effectiveMultiplier() + comm;

  if (net > formCashBalance) {
    const over = net - formCashBalance;
    cashWarning.classList.remove('soft');
    // Values are formatted currency (no user input), so innerHTML is safe here.
    cashWarning.innerHTML =
      `${icon('alert', 'icon-inline')} This trade (${formatCurrency(net)}) would exceed your cash balance ` +
      `(${formatCurrency(formCashBalance)}) by ${formatCurrency(over)}`;
    cashWarning.classList.remove('hidden');
  } else {
    cashWarning.classList.add('hidden');
  }
}

tradeQuantity.addEventListener('input', updateCashWarning);
tradePrice.addEventListener('input', updateCashWarning);
tradeCommission.addEventListener('input', updateCashWarning);
tradeAction.addEventListener('change', updateCashWarning);

tradeCommOverride.addEventListener('change', () => {
  tradeCommission.readOnly = !tradeCommOverride.checked;
  tradeCommission.classList.toggle('editable', tradeCommOverride.checked);
  if (tradeCommOverride.checked) {
    tradeCommission.focus();
    tradeCommission.select();
  } else {
    updateAddTradeCommission();  // revert to auto estimate
  }
});

tradeBrokerEl.addEventListener('change', updateAddTradeCommission);
tradeQuantity.addEventListener('input', updateAddTradeCommission);
tradeType.addEventListener('change', updateAddTradeCommission);

// ── Add trade form ────────────────────────────────────────────────────────────
addTradeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!activeUserId) return;

  clearError(addTradeError);

  // Ticker comes from the picked instrument, or the raw free-text entry otherwise.
  const ticker = selectedInstrument
    ? selectedInstrument.ticker
    : instrumentInput.value.trim();

  const payload = {
    ticker:         ticker.toUpperCase(),
    trade_type:     tradeType.value,
    action:         tradeAction.value,
    // The form opens positions: a buy opens a long, a sell opens a short.
    direction:      tradeAction.value === 'sell' ? 'short' : 'long',
    quantity:       parseFloat(tradeQuantity.value),
    price_per_unit: parseFloat(tradePrice.value),
    trade_date:     tradeDate.value,
    notes:          tradeNotes.value.trim() || null,
    broker_id:      tradeBrokerEl.value ? parseInt(tradeBrokerEl.value) : null,
    instrument_id:  selectedInstrument ? selectedInstrument.id : null,
  };
  // Only send commission when the user has overridden it; otherwise the backend
  // auto-calculates from the broker.
  if (tradeCommOverride.checked) {
    payload.commission = parseFloat(tradeCommission.value) || 0;
  }

  // Contract details for option types. Multiplier is sent when explicitly set
  // (otherwise the backend defaults it from the trade type); strike/expiration/
  // underlying ride along when filled.
  if (!contractFields.classList.contains('hidden')) {
    const m = parseFloat(tradeMultiplier.value);
    if (m > 0) payload.multiplier = m;
    const strike = parseFloat(tradeStrike.value);
    if (strike >= 0 && tradeStrike.value !== '') payload.strike_price = strike;
    if (tradeExpiration.value) payload.expiration_date = tradeExpiration.value;
    if (tradeUnderlying.value.trim()) payload.underlying = tradeUnderlying.value.trim().toUpperCase();
  }

  btnSubmitTrade.disabled = true;
  try {
    await apiFetch(`/users/${activeUserId}/trades`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast(i18n.t('trades.added'));
    resetAddTradeForm();
    switchTab('trades');
  } catch (e) {
    showError(addTradeError, e.message);
  } finally {
    btnSubmitTrade.disabled = false;
  }
});

function resetAddTradeForm() {
  addTradeForm.reset();
  clearInstrumentSelection();    // drop any picked instrument + unlock the input
  totalPreview.textContent = '—';
  tradeCommOverride.checked = false;
  tradeCommission.readOnly  = true;
  tradeCommission.classList.remove('editable');
  applyDefaultBroker();          // reset restores the default broker too
  updateContractFields();        // hide/clear option fields for the (reset) type
  updateAddTradeCommission();
  clearError(addTradeError);
  hidePriceAutofillHint();
  lastAutofillTicker = '';       // a fresh form may autofill again
}

btnResetTrade.addEventListener('click', resetAddTradeForm);

// ── Analytics ─────────────────────────────────────────────────────────────────
const CHART_COLORS = {
  stock: '#4f8ef7',
  call:  '#a259ff',
  put:   '#ffaa33',
  other: '#7b8099',
};

// Distinct fallback palette so trade types with no explicit color still get
// different slices in the doughnut (cycled by position).
const TYPE_PALETTE = ['#4f8ef7','#a259ff','#ffaa33','#4caf82','#e6c84f','#2bb6c4','#e05c5c','#d98cff','#5fb0ff','#8a909e'];

// Resolve a chart color for a trade type by name: the user-set color from the
// trade_types table wins, then the legacy name map, then the cycling palette.
function tradeTypeColor(name, idx) {
  const t = tradeTypesList.find(x => x.name.toLowerCase() === String(name).toLowerCase());
  if (t && t.color) return t.color;
  return CHART_COLORS[String(name).toLowerCase()] || TYPE_PALETTE[idx % TYPE_PALETTE.length];
}

let chartMonthly   = null;
let chartByType    = null;
let chartGrowth    = null;
let growthDataFull = [];
let growthRange    = 'all';
let lastAnalyticsStats = null;   // cached so a language switch can re-render the cards

function chartScales() {
  const light = document.documentElement.dataset.theme === 'light';
  const tick  = light ? '#697180' : '#7b8099';
  const grid  = light ? '#ced3e2' : '#2a2f42';
  const axis  = {
    ticks:  { color: tick, font: { size: 11 } },
    grid:   { color: grid },
    border: { color: grid },
  };
  return { x: axis, y: { ...axis, ticks: { ...axis.ticks, callback: v => currencySymbol() + compactNum(v) } } };
}

function compactNum(v) {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
  if (v >= 1_000)     return (v / 1_000).toFixed(1) + 'K';
  return v;
}

async function loadAnalytics() {
  if (!activeUserId) return;

  analyticsContent.classList.add('hidden');
  analyticsSpinner.classList.remove('hidden');
  clearError(analyticsError);

  try {
    // Omit fiscal_year_start_month: the backend defaults to the same configured
    // setting, and omitting it lets the server serve the cached stats (passing an
    // explicit value bypasses the cache and re-runs every aggregation).
    const [s, growth] = await Promise.all([
      apiFetch(`/users/${activeUserId}/stats`),
      apiFetch(`/users/${activeUserId}/stats/growth`),
    ]);
    renderAnalytics(s);
    growthDataFull = growth;
    renderGrowthChart(filterGrowth(growth, growthRange));
    analyticsContent.classList.remove('hidden');
  } catch (e) {
    showError(analyticsError, 'Failed to load analytics: ' + e.message);
  } finally {
    analyticsSpinner.classList.add('hidden');
  }
}

function renderAnalytics(s) {
  lastAnalyticsStats = s;
  document.getElementById('stat-total-trades').textContent = s.total_trades;
  document.getElementById('stat-buy-volume').textContent   = formatCurrency(s.buy_volume);
  document.getElementById('stat-sell-volume').textContent  = formatCurrency(s.sell_volume);

  const netEl = document.getElementById('stat-net-position');
  netEl.textContent = formatCurrency(s.net_position);
  netEl.className   = 'stat-value ' + (s.net_position >= 0 ? 'positive' : 'negative');

  document.getElementById('stat-total-commissions').textContent = formatCurrency(s.total_commissions ?? 0);

  const netPnlEl = document.getElementById('stat-net-realized-pnl');
  netPnlEl.textContent = formatCurrency(s.net_realized_pnl ?? 0);
  netPnlEl.className    = 'stat-value ' + ((s.net_realized_pnl ?? 0) >= 0 ? 'positive' : 'negative');

  document.getElementById('stat-fiscal-volume').textContent = formatCurrency(s.this_fiscal_year_volume ?? 0);
  const fyStart = getFiscalYearRange().start;
  const fyMonth = i18n.t('settings.months.' + (fyStart.getMonth() + 1));
  document.getElementById('stat-fiscal-range').textContent = i18n.t('analytics.fiscal_range', { month: fyMonth, year: fyStart.getFullYear() });

  document.getElementById('stat-top-ticker').textContent = s.most_traded_ticker ?? '—';

  // Monthly bar chart
  if (chartMonthly) chartMonthly.destroy();
  chartMonthly = new Chart(document.getElementById('chart-monthly'), {
    type: 'bar',
    data: {
      labels: s.monthly_volume.map(m => m.month),
      datasets: [{
        data: s.monthly_volume.map(m => m.volume),
        backgroundColor: 'rgba(79,142,247,0.55)',
        borderColor: '#4f8ef7',
        borderWidth: 1,
        borderRadius: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ' ' + formatCurrency(ctx.parsed.y) } },
      },
      scales: chartScales(),
    },
  });

  // Doughnut chart
  const typeLabels = s.by_trade_type.map(t => t.trade_type);
  const typeColors = typeLabels.map((l, i) => tradeTypeColor(l, i));

  if (chartByType) chartByType.destroy();
  chartByType = new Chart(document.getElementById('chart-by-type'), {
    type: 'doughnut',
    data: {
      labels: typeLabels,
      datasets: [{
        data: s.by_trade_type.map(t => t.volume),
        backgroundColor: typeColors.map(c => c + 'bb'),
        borderColor: typeColors,
        borderWidth: 2,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: document.documentElement.dataset.theme === 'light' ? '#697180' : '#7b8099',
            font: { size: 12 }, padding: 14,
          },
        },
        tooltip: { callbacks: { label: ctx => ' ' + formatCurrency(ctx.parsed) } },
      },
    },
  });
}

// ── Growth chart ──────────────────────────────────────────────────────────────

// Local YYYY-MM-DD (avoids the UTC shift that toISOString() would introduce).
function _localISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Current fiscal year window based on appSettings.fiscal_year_start_month.
// Returns { start: Date, end: Date } where end is the exclusive next-FY start.
function getFiscalYearRange() {
  const startMonth = parseInt(appSettings.fiscal_year_start_month) || 1;   // 1-12
  const today = new Date();
  const year = (today.getMonth() + 1) >= startMonth ? today.getFullYear() : today.getFullYear() - 1;
  return {
    start: new Date(year, startMonth - 1, 1),
    end:   new Date(year + 1, startMonth - 1, 1),
  };
}

function filterGrowth(data, range) {
  if (range === 'all') return data;
  if (range === 'fy') {
    const { start, end } = getFiscalYearRange();
    const startStr = _localISO(start), endStr = _localISO(end);
    return data.filter(d => d.date >= startStr && d.date < endStr);
  }
  const months    = { '3m': 3, '6m': 6, '1y': 12 }[range];
  const cutoff    = new Date();
  cutoff.setMonth(cutoff.getMonth() - months);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return data.filter(d => d.date >= cutoffStr);
}

document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    growthRange = btn.dataset.range;
    if (growthDataFull.length) renderGrowthChart(filterGrowth(growthDataFull, growthRange));
  });
});

function renderGrowthChart(data) {
  const light     = document.documentElement.dataset.theme === 'light';
  const tick      = light ? '#697180' : '#7b8099';
  const grid      = light ? '#ced3e2' : '#2a2f42';
  const latestPnl = data.length ? data[data.length - 1].realized_pnl : 0;
  const pnlColor  = latestPnl >= 0 ? '#4caf82' : '#e05c5c';

  function pnlFill(ctx) {
    const { chart } = ctx;
    const { ctx: c, chartArea, scales } = chart;
    if (!chartArea) return 'transparent';
    const { top, bottom } = chartArea;
    if (bottom <= top) return 'transparent';

    const zeroY = scales.y.getPixelForValue(0);
    if (!isFinite(zeroY)) return 'transparent';

    const raw = (zeroY - top) / (bottom - top);
    // Clamp to [0.002, 0.998] so the ±0.001 neighbour stops never fall outside [0, 1]
    const pct = Math.max(0, Math.min(1, raw));

    const gradient = c.createLinearGradient(0, top, 0, bottom);
    if (pct <= 0) {
      gradient.addColorStop(0, 'rgba(224,92,92,0.18)');
      gradient.addColorStop(1, 'rgba(224,92,92,0.04)');
    } else if (pct >= 1) {
      gradient.addColorStop(0, 'rgba(76,175,130,0.18)');
      gradient.addColorStop(1, 'rgba(76,175,130,0.04)');
    } else {
      const lo = Math.max(0, pct - 0.001);
      const hi = Math.min(1, pct + 0.001);
      gradient.addColorStop(0,   'rgba(76,175,130,0.18)');
      gradient.addColorStop(lo,  'rgba(76,175,130,0.04)');
      gradient.addColorStop(pct, 'rgba(0,0,0,0)');
      gradient.addColorStop(hi,  'rgba(224,92,92,0.04)');
      gradient.addColorStop(1,   'rgba(224,92,92,0.18)');
    }
    return gradient;
  }

  const dot = { pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 10 };

  if (chartGrowth) chartGrowth.destroy();
  chartGrowth = new Chart(document.getElementById('chart-growth'), {
    type: 'line',
    data: {
      datasets: [
        {
          label:           i18n.t('analytics.series_cost_basis'),
          data:            data.map(d => ({ x: d.date, y: d.cost_basis })),
          borderColor:     '#4f8ef7',
          backgroundColor: 'rgba(79,142,247,0.07)',
          fill:            false,
          borderWidth:     2,
          tension:         0.3,
          ...dot,
        },
        {
          label:           i18n.t('analytics.series_realized_pnl'),
          data:            data.map(d => ({ x: d.date, y: d.realized_pnl })),
          borderColor:     pnlColor,
          backgroundColor: pnlFill,
          fill:            'origin',
          borderWidth:     2,
          tension:         0.3,
          ...dot,
        },
      ],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction:         { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: {
            color:           tick,
            font:            { size: 12 },
            padding:         16,
            usePointStyle:   true,
            pointStyleWidth: 12,
          },
        },
        tooltip: {
          callbacks: {
            title: items => new Date(items[0].parsed.x).toLocaleDateString('en-US', {
              year: 'numeric', month: 'short', day: 'numeric',
            }),
            label: ctx => ` ${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: {
            displayFormats: {
              day:     'MMM d',
              week:    'MMM d',
              month:   'MMM yyyy',
              quarter: 'MMM yyyy',
              year:    'yyyy',
            },
          },
          ticks:  { color: tick, font: { size: 11 }, maxTicksLimit: 12 },
          grid:   { color: grid },
          border: { color: grid },
        },
        y: {
          ticks:  { color: tick, font: { size: 11 }, callback: v => currencySymbol() + compactNum(v) },
          grid:   { color: grid },
          border: { color: grid },
        },
      },
    },
  });
}

// ── Positions ─────────────────────────────────────────────────────────────────
const positionsSpinner     = document.getElementById('positions-spinner');
const positionsError       = document.getElementById('positions-error');
const positionsContent     = document.getElementById('positions-content');
const positionsTbody       = document.getElementById('positions-tbody');
const positionsEmpty       = document.getElementById('positions-empty');
const positionsCashBalance = document.getElementById('positions-cash-balance');
const posFilterTicker       = document.getElementById('pos-filter-ticker');
const posFilterAsset        = document.getElementById('pos-filter-asset');
const posFilterType         = document.getElementById('pos-filter-type');
const posFilterBroker       = document.getElementById('pos-filter-broker');
const posSplitBroker        = document.getElementById('pos-split-broker');
const btnClearPositionFilters = document.getElementById('btn-clear-position-filters');

// "Split by broker" is a display preference (not a filter), persisted across
// sessions. Defaults on: holdings spread across brokers show as separate rows.
posSplitBroker.checked = localStorage.getItem('positionsSplitByBroker') !== '0';
posSplitBroker.addEventListener('change', () => {
  localStorage.setItem('positionsSplitByBroker', posSplitBroker.checked ? '1' : '0');
  applyPositionSort();
});

// ── Add cash (deposit) ──────────────────────────────────────────────────────────
const btnAddCash    = document.getElementById('btn-add-cash');
const addCashForm   = document.getElementById('add-cash-form');
const addCashAmount = document.getElementById('add-cash-amount');
const addCashNote   = document.getElementById('add-cash-note');

function closeAddCashForm() {
  addCashForm.classList.add('hidden');
  btnAddCash.classList.remove('hidden');
}

btnAddCash.addEventListener('click', () => {
  addCashForm.classList.remove('hidden');
  btnAddCash.classList.add('hidden');
  addCashAmount.value = '';
  addCashNote.value = '';
  addCashAmount.focus();
});

document.getElementById('btn-cancel-cash').addEventListener('click', closeAddCashForm);

addCashForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!activeUserId) return;
  const amount = parseFloat(addCashAmount.value);
  if (!(amount > 0)) { showToast(i18n.t('cash.amount_invalid'), true); return; }

  const saveBtn = document.getElementById('btn-save-cash');
  saveBtn.disabled = true;
  try {
    const res = await apiFetch(`/users/${activeUserId}/cash/deposit`, {
      method: 'POST',
      body: JSON.stringify({ amount, note: addCashNote.value.trim() || null }),
    });
    setCashBalance(res.balance);
    showToast(i18n.t('cash.added', { amount: formatCurrency(amount) }));
    closeAddCashForm();
    loadCash();   // refresh the history so the new deposit appears
  } catch (err) {
    showToast(err.message, true);
  } finally {
    saveBtn.disabled = false;
  }
});

// ── Cash tab: balance + paginated transaction history ───────────────────────────
const CASH_PAGE = 50;
const CASH_DOM_CAP = 500;
const cashBalanceValue = document.getElementById('cash-balance-value');
const cashSpinner      = document.getElementById('cash-spinner');
const cashError        = document.getElementById('cash-error');
const cashTbody        = document.getElementById('cash-tbody');
const cashEmpty        = document.getElementById('cash-empty');
const cashTableWrap    = document.getElementById('cash-table-wrap');
const cashCountHeader  = document.getElementById('cash-count-header');
const cashCountText    = document.getElementById('cash-count-text');
const cashLoadmore     = document.getElementById('cash-loadmore');

let cashTransactions = [];
let cashCursor  = null;
let cashHasMore = false;
let cashTotal   = 0;
let cashLoading = false;

// Mirror the balance into both the Cash tab and the Positions tab displays.
function setCashBalance(v) {
  if (v == null) return;
  positionsBalance = v;
  const txt = formatCurrency(v);
  if (cashBalanceValue)     cashBalanceValue.textContent = txt;
  if (positionsCashBalance) positionsCashBalance.textContent = txt;
}

function loadCash() {
  if (!activeUserId) return Promise.resolve();
  cashLoading = true;
  clearError(cashError);
  cashSpinner.classList.remove('hidden');
  cashTableWrap.classList.add('hidden');
  cashCountHeader.classList.add('hidden');
  cashLoadmore.classList.add('hidden');

  return apiFetch(`/users/${activeUserId}/cash?limit=${CASH_PAGE}`)
    .then(resp => {
      setCashBalance(resp.balance);
      cashTransactions = resp.transactions;
      cashTotal   = resp.total_count;
      cashHasMore = resp.has_more;
      cashCursor  = resp.next_cursor;
      renderCashRows(cashTransactions, { append: false });
      updateCashChrome();
      cashTableWrap.classList.remove('hidden');
    })
    .catch(e => showError(cashError, 'Failed to load cash: ' + e.message))
    .finally(() => { cashLoading = false; cashSpinner.classList.add('hidden'); });
}

function loadMoreCash() {
  if (cashLoading || !cashHasMore) return Promise.resolve();
  if (cashTransactions.length >= CASH_DOM_CAP) return Promise.resolve();
  cashLoading = true;

  const url = `/users/${activeUserId}/cash?limit=${CASH_PAGE}` +
              `&cursor=${encodeURIComponent(cashCursor)}`;
  return apiFetch(url)
    .then(resp => {
      let newRows = resp.transactions;
      cashHasMore = resp.has_more;
      cashCursor  = resp.next_cursor;
      cashTransactions = cashTransactions.concat(newRows);
      if (cashTransactions.length > CASH_DOM_CAP) {
        const overflow = cashTransactions.length - CASH_DOM_CAP;
        cashTransactions = cashTransactions.slice(0, CASH_DOM_CAP);
        newRows = newRows.slice(0, newRows.length - overflow);
      }
      renderCashRows(newRows, { append: true });
    })
    .catch(e => showToast(i18n.t('common.load_more_failed', { error: e.message }), true))
    .finally(() => { cashLoading = false; updateCashChrome(); });
}

function renderCashRows(rows, { append }) {
  if (!append) {
    cashTbody.innerHTML = '';
    if (!rows.length) { cashEmpty.classList.remove('hidden'); return; }
  }
  cashEmpty.classList.add('hidden');
  rows.forEach(c => {
    const tr = document.createElement('tr');
    const cls  = c.amount >= 0 ? 'pnl-pos' : 'pnl-neg';
    const sign = c.amount > 0 ? '+' : '';
    const typeLabel = i18n.t('cash.types.' + c.transaction_type);
    tr.innerHTML = `
      <td>${formatDate(c.created_at)}</td>
      <td><span class="badge badge-${c.transaction_type.replace(/_/g, '-')}">${escHtml(typeLabel)}</span></td>
      <td class="num ${cls}">${sign}${formatCurrency(c.amount)}</td>
      <td class="notes-cell" title="${escHtml(c.note ?? '')}">${escHtml(c.note ?? '—')}</td>
    `;
    cashTbody.appendChild(tr);
  });
}

function updateCashChrome() {
  const loaded = cashTransactions.length;
  if (cashTotal === 0) {
    cashCountHeader.classList.add('hidden');
    cashLoadmore.classList.add('hidden');
    return;
  }
  cashCountHeader.classList.remove('hidden');
  cashCountText.textContent = i18n.t('cash.showing', { shown: fmtCount(loaded), total: fmtCount(cashTotal) });

  const capped = loaded >= CASH_DOM_CAP && (cashHasMore || cashTotal > loaded);
  renderListFooter(cashLoadmore, {
    loaded, total: cashTotal,
    hasMore: cashHasMore && !capped,
    capped, pageSize: CASH_PAGE, nounP: i18n.t('common.nouns.transactions'),
    capNotice: i18n.t('cash.cap_notice'),
    onMore: loadMoreCash,
  });
}

document.getElementById('btn-goto-cash').addEventListener('click', () => switchTab('cash'));

async function loadPositions() {
  if (!activeUserId) return;

  positionsSpinner.classList.remove('hidden');
  positionsContent.classList.add('hidden');
  clearError(positionsError);

  try {
    const [positions, cash] = await Promise.all([
      apiFetch(`/users/${activeUserId}/positions/prices`),
      apiFetch(`/users/${activeUserId}/cash`),
      ensureBrokers(),  // so the sell modal can estimate commissions
    ]);
    renderPositions(positions, cash.balance);
    updatePricesLabel(positions);
    positionsContent.classList.remove('hidden');
  } catch (e) {
    showError(positionsError, 'Failed to load positions: ' + e.message);
  } finally {
    positionsSpinner.classList.add('hidden');
  }
}

// ── Events: dividends, splits, interest, fees ──────────────────────────────────
const eventsTbody     = document.getElementById('events-tbody');
const eventsEmpty     = document.getElementById('events-empty');
const eventsList      = document.getElementById('event-instrument-list');
const addEventForm    = document.getElementById('add-event-form');
const eventTypeEl     = document.getElementById('event-type');
const eventDateEl     = document.getElementById('event-date');
const eventInstrEl    = document.getElementById('event-instrument');
const eventInstrRow   = document.getElementById('event-instrument-row');
const eventAmountEl   = document.getElementById('event-amount');
const eventRatioEl    = document.getElementById('event-ratio');
const eventRatioHint  = document.getElementById('event-ratio-hint');
const eventNoteEl     = document.getElementById('event-note');
const eventError      = document.getElementById('add-event-error');

let _instrumentsByTicker = new Map();

async function loadEvents() {
  if (!activeUserId) return;
  // Refresh the instrument datalist once per session-ish (cheap call); the form
  // resolves ticker -> instrument_id from this map on submit.
  try {
    const instruments = await apiFetch('/instruments');
    _instrumentsByTicker = new Map(instruments.map(i => [String(i.ticker).toUpperCase(), i]));
    eventsList.innerHTML = instruments
      .map(i => `<option value="${escHtml(i.ticker)}">${escHtml(i.name || i.ticker)}</option>`)
      .join('');
  } catch (e) {
    console.warn('Failed to load instruments for events form:', e.message);
  }
  try {
    const events = await apiFetch(`/users/${activeUserId}/events`);
    renderEvents(events);
  } catch (e) {
    showToast(e.message, true);
  }
}

function renderEvents(events) {
  eventsTbody.innerHTML = '';
  if (!events.length) { eventsEmpty.classList.remove('hidden'); return; }
  eventsEmpty.classList.add('hidden');
  events.forEach(e => {
    const tr = document.createElement('tr');
    const typeLabel = i18n.t('events.type_' + e.event_type);
    const detail = e.event_type === 'split'
      ? `${formatNumber(e.ratio, 4)}×`
      : formatCurrencyIn(e.amount * (e.event_type === 'fee' ? -1 : 1), e.currency);
    tr.innerHTML = `
      <td>${formatDate(e.event_date)}</td>
      <td><span class="badge badge-${e.event_type}">${escHtml(typeLabel)}</span></td>
      <td>${escHtml(e.ticker || '—')}</td>
      <td class="num">${detail}</td>
      <td class="notes-cell" title="${escHtml(e.note ?? '')}">${escHtml(e.note ?? '—')}</td>
      <td><button class="event-delete-btn secondary" data-id="${e.id}">×</button></td>
    `;
    tr.querySelector('.event-delete-btn').addEventListener('click', () => deleteEvent(e.id));
    eventsTbody.appendChild(tr);
  });
}

async function deleteEvent(id) {
  if (!confirm(i18n.t('events.delete_confirm'))) return;
  try {
    await apiFetch(`/events/${id}`, { method: 'DELETE' });
    showToast(i18n.t('events.deleted'));
    loadEvents();
    loadCash();      // cash balance changed
  } catch (e) {
    showToast(e.message, true);
  }
}

// Show only the fields each event type needs: instrument is required for
// dividend/split, amount is for everything except split, ratio is only split.
function updateEventFormFields() {
  const type = eventTypeEl.value;
  const isSplit = type === 'split';
  const needsInstrument = type === 'dividend' || type === 'split';
  eventInstrRow.classList.toggle('hidden', !needsInstrument);
  eventAmountEl.classList.toggle('hidden', isSplit);
  eventRatioEl.classList.toggle('hidden', !isSplit);
  eventRatioHint.classList.toggle('hidden', !isSplit);
  if (isSplit) {
    eventAmountEl.removeAttribute('required');
    eventRatioEl.setAttribute('required', '');
  } else {
    eventAmountEl.setAttribute('required', '');
    eventRatioEl.removeAttribute('required');
  }
  eventAmountEl.placeholder = i18n.t(type === 'dividend' ? 'events.amount_per_share' : 'events.amount_total');
}

document.getElementById('btn-add-event').addEventListener('click', () => {
  addEventForm.classList.toggle('hidden');
  if (!addEventForm.classList.contains('hidden')) {
    eventDateEl.value = todayISO();
    updateEventFormFields();
    eventTypeEl.focus();
  }
});

document.getElementById('btn-cancel-event').addEventListener('click', () => {
  addEventForm.reset();
  addEventForm.classList.add('hidden');
  clearError(eventError);
});

eventTypeEl.addEventListener('change', updateEventFormFields);

addEventForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!activeUserId) return;
  clearError(eventError);
  const type = eventTypeEl.value;
  const payload = { event_type: type, event_date: eventDateEl.value, note: eventNoteEl.value.trim() || null };
  if (type === 'dividend' || type === 'split') {
    const inst = _instrumentsByTicker.get(eventInstrEl.value.trim().toUpperCase());
    if (!inst) {
      showError(eventError, i18n.t('events.save_failed', { error: `Unknown instrument: ${eventInstrEl.value}` }));
      return;
    }
    payload.instrument_id = inst.id;
  }
  if (type === 'split') payload.ratio = parseFloat(eventRatioEl.value);
  else                  payload.amount = parseFloat(eventAmountEl.value);

  const btn = document.getElementById('btn-save-event');
  btn.disabled = true;
  try {
    await apiFetch(`/users/${activeUserId}/events`, { method: 'POST', body: JSON.stringify(payload) });
    showToast(i18n.t('events.added'));
    addEventForm.reset();
    addEventForm.classList.add('hidden');
    loadEvents();
    loadCash();
    if (type === 'split') loadPositions();   // split adjusts open lots
  } catch (e) {
    showError(eventError, i18n.t('events.save_failed', { error: e.message }));
  } finally {
    btn.disabled = false;
  }
});

// ── Helpers for price cells ────────────────────────────────────────────────────

function _priceHtml(value, code) {
  return value != null ? formatCurrencyIn(value, code) : '<span class="price-na">—</span>';
}

function _pnlHtml(value, code) {
  if (value == null) return '<span class="price-na">—</span>';
  const cls  = value >= 0 ? 'pnl-pos' : 'pnl-neg';
  const sign = value > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${formatCurrencyIn(value, code)}</span>`;
}

function _pnlPctHtml(value) {
  if (value == null) return '<span class="price-na">—</span>';
  const cls  = value >= 0 ? 'pnl-pos' : 'pnl-neg';
  const sign = value > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${value.toFixed(2)}%</span>`;
}

// ── Client-side sorting (positions) ─────────────────────────────────────────────
// Most recently loaded positions + balance, kept so re-sorting never re-fetches.
let currentPositions = [];
let positionsBalance = null;
// Active sort, or null for the default order (the order the API returned).
let activePositionSort = null;

const POSITION_SORT_COLUMNS = {
  ticker:  { field: 'ticker',                   type: 'string' },
  type:    { field: 'trade_type',               type: 'string' },
  qty:     { field: 'total_remaining_quantity', type: 'number' },
  avgcost: { field: 'avg_cost_per_unit',        type: 'number' },
  basis:   { field: 'total_cost_basis',         type: 'number' },
  price:   { field: 'current_price',            type: 'number' },
  value:   { field: 'current_value',            type: 'number' },
  pnl:     { field: 'unrealized_pnl',           type: 'number' },
  pnlpct:  { field: 'unrealized_pnl_pct',       type: 'number' },
};

// Active filters narrow the cached positions client-side (no re-fetch). A position
// matches a broker filter when any of its lots is held at that broker.
function getFilteredPositions() {
  const q      = posFilterTicker.value.trim().toLowerCase();
  const asset  = posFilterAsset.value;
  const type   = posFilterType.value;
  const broker = posFilterBroker.value;
  let result = currentPositions.filter(p => {
    if (q && !`${p.ticker} ${p.symbol || ''}`.toLowerCase().includes(q)) return false;
    if (asset && (p.asset_class || '') !== asset) return false;
    if (type && p.trade_type !== type) return false;
    return true;
  });
  // A position aggregates lots across brokers. A broker filter re-scopes each
  // position to that broker's lots (recomputing quantity, cost basis, and value)
  // and drops positions not held there — rather than keeping whole rows, which
  // would match every broker for a diversified holding.
  if (broker) {
    result = result.map(p => scopePositionToBroker(p, parseInt(broker, 10))).filter(Boolean);
  } else if (posSplitBroker.checked) {
    // "Split by broker" off the filter: show one row per broker the stock is held
    // at, instead of a single aggregated row.
    result = result.flatMap(splitPositionByBroker);
  }
  return result;
}

// One scoped position per distinct broker in the holding (null = no broker last),
// or the original row when it has no lots to split.
function splitPositionByBroker(p) {
  const ids = [...new Set((p.lots || []).map(l => l.broker_id))]
    .sort((a, b) => (a == null ? 1 : b == null ? -1 : a - b));
  const rows = ids.map(id => scopePositionToBroker(p, id)).filter(Boolean);
  return rows.length ? rows : [p];
}

// Rebuild a position from only the lots held at `brokerId` (a raw broker id, or
// null for unbrokered lots), or null if none. Marks the row broker_scoped so the
// renderer shows which broker it is.
function scopePositionToBroker(p, brokerId) {
  const lots = (p.lots || []).filter(l => l.broker_id === brokerId);
  if (!lots.length) return null;
  const round10 = x => Math.round(x * 1e10) / 1e10;
  const mult  = p.multiplier || 1;   // contract multiplier (100 for options, else 1)
  const qty   = round10(lots.reduce((s, l) => s + l.remaining_quantity, 0));
  // avg cost stays per-unit; basis and value fold in the multiplier (matches the backend).
  const basis = round10(lots.reduce((s, l) => s + l.remaining_quantity * l.price_per_unit * (l.multiplier || mult), 0));
  const rawCost = round10(lots.reduce((s, l) => s + l.remaining_quantity * l.price_per_unit, 0));
  const price = p.current_price;
  const value = price != null ? round10(qty * price * mult) : null;
  // A short gains when the buy-back value falls below the proceeds (basis).
  const pnl   = value != null
    ? round10(p.direction === 'short' ? (basis - value) : (value - basis))
    : null;
  const brokerName = brokerId != null
    ? (brokersById.get(brokerId)?.name ?? `Broker ${brokerId}`)
    : i18n.t('positions.no_broker');
  return {
    ...p,
    broker_id:                brokerId,
    broker_name:              brokerName,
    broker_color:             brokerId != null ? (brokersById.get(brokerId)?.color ?? null) : null,
    broker_scoped:            true,
    lots,
    total_remaining_quantity: qty,
    total_cost_basis:         basis,
    avg_cost_per_unit:        qty ? round10(rawCost / qty) : 0,
    current_value:            value,
    unrealized_pnl:           pnl,
    unrealized_pnl_pct:       (pnl != null && basis) ? round10(pnl / basis * 100) : null,
  };
}

// "SHORT" pill shown next to the ticker on short positions.
function shortBadgeHtml() {
  return `<span class="short-badge">${escHtml(i18n.t('positions.short'))}</span>`;
}

// Currency pill shown when a position is held in a currency other than the
// reporting currency, so the per-unit/native amounts aren't mistaken for base.
function currencyTagHtml(code) {
  if (!code || code === reportingCurrency()) return '';
  return `<span class="currency-tag">${escHtml(code)}</span>`;
}

// Small broker chip (color dot + name) shown on broker-scoped position rows.
function brokerTagHtml(name, color) {
  const dot = color ? `<span class="pos-broker-dot" style="background:${escHtml(color)}"></span>` : '';
  return `<span class="pos-broker-tag">${dot}${escHtml(name || '')}</span>`;
}

function getSortedPositions(base = currentPositions) {
  const data = base.slice();   // stable sort keeps API order for ties
  if (!activePositionSort) return data;
  const col  = POSITION_SORT_COLUMNS[activePositionSort.key];
  const sign = activePositionSort.dir === 'asc' ? 1 : -1;
  data.sort((a, b) => sign * compareTradeValues(a[col.field], b[col.field], col.type));
  return data;
}

function updatePositionSortIndicators() {
  document.querySelectorAll('#positions-table th[data-sort-key]').forEach(th => {
    const arrow = th.querySelector('.sort-arrow');
    if (!arrow) return;
    if (activePositionSort && activePositionSort.key === th.dataset.sortKey) {
      arrow.innerHTML = icon(activePositionSort.dir === 'asc' ? 'chevronUp' : 'chevronDown', 'icon-sort');
    } else {
      arrow.innerHTML = '';
    }
  });
}

function applyPositionSort() {
  renderPositionsRows(getSortedPositions(getFilteredPositions()));
  updatePositionSortIndicators();
}

// Rebuild the filter dropdowns from the holdings actually present, preserving the
// user's current choice when it still applies. Asset-class and type options reflect
// what's held; broker options map ids (from lots) to broker names.
function fillSelectPreserve(sel, values, labelFn, allLabel) {
  const prev = sel.value;
  sel.innerHTML = '';
  sel.add(new Option(allLabel, ''));
  for (const v of values) sel.add(new Option(labelFn(v), v));
  sel.value = [...sel.options].some(o => o.value === prev) ? prev : '';
}

function populatePositionFilters() {
  const assets = [...new Set(currentPositions.map(p => p.asset_class).filter(Boolean))].sort();
  fillSelectPreserve(posFilterAsset, assets, assetClassLabel, i18n.t('positions.all_asset_classes'));

  const types = [...new Set(currentPositions.map(p => p.trade_type).filter(Boolean))].sort();
  fillSelectPreserve(posFilterType, types, v => v, i18n.t('positions.all_types'));

  const brokerIds = [...new Set(
    currentPositions.flatMap(p => (p.lots || []).map(l => l.broker_id)).filter(id => id != null)
  )].map(String);
  fillSelectPreserve(
    posFilterBroker, brokerIds,
    id => (brokersById.get(parseInt(id))?.name) || `Broker ${id}`,
    i18n.t('positions.all_brokers'),
  );
}

function onPositionSortClick(key) {
  if (!activePositionSort || activePositionSort.key !== key) {
    activePositionSort = { key, dir: 'asc' };
  } else if (activePositionSort.dir === 'asc') {
    activePositionSort = { key, dir: 'desc' };
  } else {
    activePositionSort = null;   // back to default (API order)
  }
  applyPositionSort();
}

document.querySelectorAll('#positions-table th[data-sort-key]').forEach(th => {
  th.addEventListener('click', () => onPositionSortClick(th.dataset.sortKey));
});

// Cache the data, then render with the active sort preserved across refreshes.
function renderPositions(positions, balance) {
  currentPositions = positions;
  positionsBalance = balance;
  populatePositionFilters();
  applyPositionSort();
}

posFilterTicker.addEventListener('input', applyPositionSort);
posFilterAsset.addEventListener('change', applyPositionSort);
posFilterType.addEventListener('change', applyPositionSort);
posFilterBroker.addEventListener('change', applyPositionSort);
btnClearPositionFilters.addEventListener('click', () => {
  posFilterTicker.value = '';
  posFilterAsset.value  = '';
  posFilterType.value   = '';
  posFilterBroker.value = '';
  applyPositionSort();
});

function renderPositionsRows(positions) {
  if (positionsBalance != null) positionsCashBalance.textContent = formatCurrency(positionsBalance);
  positionsTbody.innerHTML = '';

  if (!positions.length) {
    // Distinguish "no holdings at all" from "filters hid everything".
    positionsEmpty.textContent = currentPositions.length
      ? i18n.t('positions.no_match')
      : i18n.t('positions.no_positions');
    positionsEmpty.classList.remove('hidden');
    return;
  }
  positionsEmpty.classList.add('hidden');

  positions.forEach(p => {
    const tr = document.createElement('tr');
    tr.dataset.ticker = p.ticker;
    // Prices are fetched by Yahoo symbol; the display ticker stays user-friendly.
    tr.dataset.symbol = p.symbol || p.ticker;
    tr.innerHTML = `
      <td class="ticker-cell">
        ${exchangeBadge(p.exchange)}
        ${tickerLinkHtml(p.ticker, p.name)}
        ${p.direction === 'short' ? shortBadgeHtml() : ''}
        ${currencyTagHtml(p.currency)}
        ${p.broker_scoped ? brokerTagHtml(p.broker_name, p.broker_color) : ''}
      </td>
      <td>${badge(p.trade_type)}</td>
      <td class="num">${formatNumber(p.total_remaining_quantity)}</td>
      <td class="num">${formatCurrencyIn(p.avg_cost_per_unit, p.currency)}</td>
      <td class="num">${formatCurrencyIn(p.total_cost_basis, p.currency)}</td>
      <td class="num price-col">${_priceHtml(p.current_price, p.currency)}</td>
      <td class="num price-col">${_priceHtml(p.current_value, p.currency)}</td>
      <td class="num price-col">${_pnlHtml(p.unrealized_pnl, p.currency)}</td>
      <td class="num price-col">${_pnlPctHtml(p.unrealized_pnl_pct)}</td>
      <td><button class="sell-btn">${p.direction === 'short'
            ? escHtml(i18n.t('positions.cover')) : escHtml(i18n.t('positions.sell'))}</button></td>
    `;
    if (p.broker_color) {
      tr.style.setProperty('--broker-color', p.broker_color);
      tr.classList.add('has-broker-color');
    }
    tr.querySelector('.sell-btn').addEventListener('click', () => openSellModal(p));
    // Positions are aggregates with no single trade; resolve via the instrument
    // (with the dominant broker). Fall back to a representative lot's trade when
    // the position has no linked instrument (free-text ticker).
    const posDesc = p.instrument_id != null
      ? instrumentQuoteDesc(p.instrument_id, p.broker_id)
      : (p.lots && p.lots.length ? tradeQuoteDesc(p.lots[0].trade_id) : null);
    wireTickerLink(tr.querySelector('.ticker-link'), posDesc);
    positionsTbody.appendChild(tr);
  });

  consumeSearchHighlight('position');   // flash a row if search navigated here
}

function showPriceSkeleton() {
  positionsTbody.querySelectorAll('.price-col').forEach(cell => {
    cell.innerHTML = '<span class="price-skel"></span>';
  });
}

function updatePricesLabel(positions) {
  const label = document.getElementById('prices-last-updated');
  const timestamps = positions
    .map(p => p.price_fetched_at)
    .filter(Boolean)
    .map(ts => new Date(ts.replace(' ', 'T') + 'Z').getTime());

  if (!timestamps.length) { label.textContent = ''; return; }

  const oldest     = Math.min(...timestamps);
  const minutesAgo = Math.round((Date.now() - oldest) / 60_000);

  const ago = minutesAgo < 1
    ? i18n.t('common.just_now')
    : i18n.t('common.ago', { n: minutesAgo, unit: 'minutes' });
  label.textContent = i18n.t('positions.last_updated', { ago });
}

// ── Refresh prices ─────────────────────────────────────────────────────────────
document.getElementById('btn-refresh-prices').addEventListener('click', async () => {
  if (!activeUserId) return;

  const symbols = [...new Set(
    Array.from(positionsTbody.querySelectorAll('tr[data-symbol]'))
      .map(tr => tr.dataset.symbol)
  )];
  if (!symbols.length) return;

  const btn   = document.getElementById('btn-refresh-prices');
  const label = document.getElementById('prices-last-updated');
  btn.disabled     = true;
  label.textContent = i18n.t('positions.refreshing');
  showPriceSkeleton();

  try {
    await apiFetch('/prices/refresh', {
      method: 'POST',
      body: JSON.stringify({ symbols, source: 'yahoo_finance' }),
    });
  } catch (e) {
    showToast(i18n.t('positions.refresh_failed', { error: e.message }), true);
  }

  // Re-fetch regardless of whether the refresh call succeeded — cache may
  // have partial results, and we always need to clear the skeleton.
  try {
    const [positions, cash] = await Promise.all([
      apiFetch(`/users/${activeUserId}/positions/prices`),
      apiFetch(`/users/${activeUserId}/cash`),
    ]);
    renderPositions(positions, cash.balance);
    updatePricesLabel(positions);
  } catch (e) {
    showToast(i18n.t('positions.reload_failed', { error: e.message }), true);
    positionsTbody.querySelectorAll('.price-col').forEach(cell => {
      cell.innerHTML = '<span class="price-na">—</span>';
    });
  } finally {
    btn.disabled = false;
  }
});

// ── Sell modal ────────────────────────────────────────────────────────────────
let currentSellPosition = null;

const sellModalOverlay  = document.getElementById('sell-modal-overlay');
const sellModalTicker   = document.getElementById('sell-modal-ticker');
const sellModalTypeBadge= document.getElementById('sell-modal-type-badge');
const sellLotsTbody     = document.getElementById('sell-lots-tbody');
const sellQtyInput      = document.getElementById('sell-qty-input');
const sellPriceInput    = document.getElementById('sell-price-input');
const sellCurrentPrice  = document.getElementById('sell-current-price');
const sellDateInput     = document.getElementById('sell-date-input');
const sellNotesInput    = document.getElementById('sell-notes-input');
const sellPreviewBar    = document.getElementById('sell-preview-bar');
const sellErrorEl       = document.getElementById('sell-error');
const sellMaxHint       = document.getElementById('sell-max-hint');
const sellConfirmBtn    = document.getElementById('sell-confirm-btn');
const sellCancelBtn     = document.getElementById('sell-cancel-btn');
const sellModalClose    = document.getElementById('sell-modal-close');

function todayISO() {
  return new Date().toLocaleDateString('en-CA'); // YYYY-MM-DD in local time
}

function openSellModal(position) {
  // Sort lots oldest-first (FIFO); API should already return them sorted, but be defensive
  const lots = [...position.lots].sort((a, b) =>
    a.trade_date < b.trade_date ? -1 : a.trade_date > b.trade_date ? 1 : a.trade_id - b.trade_id
  );
  currentSellPosition = { ...position, lots };

  sellModalTicker.innerHTML = tickerLinkHtml(position.ticker, position.name);
  {
    const sellDesc = position.instrument_id != null
      ? instrumentQuoteDesc(position.instrument_id, position.broker_id)
      : (lots.length ? tradeQuoteDesc(lots[0].trade_id) : null);
    wireTickerLink(sellModalTicker.querySelector('.ticker-link'), sellDesc);
  }
  sellModalTypeBadge.className = `badge badge-${position.trade_type}`;
  sellModalTypeBadge.textContent = position.trade_type;

  sellLotsTbody.innerHTML = lots.map(lot => `
    <tr>
      <td>${formatDate(lot.trade_date)}${lot.status === 'partial' ? `<span class="lot-status-partial">${escHtml(i18n.t('sell_form.lot_partial'))}</span>` : ''}</td>
      <td class="num">${formatNumber(lot.remaining_quantity)}</td>
      <td class="num">${formatCurrency(lot.price_per_unit)}</td>
    </tr>
  `).join('');

  const maxQty = position.total_remaining_quantity;
  sellQtyInput.max   = maxQty;
  sellMaxHint.textContent = i18n.t('sell_form.max_hint', { n: formatNumber(maxQty) });
  sellQtyInput.value  = '';
  sellDateInput.value  = todayISO();
  sellNotesInput.value = '';

  // Pre-fill the sell price with the current market price (editable), and show it
  // as a hint. Falls back to blank when no price is available.
  if (position.current_price != null) {
    sellPriceInput.value = position.current_price;
    sellCurrentPrice.textContent = i18n.t('sell_form.current_price', { price: formatCurrency(position.current_price) });
  } else {
    sellPriceInput.value = '';
    sellCurrentPrice.textContent = i18n.t('sell_form.current_price_unavailable');
  }

  sellPreviewBar.className = 'sell-preview-bar hidden';
  clearError(sellErrorEl);
  sellConfirmBtn.disabled    = false;
  sellConfirmBtn.textContent = i18n.t(position.direction === 'short' ? 'sell_form.confirm_cover' : 'sell_form.confirm');

  sellModalOverlay.classList.remove('hidden');
  sellQtyInput.focus();
}

function closeSellModal() {
  sellModalOverlay.classList.add('hidden');
  currentSellPosition = null;
}

// FIFO allocation across lots, mirroring the backend: each lot allocation is a
// separate sell call, so the broker's flat fee applies once per lot touched and
// the proportional buy commission is the lot's commission scaled by the share
// of its original quantity being sold.
function computeSellEstimate(lots, qtySold, sellPrice, multiplier = 1, direction = 'long') {
  let remaining   = qtySold;
  let costBasis   = 0;   // gross open value of the units being closed (× multiplier)
  let sellComm    = 0;   // estimated sell-side commission
  let buyCommProp = 0;   // proportional buy-side commission

  for (const lot of lots) {
    if (remaining <= 1e-9) break;
    const allocated = Math.min(lot.remaining_quantity, remaining);
    costBasis += allocated * lot.price_per_unit * (lot.multiplier || multiplier);
    sellComm  += estimateCommission(getBroker(lot.broker_id), allocated);
    if (lot.quantity > 0) {
      buyCommProp += (allocated / lot.quantity) * (lot.commission || 0);
    }
    remaining -= allocated;
  }

  // `cashFlow` is the gross trade value: proceeds you receive closing a long, or
  // the buy-back cost you pay covering a short.
  const cashFlow = qtySold * sellPrice * multiplier;
  // Closing a long: P&L = (proceeds − sell comm) − (open cost + prop buy comm).
  // Covering a short: lot.price_per_unit is the short-sale price, so costBasis is
  // the open proceeds; P&L = (open proceeds − prop comm) − (buy-back cost + comm).
  const netPnl = direction === 'short'
    ? (costBasis - buyCommProp) - (cashFlow + sellComm)
    : (cashFlow - sellComm) - (costBasis + buyCommProp);
  return { proceeds: cashFlow, sellComm, costBasis, buyCommProp, netPnl };
}

function updateSellPreview() {
  const qty   = parseFloat(sellQtyInput.value);
  const price = parseFloat(sellPriceInput.value);

  if (!currentSellPosition || !(qty > 0) || !(price >= 0)) {
    sellPreviewBar.className = 'sell-preview-bar hidden';
    return;
  }

  const isShort = currentSellPosition.direction === 'short';
  const est  = computeSellEstimate(
    currentSellPosition.lots, qty, price,
    currentSellPosition.multiplier || 1, currentSellPosition.direction || 'long'
  );
  const sign = est.netPnl >= 0 ? '+' : '';
  const grossLabel = isShort ? i18n.t('sell_form.cost_label') : i18n.t('sell_form.proceeds_label');

  sellPreviewBar.innerHTML =
    `<div class="sell-preview-line"><span>${escHtml(grossLabel)}</span><span>${formatCurrency(est.proceeds)}</span></div>` +
    `<div class="sell-preview-line"><span>${escHtml(i18n.t('sell_form.commission_label'))}</span><span>−${formatCurrency(est.sellComm)}</span></div>` +
    `<div class="sell-preview-line sell-preview-total"><span>${escHtml(i18n.t('sell_form.net_pnl_label'))}</span>` +
      `<span>${sign}${formatCurrency(est.netPnl)}</span></div>`;
  sellPreviewBar.className = `sell-preview-bar ${est.netPnl >= 0 ? 'positive' : 'negative'}`;
}

sellQtyInput.addEventListener('input', () => {
  // Clamp to max on blur-level; warn inline if over
  const qty = parseFloat(sellQtyInput.value);
  const max = currentSellPosition?.total_remaining_quantity ?? 0;
  if (qty > max) sellQtyInput.value = max;
  updateSellPreview();
});
sellPriceInput.addEventListener('input', updateSellPreview);

sellModalClose.addEventListener('click', closeSellModal);
sellCancelBtn.addEventListener('click', closeSellModal);
sellModalOverlay.addEventListener('click', e => {
  if (e.target === sellModalOverlay) closeSellModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !sellModalOverlay.classList.contains('hidden')) closeSellModal();
});

sellConfirmBtn.addEventListener('click', async () => {
  if (!currentSellPosition) return;
  clearError(sellErrorEl);

  const qty   = parseFloat(sellQtyInput.value);
  const price = parseFloat(sellPriceInput.value);
  const date  = sellDateInput.value;
  const notes = sellNotesInput.value.trim() || null;
  const max   = currentSellPosition.total_remaining_quantity;

  if (!(qty > 0))     { showError(sellErrorEl, 'Enter a quantity greater than 0.'); return; }
  if (qty > max)      { showError(sellErrorEl, `Quantity exceeds remaining ${formatNumber(max)}.`); return; }
  if (!(price >= 0))  { showError(sellErrorEl, 'Enter a valid sell price.'); return; }
  if (!date)          { showError(sellErrorEl, 'Enter a sell date.'); return; }

  // Build FIFO allocations
  const allocations = [];
  let toSell = qty;
  for (const lot of currentSellPosition.lots) {
    if (toSell <= 1e-9) break;
    const allocated = Math.min(lot.remaining_quantity, toSell);
    allocations.push({ tradeId: lot.trade_id, qty: allocated });
    toSell -= allocated;
  }

  const isShort = currentSellPosition.direction === 'short';
  sellConfirmBtn.disabled    = true;
  sellConfirmBtn.textContent = i18n.t(isShort ? 'sell_form.covering' : 'sell_form.selling');

  try {
    for (const alloc of allocations) {
      // Closing a long sells against the buy lot; closing a short covers it.
      const path = isShort
        ? `/trades/${alloc.tradeId}/cover`
        : `/trades/${alloc.tradeId}/sell`;
      const body = isShort
        ? { quantity_covered: alloc.qty, cover_price_per_unit: price, cover_date: date, notes }
        : { quantity_sold:    alloc.qty, sell_price_per_unit:  price, sell_date:  date, notes };
      await apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
    }
    closeSellModal();
    showToast(i18n.t(isShort ? 'sell_form.covered' : 'sell_form.recorded'));
    loadPositions(); // refreshes both positions table and cash balance
  } catch (e) {
    showError(sellErrorEl, e.message);
    sellConfirmBtn.disabled    = false;
    sellConfirmBtn.textContent = i18n.t(isShort ? 'sell_form.confirm_cover' : 'sell_form.confirm');
  }
});

// ── Settings ──────────────────────────────────────────────────────────────────
const SETTINGS_DEFAULTS = { theme: 'dark', zoom: 1.0, sidebarWidth: 240, density: 'normal' };

function loadSettings() {
  try { return { ...SETTINGS_DEFAULTS, ...JSON.parse(localStorage.getItem('tn-settings') || '{}') }; }
  catch { return { ...SETTINGS_DEFAULTS }; }
}

function saveSettings(s) { localStorage.setItem('tn-settings', JSON.stringify(s)); }

function applySettings(s) {
  document.documentElement.dataset.theme = s.theme;
  if (window.electronAPI) {
    window.electronAPI.setZoom(s.zoom);
  }
  document.documentElement.style.setProperty('--sidebar-w', s.sidebarWidth + 'px');
  document.body.classList.toggle('compact', s.density === 'compact');
}

let currentSettings = loadSettings();
applySettings(currentSettings);

const settingsOverlay = document.getElementById('settings-overlay');
const settingThemeEl  = document.getElementById('setting-theme');
const settingZoomEl   = document.getElementById('setting-zoom');
const zoomDisplayEl   = document.getElementById('zoom-display');
const settingSidebarEl= document.getElementById('setting-sidebar');
const settingDensityEl= document.getElementById('setting-density');

// Reflect the stored UI preferences (theme / zoom / sidebar / density) into their
// controls. Runs whenever the settings popup opens (via populateGeneralSettings).
function syncUiPrefControls() {
  settingThemeEl.querySelectorAll('.opt-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.value === currentSettings.theme));
  settingZoomEl.value = currentSettings.zoom;
  zoomDisplayEl.textContent = Math.round(currentSettings.zoom * 100) + '%';
  settingSidebarEl.querySelectorAll('.opt-btn').forEach(b =>
    b.classList.toggle('active', +b.dataset.value === currentSettings.sidebarWidth));
  settingDensityEl.querySelectorAll('.opt-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.value === currentSettings.density));
}

// All general + appearance settings live in this popup (a fixed overlay) so the UI
// Scale slider can't reflow the page underneath it while being dragged.
function openSettings() {
  populateGeneralSettings();   // fills the app-setting fields + syncs the pref controls
  settingsOverlay.classList.remove('hidden');
}
function closeSettings() { settingsOverlay.classList.add('hidden'); }

document.getElementById('btn-settings').addEventListener('click', openSettings);
document.getElementById('settings-close').addEventListener('click', closeSettings);
settingsOverlay.addEventListener('click', e => { if (e.target === settingsOverlay) closeSettings(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !settingsOverlay.classList.contains('hidden')) closeSettings();
});

function setupOptGroup(container, key, numeric = false) {
  container.querySelectorAll('.opt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentSettings[key] = numeric ? +btn.dataset.value : btn.dataset.value;
      saveSettings(currentSettings);
      applySettings(currentSettings);
      if (key === 'theme' && document.getElementById('tab-analytics').classList.contains('active')) {
        loadAnalytics();
      }
    });
  });
}

setupOptGroup(settingThemeEl,   'theme');
setupOptGroup(settingSidebarEl, 'sidebarWidth', true);
setupOptGroup(settingDensityEl, 'density');

settingZoomEl.addEventListener('input', () => {
  const val = parseFloat(settingZoomEl.value);
  zoomDisplayEl.textContent = Math.round(val * 100) + '%';
  currentSettings.zoom = val;
  saveSettings(currentSettings);
  applySettings(currentSettings);
});

// ── Broker cache + commission helpers ─────────────────────────────────────────
const brokersById = new Map();

async function loadBrokerOptions(selectEl) {
  const current = selectEl.value;
  while (selectEl.options.length > 1) selectEl.remove(1);
  try {
    const brokers = await apiFetch('/brokers');
    brokersById.clear();
    for (const b of brokers) {
      brokersById.set(b.id, b);
      selectEl.add(new Option(b.name, b.id));
    }
    if (current) selectEl.value = current;
  } catch (e) {
    console.warn('Failed to load broker options:', e.message);
  }
}

function getBroker(brokerId) {
  if (brokerId == null || brokerId === '') return null;
  return brokersById.get(parseInt(brokerId)) ?? null;
}

// Pre-select the configured default broker in the Add-trade dropdown, but only if
// nothing is selected yet and the broker still exists. Assumes broker options are
// already loaded.
function applyDefaultBroker() {
  const id = appSettings.default_broker_id;
  if (!id) return;                    // empty → leave the dropdown blank
  if (tradeBrokerEl.value) return;    // don't override an existing selection
  if (!getBroker(id)) return;         // broker no longer exists → leave blank
  tradeBrokerEl.value = String(id);
}

// Populate the broker cache if it has not been loaded yet (e.g. the user goes
// straight to Positions and sells without opening a trade form first).
async function ensureBrokers() {
  if (brokersById.size) return;
  try {
    const brokers = await apiFetch('/brokers');
    brokersById.clear();
    for (const b of brokers) brokersById.set(b.id, b);
  } catch (e) {
    console.warn('ensureBrokers failed:', e.message);
  }
}

// Commission = flat fee + per-unit fee * quantity (matches backend _compute_commission)
function estimateCommission(broker, quantity) {
  if (!broker) return 0;
  const flat    = Number(broker.commission_flat)     || 0;
  const perUnit = Number(broker.commission_per_unit) || 0;
  const qty     = Number(quantity) || 0;
  return flat + perUnit * qty;
}

function unitLabel(tradeType, quantity) {
  const t = String(tradeType).toLowerCase();   // accept "Stock"/"stock" alike
  const noun = (t === 'call' || t === 'put') ? 'contract'
             : (t === 'stock') ? 'share' : 'unit';
  return quantity === 1 ? noun : noun + 's';
}

// e.g. "$6.95 flat + $0.65 × 10 contracts = $13.45"
function commissionFormula(broker, quantity, tradeType) {
  if (!broker) return `No broker selected — ${formatCurrency(0)}`;
  const flat    = Number(broker.commission_flat)     || 0;
  const perUnit = Number(broker.commission_per_unit) || 0;
  const qty     = Number(quantity) || 0;
  const total   = flat + perUnit * qty;
  return `${formatCurrency(flat)} flat + ${formatCurrency(perUnit)} × ${formatNumber(qty)} `
       + `${unitLabel(tradeType, qty)} = ${formatCurrency(total)}`;
}

// ── Settings navigation ────────────────────────────────────────────────────────
const settingsPanel = document.getElementById('settings-panel');

document.querySelectorAll('.settings-nav-item').forEach(item => {
  item.addEventListener('click', () => {
    // Deactivate user view
    activeUserId = activeUserName = null;
    document.querySelectorAll('#user-list li').forEach(li => li.classList.remove('active'));
    emptyState.classList.add('hidden');
    userPanel.classList.add('hidden');

    // Activate settings item
    document.querySelectorAll('.settings-nav-item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');
    settingsPanel.classList.remove('hidden');

    // Show only the selected settings page.
    settingsPanel.querySelectorAll('[id^="page-"]').forEach(p => p.classList.add('hidden'));
    const page = document.getElementById('page-' + item.dataset.page);
    if (page) page.classList.remove('hidden');

    if (item.dataset.page === 'brokers')     loadBrokers();
    if (item.dataset.page === 'trade-types') loadTradeTypesPage();
    if (item.dataset.page === 'data')        { clearRestoreResult(); loadPriceCacheCount(); }
  });
});

// ── General settings page (auto-save) ─────────────────────────────────────────
function updateDateFormatPreview() {
  const fmt = document.getElementById('setting-date-format').value;
  document.getElementById('date-format-preview').textContent =
    i18n.t('settings.date_preview', { date: formatDate(_localISO(new Date()), fmt) });
}

// Reflect the current appSettings into the form controls.
function populateGeneralSettings() {
  document.getElementById('setting-display-name').value      = appSettings.display_name ?? '';
  document.getElementById('setting-language').value          = appSettings.language ?? 'en';
  document.getElementById('setting-currency').value          = appSettings.currency ?? 'USD';
  document.getElementById('setting-date-format').value       = appSettings.date_format ?? 'MM/DD/YYYY';
  document.getElementById('setting-decimal-separator').value = appSettings.decimal_separator ?? '.';
  document.getElementById('setting-refresh-interval').value  = String(appSettings.price_refresh_interval_minutes ?? '15');
  document.getElementById('setting-fiscal-month').value      = String(appSettings.fiscal_year_start_month ?? '1');
  updateDateFormatPreview();
  syncUiPrefControls();   // theme / zoom / sidebar / density controls (same page)
}

const _statusTimers = new WeakMap();
function showSettingStatus(el, state, msg) {
  if (!el) return;
  clearTimeout(_statusTimers.get(el));
  if (state === 'saved') {
    el.innerHTML = `${icon('check', 'icon-sm')} ${escHtml(i18n.t('settings.saved'))}`;
    el.className = 'settings-status saved';
    _statusTimers.set(el, setTimeout(() => {
      el.textContent = '';
      el.className = 'settings-status';
    }, 2000));
  } else {
    el.textContent = msg || i18n.t('settings.save_failed');
    el.className = 'settings-status failed';
  }
}

async function saveSetting(key, value, statusEl) {
  try {
    const updated = await apiFetch('/settings', {
      method: 'PUT',
      body: JSON.stringify({ [key]: value }),
    });
    Object.assign(appSettings, updated);
    showSettingStatus(statusEl, 'saved');
    if (key === 'display_name') updateGreeting();
  } catch (e) {
    showSettingStatus(statusEl, 'failed', i18n.t('settings.save_failed'));
  }
}

document.querySelectorAll('#settings-modal [data-key]').forEach(el => {
  el.addEventListener('change', async () => {
    const key = el.dataset.key;
    const statusEl = document.querySelector(`#settings-modal [data-status="${key}"]`);
    await saveSetting(key, el.value, statusEl);
    // Manually changing the date format or decimal separator pins them, so a later
    // language switch won't auto-override the user's explicit choice.
    if (key === 'date_format' || key === 'decimal_separator') {
      appSettings.date_format_manual_override = '1';
      apiFetch('/settings', {
        method: 'PUT', body: JSON.stringify({ date_format_manual_override: '1' }),
      }).catch(() => {});
    }
    // Anything that changes how money/dates render must re-paint the data views.
    if (key === 'currency' || key === 'date_format' || key === 'decimal_separator') {
      rerenderDynamicViews();
    }
  });
});
document.getElementById('setting-date-format').addEventListener('change', updateDateFormatPreview);

// ── Language switcher ─────────────────────────────────────────────────────────
// Auto date/number defaults per language, unless the user has pinned them.
async function applyLocaleFormatDefaults(lang) {
  if (String(appSettings.date_format_manual_override) === '1') return;
  const date_format       = lang === 'de' ? 'DD.MM.YYYY' : 'MM/DD/YYYY';
  const decimal_separator = lang === 'de' ? ',' : '.';
  if (appSettings.date_format === date_format && appSettings.decimal_separator === decimal_separator) return;
  try {
    const updated = await apiFetch('/settings', {
      method: 'PUT', body: JSON.stringify({ date_format, decimal_separator }),
    });
    Object.assign(appSettings, updated);
  } catch (e) {
    console.warn('Failed to apply locale format defaults:', e.message);
  }
}

// Re-paint every data-bound view from cached data (static text is handled by
// i18n.applyToDOM). Called after a language switch or a format-setting change.
function rerenderDynamicViews() {
  i18n.applyToDOM();
  updateGreeting();
  if (typeof currentTrades !== 'undefined' && currentTrades) {
    renderTradesRows(currentTrades, { append: false });
    updateTradesChrome();
  }
  if (typeof currentPositions !== 'undefined' && currentPositions) {
    populatePositionFilters();
    applyPositionSort();
    updatePricesLabel(currentPositions);
  }
  if (typeof cashTransactions !== 'undefined' && cashTransactions) {
    renderCashRows(cashTransactions, { append: false });
    updateCashChrome();
  }
  if (lastAnalyticsStats) renderAnalytics(lastAnalyticsStats);
  if (growthDataFull && growthDataFull.length) {
    renderGrowthChart(filterGrowth(growthDataFull, growthRange));
  }
}

document.getElementById('setting-language').addEventListener('change', async (e) => {
  const lang = e.target.value;
  await i18n.setLanguage(lang);          // load locale, persist, re-translate static DOM
  await applyLocaleFormatDefaults(lang); // date/number defaults unless pinned
  populateGeneralSettings();             // reflect any auto-changed format selects
  rerenderDynamicViews();                // re-paint tables / charts / cards
  showToast(i18n.t('settings.language_changed'));
});

// ── Data page: backup / restore ───────────────────────────────────────────────
const restoreFileInput = document.getElementById('restore-file-input');
const restoreResult    = document.getElementById('restore-result');
const btnRestoreBackup = document.getElementById('btn-restore-backup');

function clearRestoreResult() {
  restoreResult.textContent = '';
  restoreResult.className = 'hidden';
}
function setRestoreResult(msg, kind) {  // kind: 'success' | 'error'
  restoreResult.textContent = msg;
  restoreResult.className = kind === 'success' ? 'inline-success' : 'inline-error';
}

// Trigger a download via an anchor; the server's Content-Disposition names the file.
document.getElementById('btn-download-backup').addEventListener('click', () => {
  const a = document.createElement('a');
  a.href = API + '/settings/backup';
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
});

btnRestoreBackup.addEventListener('click', async () => {
  clearRestoreResult();

  const file = restoreFileInput.files[0];
  if (!file) {
    setRestoreResult(i18n.t('settings.restore_choose_file'), 'error');
    return;
  }

  const ok = await confirmDialog(
    i18n.t('settings.restore_confirm_safety'),
    i18n.t('common.continue')
  );
  if (!ok) return;

  btnRestoreBackup.disabled = true;
  try {
    const fd = new FormData();
    fd.append('file', file);
    // Raw fetch (not apiFetch) so the browser sets the multipart boundary itself.
    const res = await fetch(API + '/settings/restore', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    setRestoreResult(i18n.t('settings.restore_success_reloading'), 'success');
    setTimeout(() => window.location.reload(), 2000);
  } catch (e) {
    setRestoreResult(e.message, 'error');
    btnRestoreBackup.disabled = false;  // stay on the page so the user can retry
  }
});

// ── Data page: price cache ────────────────────────────────────────────────────
const priceCacheCount = document.getElementById('price-cache-count');
const cacheResult     = document.getElementById('cache-result');
const btnClearCache   = document.getElementById('btn-clear-cache');

function setCacheCount(n) {
  priceCacheCount.textContent = i18n.t('settings.tickers_cached', { n });
}

async function loadPriceCacheCount() {
  cacheResult.className = 'hidden';
  cacheResult.textContent = '';
  try {
    const { count } = await apiFetch('/settings/price-cache');
    setCacheCount(count);
  } catch (e) {
    priceCacheCount.textContent = i18n.t('settings.cache_unavailable');
  }
}

btnClearCache.addEventListener('click', async () => {
  cacheResult.className = 'hidden';
  btnClearCache.disabled = true;
  try {
    const { deleted } = await apiFetch('/settings/price-cache', { method: 'DELETE' });
    setCacheCount(0);
    cacheResult.textContent = i18n.t('settings.cache_cleared', { n: deleted });
    cacheResult.className = 'inline-success';
  } catch (e) {
    cacheResult.textContent = e.message;
    cacheResult.className = 'inline-error';
  } finally {
    btnClearCache.disabled = false;
  }
});

// ── Brokers CRUD ──────────────────────────────────────────────────────────────
let editingBrokerId = null;

const brokerFormWrap    = document.getElementById('broker-form-wrap');
const brokerFormTitle   = document.getElementById('broker-form-title');
const brokerForm        = document.getElementById('broker-form');
const brokerNameInput   = document.getElementById('broker-name-input');
const brokerSourceInput = document.getElementById('broker-source-input');
const brokerNotesInput  = document.getElementById('broker-notes-input');
const brokerCommFlatInput    = document.getElementById('broker-commission-flat-input');
const brokerCommPerUnitInput = document.getElementById('broker-commission-per-unit-input');
const brokerQuoteTemplateInput = document.getElementById('broker-quote-template-input');
const brokerQuoteKeyInput      = document.getElementById('broker-quote-key-input');
const brokerQuotePreviewRow    = document.getElementById('broker-quote-preview-row');
const brokerQuotePreview       = document.getElementById('broker-quote-preview');
const btnTestQuoteLink         = document.getElementById('btn-test-quote-link');
const brokerFormError   = document.getElementById('broker-form-error');

// Sample identifier per key, used only for the live template preview.
const QUOTE_SAMPLE = { symbol: 'VOD.L', ticker: 'VOD', isin: 'GB00BH4HKS39' };
let lastQuotePreviewUrl = null;

// Live-render the template preview as the user types. Hidden when the template is
// empty (Yahoo fallback) or missing the {value} placeholder. Test is enabled only
// for a valid https preview URL.
function updateQuotePreview() {
  const tpl = brokerQuoteTemplateInput.value.trim();
  const key = brokerQuoteKeyInput.value || 'symbol';
  // {value} follows the Identifier dropdown; named placeholders map to a field.
  const samples = {
    value:    QUOTE_SAMPLE[key] || QUOTE_SAMPLE.symbol,
    ticker:   'VOD', symbol: 'VOD.L', isin: 'GB00BH4HKS39', exchange: 'LSE',
  };
  const used = (tpl.match(/\{(\w+)\}/g) || []).map(s => s.slice(1, -1));
  const hasUnknown = used.some(p => !(p in samples));
  if (!tpl || used.length === 0 || hasUnknown) {
    brokerQuotePreviewRow.classList.add('hidden');
    lastQuotePreviewUrl = null;
    return;
  }
  const url = tpl.replace(/\{(\w+)\}/g, (m, p) => encodeURIComponent(samples[p]));
  brokerQuotePreview.textContent = i18n.t('settings.broker_quote_preview', { url });
  brokerQuotePreviewRow.classList.remove('hidden');
  lastQuotePreviewUrl = url.startsWith('https://') ? url : null;
  btnTestQuoteLink.disabled = !lastQuotePreviewUrl;
  btnTestQuoteLink.title = lastQuotePreviewUrl ? '' : i18n.t('settings.broker_quote_test_https');
}

brokerQuoteTemplateInput.addEventListener('input', updateQuotePreview);
brokerQuoteKeyInput.addEventListener('change', updateQuotePreview);
btnTestQuoteLink.addEventListener('click', () => {
  if (lastQuotePreviewUrl) openExternalLink(lastQuotePreviewUrl);
});
const brokersSpinner    = document.getElementById('brokers-spinner');
const brokersError      = document.getElementById('brokers-error');
const brokersTable      = document.getElementById('brokers-table');
const brokersTbody      = document.getElementById('brokers-tbody');
const brokersEmpty      = document.getElementById('brokers-empty');

async function loadBrokers() {
  brokersSpinner.classList.remove('hidden');
  brokersTable.classList.add('hidden');
  brokersEmpty.classList.add('hidden');
  clearError(brokersError);
  try {
    const brokers = await apiFetch('/brokers');
    renderBrokersTable(brokers);
  } catch (e) {
    showError(brokersError, i18n.t('settings.brokers_load_failed', { error: e.message }));
  } finally {
    brokersSpinner.classList.add('hidden');
  }
}

// ── Trade types ────────────────────────────────────────────────────────────────
// Loaded once at startup (alongside brokers) and refreshed after any change on the
// Trade Types settings page. Drives all trade_type dropdowns.
let tradeTypesList = [];

async function loadTradeTypes() {
  try {
    tradeTypesList = await apiFetch('/trade-types');
  } catch (e) {
    console.warn('Failed to load trade types:', e.message);
    tradeTypesList = [];
  }
  populateTradeTypeDropdowns();
}

// Fill one <select> with the trade-type names, preserving the current value if it
// still exists. `placeholder` (if given) is kept as the first, empty-value option.
function fillTypeSelect(sel, placeholder) {
  const prev = sel.value;
  sel.innerHTML = '';
  if (placeholder !== undefined) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = placeholder;
    sel.appendChild(opt);
  }
  for (const t of tradeTypesList) {
    const opt = document.createElement('option');
    opt.value = t.name;
    opt.textContent = t.name;
    sel.appendChild(opt);
  }
  if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
}

function populateTradeTypeDropdowns() {
  fillTypeSelect(filterTradeType, i18n.t('trades.all_types'));
  fillTypeSelect(tradeType, i18n.t('common.select'));
  fillTypeSelect(editType);   // no placeholder — always has a value
}

// ── Trade Types settings page ───────────────────────────────────────────────────
const tradeTypesTable    = document.getElementById('trade-types-table');
const tradeTypesTbody    = document.getElementById('trade-types-tbody');
const tradeTypesEmpty    = document.getElementById('trade-types-empty');
const tradeTypesError    = document.getElementById('trade-types-error');
const tradeTypeFormWrap  = document.getElementById('trade-type-form-wrap');
const tradeTypeForm      = document.getElementById('trade-type-form');
const tradeTypeNameInput = document.getElementById('trade-type-name-input');
const tradeTypeFormError = document.getElementById('trade-type-form-error');

async function loadTradeTypesPage() {
  clearError(tradeTypesError);
  tradeTypeFormWrap.classList.add('hidden');
  await loadTradeTypes();      // refresh from server (also refreshes dropdowns)
  renderTradeTypesTable();
}

function renderTradeTypesTable() {
  tradeTypesTbody.innerHTML = '';
  if (!tradeTypesList.length) {
    tradeTypesTable.classList.add('hidden');
    tradeTypesEmpty.classList.remove('hidden');
    return;
  }
  tradeTypesEmpty.classList.add('hidden');
  for (const t of tradeTypesList) {
    const tr = document.createElement('tr');
    tr.dataset.id = t.id;
    renderTypeRowDisplay(tr, t);
    tradeTypesTbody.appendChild(tr);
  }
  tradeTypesTable.classList.remove('hidden');
}

// A compact inline color picker (swatch → native picker, plus a clear button).
// Reuses the broker color-picker styles. Returns { el, value } where `value` is a
// live getter giving the current "#rrggbb" or null. Used by the create + edit rows.
function makeColorPicker(initial) {
  const wrap = document.createElement('span');
  wrap.className = 'color-picker-row type-color-picker';

  const swatch = document.createElement('button');
  swatch.type = 'button';
  swatch.className = 'color-swatch-btn';
  swatch.title = i18n.t('settings.broker_color_swatch_title');

  const native = document.createElement('input');
  native.type = 'color';
  native.className = 'color-native-hidden';
  native.tabIndex = -1;

  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'color-clear-btn';
  clear.title = i18n.t('settings.broker_color_clear_title');
  clear.innerHTML = icon('close', 'icon-sm');

  let value = (initial && _HEX_RE.test(initial)) ? initial : null;
  function sync() {
    if (value) { swatch.style.background = value; swatch.classList.add('has-color'); native.value = value; }
    else       { swatch.style.background = ''; swatch.classList.remove('has-color'); native.value = '#4f8ef7'; }
  }
  swatch.addEventListener('click', () => native.click());
  native.addEventListener('input', () => { value = native.value; sync(); });
  clear.addEventListener('click', () => { value = null; sync(); });
  sync();

  wrap.append(swatch, native, clear);
  return { el: wrap, get value() { return value; } };
}

function renderTypeRowDisplay(tr, t) {
  const typeBadge = t.is_default
    ? `<span class="badge badge-default-type">${escHtml(i18n.t('settings.type_default'))}</span>`
    : `<span class="badge badge-custom-type">${escHtml(i18n.t('settings.type_custom'))}</span>`;
  // Default types cannot be deleted, so they get no Delete button.
  const delBtn = t.is_default ? '' : `<button class="icon-btn danger type-del-btn" title="${escHtml(i18n.t('settings.delete_type_title'))}" aria-label="${escHtml(i18n.t('settings.delete_type_title'))}">${icon('trash', 'icon-sm')}</button>`;
  const dot = (t.color && _HEX_RE.test(t.color))
    ? `<span class="broker-color-dot" style="background:${t.color}"></span>`
    : `<span class="broker-color-dot broker-color-dot--empty"></span>`;
  tr.innerHTML = `
    <td><strong>${dot}${escHtml(t.name)}</strong></td>
    <td class="num">${t.usage_count}</td>
    <td>${typeBadge}</td>
    <td>
      <button class="secondary type-edit-btn">${escHtml(i18n.t('common.edit'))}</button>
      ${delBtn}
    </td>`;
  tr.querySelector('.type-edit-btn').addEventListener('click', () => renderTypeRowEdit(tr, t));
  const db = tr.querySelector('.type-del-btn');
  if (db) db.addEventListener('click', () => deleteTradeType(t));
}

function renderTypeRowEdit(tr, t) {
  tr.innerHTML = `
    <td colspan="4">
      <div class="type-edit-row">
        <input type="text" class="type-edit-input" maxlength="50" />
        <span class="type-color-slot"></span>
        <button class="type-save-btn">${escHtml(i18n.t('common.save'))}</button>
        <button type="button" class="secondary type-cancel-btn">${escHtml(i18n.t('common.cancel'))}</button>
      </div>
    </td>`;
  const input = tr.querySelector('.type-edit-input');
  input.value = t.name;
  const picker = makeColorPicker(t.color);
  tr.querySelector('.type-color-slot').replaceWith(picker.el);
  input.focus();
  input.select();
  tr.querySelector('.type-cancel-btn').addEventListener('click', () => renderTypeRowDisplay(tr, t));
  tr.querySelector('.type-save-btn').addEventListener('click', () => saveTypeEdit(t, input.value, picker.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); saveTypeEdit(t, input.value, picker.value); }
    if (e.key === 'Escape') renderTypeRowDisplay(tr, t);
  });
}

async function saveTypeEdit(t, rawName, color) {
  const name = rawName.trim();
  if (!name) { showToast(i18n.t('settings.type_name_empty'), true); return; }

  const nameChanged  = name !== t.name;
  const colorChanged = (color || null) !== (t.color || null);
  if (!nameChanged && !colorChanged) { renderTradeTypesTable(); return; }   // nothing to save

  // Renaming re-points existing trades, so confirm that; a color-only edit is silent.
  if (nameChanged) {
    const ok = await confirmDialog(
      i18n.t('settings.type_rename_confirm', { n: t.usage_count }),
      i18n.t('common.rename')
    );
    if (!ok) return;
  }

  try {
    const res = await apiFetch(`/trade-types/${t.id}`, {
      method: 'PUT',
      body: JSON.stringify({ name, color }),
    });
    showToast(nameChanged ? i18n.t('settings.type_renamed', { n: res.trades_updated })
                          : i18n.t('settings.saved'));
    await loadTradeTypes();      // refresh dropdowns + list (+ chart colors next open)
    renderTradeTypesTable();
  } catch (e) {
    showToast(e.message, true);  // e.g. duplicate name
  }
}

async function deleteTradeType(t) {
  const ok = await confirmDialog(i18n.t('settings.delete_type_confirm', { name: t.name }));
  if (!ok) return;
  clearError(tradeTypesError);
  try {
    await apiFetch(`/trade-types/${t.id}`, { method: 'DELETE' });
    showToast(i18n.t('settings.type_deleted'));
    await loadTradeTypes();
    renderTradeTypesTable();
  } catch (e) {
    if (e.status === 400) {
      showError(tradeTypesError, e.message + ' ' + i18n.t('settings.type_in_use_hint'));
    } else {
      showError(tradeTypesError, e.message);
    }
  }
}

let addTypeColorPicker = null;
document.getElementById('btn-add-trade-type').addEventListener('click', () => {
  tradeTypeFormWrap.classList.remove('hidden');
  tradeTypeNameInput.value = '';
  clearError(tradeTypeFormError);
  // Fresh color picker (defaults to "no color") mounted into the form slot.
  const slot = document.getElementById('trade-type-color-slot');
  slot.innerHTML = '';
  addTypeColorPicker = makeColorPicker(null);
  slot.appendChild(addTypeColorPicker.el);
  tradeTypeNameInput.focus();
});

document.getElementById('btn-cancel-trade-type').addEventListener('click', () => {
  tradeTypeFormWrap.classList.add('hidden');
  clearError(tradeTypeFormError);
});

tradeTypeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = tradeTypeNameInput.value.trim();
  clearError(tradeTypeFormError);
  if (!name) { showError(tradeTypeFormError, i18n.t('settings.type_name_empty')); return; }
  const color = addTypeColorPicker ? addTypeColorPicker.value : null;
  try {
    await apiFetch('/trade-types', { method: 'POST', body: JSON.stringify({ name, color }) });
    showToast(i18n.t('settings.type_added'));
    tradeTypeFormWrap.classList.add('hidden');
    await loadTradeTypes();
    renderTradeTypesTable();
  } catch (e) {
    showError(tradeTypeFormError, e.message);   // duplicate / too long
  }
});

// ── Color picker ──────────────────────────────────────────────────────────────
const _HEX_RE       = /^#[0-9a-fA-F]{6}$/;
const colorSwatch   = document.getElementById('broker-color-swatch');
const colorNative   = document.getElementById('broker-color-native');
const colorHex      = document.getElementById('broker-color-hex');
const colorClearBtn = document.getElementById('broker-color-clear');

function setColorUI(hex) {
  const valid = hex && _HEX_RE.test(hex);
  if (valid) {
    colorSwatch.style.background = hex;
    colorSwatch.classList.add('has-color');
    colorHex.value    = hex;
    colorNative.value = hex;
  } else {
    colorSwatch.style.background = '';
    colorSwatch.classList.remove('has-color');
    colorHex.value    = '';
    colorNative.value = '#000000';
  }
}

function getColorValue() {
  const v = colorHex.value.trim();
  return _HEX_RE.test(v) ? v : null;
}

colorSwatch.addEventListener('click', () => colorNative.click());

colorNative.addEventListener('input', () => setColorUI(colorNative.value));

colorHex.addEventListener('input', () => {
  let v = colorHex.value.trim();
  if (!v.startsWith('#') && v.length) v = '#' + v;
  if (_HEX_RE.test(v)) {
    colorSwatch.style.background = v;
    colorSwatch.classList.add('has-color');
    colorNative.value = v;
  } else {
    colorSwatch.style.background = '';
    colorSwatch.classList.remove('has-color');
  }
});

colorHex.addEventListener('blur', () => {
  let v = colorHex.value.trim();
  if (!v.startsWith('#') && v) v = '#' + v;
  setColorUI(_HEX_RE.test(v) ? v : null);
});

colorClearBtn.addEventListener('click', () => setColorUI(null));

// ── Broker table + form ───────────────────────────────────────────────────────
function renderBrokersTable(brokers) {
  brokersTbody.innerHTML = '';
  if (!brokers.length) {
    brokersEmpty.classList.remove('hidden');
    return;
  }
  brokersEmpty.classList.add('hidden');
  brokers.forEach(b => {
    const dot = b.color
      ? `<span class="broker-color-dot" style="background:${b.color}"></span>`
      : `<span class="broker-color-dot broker-color-dot--empty"></span>`;
    const isDefault = String(b.id) === String(appSettings.default_broker_id || '');
    const check = isDefault
      ? `<span class="broker-default-check" title="${escHtml(i18n.t('settings.default_broker_check_title'))}">${icon('check', 'icon-sm')}</span>`
      : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${dot}${escHtml(b.name)}</strong>${check}</td>
      <td>${sourceBadge(b.price_source)}</td>
      <td class="broker-notes-cell" title="${escHtml(b.notes ?? '')}">${escHtml(b.notes ?? '—')}</td>
      <td>
        <button class="secondary broker-default-btn"${isDefault ? ' disabled' : ''}>${escHtml(isDefault ? i18n.t('settings.type_default') : i18n.t('settings.broker_set_default'))}</button>
        <button class="secondary broker-edit-btn">${escHtml(i18n.t('common.edit'))}</button>
        <button class="icon-btn danger broker-del-btn" title="${escHtml(i18n.t('settings.delete_broker_title'))}" aria-label="${escHtml(i18n.t('settings.delete_broker_title'))}">${icon('trash', 'icon-sm')}</button>
      </td>
    `;
    tr.querySelector('.broker-default-btn').addEventListener('click', () => setDefaultBroker(b.id));
    tr.querySelector('.broker-edit-btn').addEventListener('click', () => openBrokerForm(b));
    tr.querySelector('.broker-del-btn').addEventListener('click', () => deleteBroker(b.id, b.name));
    brokersTbody.appendChild(tr);
  });
  brokersTable.classList.remove('hidden');
}

function openBrokerForm(broker) {
  editingBrokerId             = broker ? broker.id : null;
  brokerFormTitle.textContent = i18n.t(broker ? 'settings.edit_broker' : 'settings.add_broker');
  brokerNameInput.value         = broker ? broker.name         : '';
  brokerSourceInput.value       = broker ? broker.price_source : 'yahoo_finance';
  brokerNotesInput.value        = broker ? (broker.notes ?? '') : '';
  brokerCommFlatInput.value     = broker && broker.commission_flat     ? broker.commission_flat     : '';
  brokerCommPerUnitInput.value  = broker && broker.commission_per_unit ? broker.commission_per_unit : '';
  brokerQuoteTemplateInput.value = broker ? (broker.quote_url_template ?? '') : '';
  brokerQuoteKeyInput.value      = broker && broker.quote_url_key ? broker.quote_url_key : 'symbol';
  updateQuotePreview();
  setColorUI(broker ? broker.color : null);
  clearError(brokerFormError);
  brokerFormWrap.classList.remove('hidden');
  brokerNameInput.focus();
}

function closeBrokerForm() {
  brokerFormWrap.classList.add('hidden');
  editingBrokerId = null;
}

document.getElementById('btn-add-broker').addEventListener('click', () => {
  if (brokerFormWrap.classList.contains('hidden') || editingBrokerId !== null) {
    openBrokerForm(null);
  } else {
    closeBrokerForm();
  }
});

document.getElementById('btn-cancel-broker').addEventListener('click', closeBrokerForm);

brokerForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearError(brokerFormError);

  const name   = brokerNameInput.value.trim();
  const source = brokerSourceInput.value;
  const notes  = brokerNotesInput.value.trim() || null;
  const color  = getColorValue();
  const commissionFlat    = parseFloat(brokerCommFlatInput.value)    || 0;
  const commissionPerUnit = parseFloat(brokerCommPerUnitInput.value) || 0;
  const quoteTemplate     = brokerQuoteTemplateInput.value.trim();   // '' clears it (Yahoo fallback)
  const quoteKey          = brokerQuoteKeyInput.value || 'symbol';

  if (!name) { showError(brokerFormError, i18n.t('settings.broker_name_required')); return; }
  if (commissionFlat < 0 || commissionPerUnit < 0) {
    showError(brokerFormError, i18n.t('settings.broker_commission_negative'));
    return;
  }

  const btn  = document.getElementById('btn-save-broker');
  btn.disabled = true;
  try {
    const method = editingBrokerId ? 'PUT' : 'POST';
    const path   = editingBrokerId ? `/brokers/${editingBrokerId}` : '/brokers';
    await apiFetch(path, { method, body: JSON.stringify({
      name, price_source: source, color, notes,
      commission_flat: commissionFlat, commission_per_unit: commissionPerUnit,
      quote_url_template: quoteTemplate, quote_url_key: quoteKey,
    }) });
    closeBrokerForm();
    showToast(i18n.t(editingBrokerId ? 'settings.broker_updated' : 'settings.broker_created'));
    loadBrokers();
  } catch (e) {
    showError(brokerFormError, e.message);
  } finally {
    btn.disabled = false;
  }
});

async function setDefaultBroker(id) {
  try {
    const updated = await apiFetch('/settings', {
      method: 'PUT',
      body: JSON.stringify({ default_broker_id: id }),
    });
    Object.assign(appSettings, updated);
    showToast(i18n.t('settings.default_broker_set'));
    loadBrokers();   // re-render to move the checkmark
  } catch (e) {
    showToast(e.message, true);
  }
}

async function deleteBroker(id, name) {
  const ok = await confirmDialog(i18n.t('settings.delete_broker_confirm', { name }));
  if (!ok) return;
  try {
    await apiFetch(`/brokers/${id}`, { method: 'DELETE' });

    // If the deleted broker was the default, clear the setting.
    if (String(appSettings.default_broker_id || '') === String(id)) {
      try {
        const updated = await apiFetch('/settings', {
          method: 'PUT',
          body: JSON.stringify({ default_broker_id: '' }),
        });
        Object.assign(appSettings, updated);
      } catch (e) {
        console.warn('Failed to clear default broker:', e.message);
      }
    }

    showToast(i18n.t('settings.broker_deleted'));
    loadBrokers();
  } catch (e) {
    showToast(e.message, true);
  }
}

// ── Trade edit modal ──────────────────────────────────────────────────────────
let editingTradeId = null;

const editTradeOverlay = document.getElementById('edit-trade-overlay');
const editTradeForm    = document.getElementById('edit-trade-form');
const editTradeError   = document.getElementById('edit-trade-error');
const editTicker       = document.getElementById('edit-ticker');
const editType         = document.getElementById('edit-type');
const editAction       = document.getElementById('edit-action');
const editQuantity     = document.getElementById('edit-quantity');
const editPrice        = document.getElementById('edit-price');
const editDate         = document.getElementById('edit-date');
const editNotes        = document.getElementById('edit-notes');
const editBrokerEl     = document.getElementById('edit-broker');
const editCommission   = document.getElementById('edit-commission');
const editCommOverride = document.getElementById('edit-commission-override');
const editCommFormula  = document.getElementById('edit-commission-formula');

function updateEditCommission() {
  const broker = getBroker(editBrokerEl.value);
  const qty    = parseFloat(editQuantity.value) || 0;
  editCommFormula.textContent = commissionFormula(broker, qty, editType.value);
  if (!editCommOverride.checked) {
    editCommission.value = estimateCommission(broker, qty).toFixed(2);
  }
}

async function openEditTradeModal(trade) {
  editingTradeId     = trade.id;
  editTicker.value   = trade.ticker;
  editType.value     = trade.trade_type;   // options are the canonical type names
  editAction.value   = trade.action;
  editQuantity.value = trade.quantity;
  editPrice.value    = trade.price_per_unit;
  editDate.value     = trade.trade_date;
  editNotes.value    = trade.notes || '';
  clearError(editTradeError);
  const saveBtn = document.getElementById('btn-save-edit-trade');
  saveBtn.disabled    = false;
  saveBtn.textContent = i18n.t('common.save_changes');
  editTradeOverlay.classList.remove('hidden');
  await loadBrokerOptions(editBrokerEl);
  editBrokerEl.value = trade.broker_id != null ? String(trade.broker_id) : '';

  // Decide whether the stored commission is a manual override (differs from the
  // broker's auto estimate) and set up the field accordingly.
  const broker     = getBroker(trade.broker_id);
  const estimate   = estimateCommission(broker, trade.quantity);
  const stored     = Number(trade.commission) || 0;
  const overridden = Math.abs(stored - estimate) > 0.005;
  editCommOverride.checked  = overridden;
  editCommission.readOnly   = !overridden;
  editCommission.classList.toggle('editable', overridden);
  editCommission.value      = stored.toFixed(2);
  editCommFormula.textContent = commissionFormula(broker, trade.quantity, trade.trade_type);
}

function closeEditTradeModal() {
  editTradeOverlay.classList.add('hidden');
  editingTradeId = null;
}

editCommOverride.addEventListener('change', () => {
  editCommission.readOnly = !editCommOverride.checked;
  editCommission.classList.toggle('editable', editCommOverride.checked);
  if (editCommOverride.checked) {
    editCommission.focus();
    editCommission.select();
  } else {
    updateEditCommission();  // revert to auto estimate
  }
});
editBrokerEl.addEventListener('change', updateEditCommission);
editQuantity.addEventListener('input', updateEditCommission);
editType.addEventListener('change', updateEditCommission);

document.getElementById('edit-trade-close').addEventListener('click', closeEditTradeModal);
document.getElementById('btn-cancel-edit-trade').addEventListener('click', closeEditTradeModal);
editTradeOverlay.addEventListener('click', e => { if (e.target === editTradeOverlay) closeEditTradeModal(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !editTradeOverlay.classList.contains('hidden')) closeEditTradeModal();
});

editTradeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!editingTradeId) return;
  clearError(editTradeError);

  const ticker         = editTicker.value.trim().toUpperCase();
  const trade_type     = editType.value;
  const action         = editAction.value;
  const quantity       = parseFloat(editQuantity.value);
  const price_per_unit = parseFloat(editPrice.value);
  const trade_date     = editDate.value;
  const notes          = editNotes.value.trim() || null;
  const broker_id      = editBrokerEl.value ? parseInt(editBrokerEl.value) : null;
  // Field is kept in sync with the estimate when not overridden, so its value is
  // always what should be saved — send it explicitly.
  const commission     = parseFloat(editCommission.value) || 0;

  if (!ticker)                            { showError(editTradeError, i18n.t('trades.ticker_required')); return; }
  if (isNaN(quantity) || quantity <= 0)   { showError(editTradeError, i18n.t('trades.quantity_positive')); return; }
  if (isNaN(price_per_unit) || price_per_unit < 0) { showError(editTradeError, i18n.t('trades.price_nonneg')); return; }
  if (!trade_date)                        { showError(editTradeError, i18n.t('trades.date_required')); return; }

  const btn = document.getElementById('btn-save-edit-trade');
  btn.disabled    = true;
  btn.textContent = i18n.t('common.saving');
  try {
    await apiFetch(`/trades/${editingTradeId}`, {
      method: 'PUT',
      body: JSON.stringify({ ticker, trade_type, action, quantity, price_per_unit, trade_date, notes, broker_id, commission }),
    });
    closeEditTradeModal();
    showToast(i18n.t('trades.updated'));
    loadTrades();
  } catch (e) {
    showError(editTradeError, e.message);
    btn.disabled    = false;
    btn.textContent = i18n.t('common.save_changes');
  }
});

// ── Global keyboard shortcuts ─────────────────────────────────────────────────
const shortcutsCheatsheet = document.getElementById('shortcuts-cheatsheet');

// True when one of the real dialog overlays is showing. The cheatsheet itself is
// intentionally excluded (its id does not end in "-overlay").
function isAnyModalOpen() {
  return [...document.querySelectorAll('[id$="-overlay"]')]
    .some(el => !el.classList.contains('hidden'));
}

function toggleCheatsheet(show) {
  const willShow = show ?? shortcutsCheatsheet.classList.contains('hidden');
  shortcutsCheatsheet.classList.toggle('hidden', !willShow);
}

document.addEventListener('keydown', (e) => {
  // Never hijack browser/OS combos.
  if (e.ctrlKey || e.metaKey || e.altKey) return;

  // Escape always closes the cheatsheet, even before the guards below.
  if (e.key === 'Escape' && !shortcutsCheatsheet.classList.contains('hidden')) {
    toggleCheatsheet(false);
    return;
  }

  // Ignore shortcuts while typing in a field…
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

  // …or while a modal dialog is open.
  if (isAnyModalOpen()) return;

  switch (e.key) {
    case '/':
      if (activeUserId) { e.preventDefault(); searchInput.focus(); searchInput.select(); }
      break;
    case '?':
      e.preventDefault();
      toggleCheatsheet();
      break;
    case 'n': case 'N':
      e.preventDefault();
      switchTab('add-trade');
      instrumentInput.focus();
      break;
    case 's': case 'S':
      e.preventDefault();
      switchTab('positions');
      break;
  }
});

document.getElementById('shortcuts-fab').addEventListener('click', () => toggleCheatsheet());
document.getElementById('shortcuts-close').addEventListener('click', () => toggleCheatsheet(false));
shortcutsCheatsheet.addEventListener('click', (e) => {
  if (e.target === shortcutsCheatsheet) toggleCheatsheet(false);  // backdrop click
});

// ── Init ──────────────────────────────────────────────────────────────────────
// Load settings first so formatters are configured before anything renders.
// ── Global search (command palette) ─────────────────────────────────────────────
const searchInput   = document.getElementById('search-input');
const searchSpinner = document.getElementById('search-spinner');
const searchResults = document.getElementById('search-results');
const globalSearch  = document.getElementById('global-search');

let searchDebounce = null;
let searchSeq = 0;                  // guards against out-of-order responses
let pendingSearchHighlight = null;  // {type:'trade'|'position', key} consumed after navigation
let lastSearchData = null;          // cached so click handlers can resolve rows
let lastSearchQuery = '';           // current query, reused by the "View all" overlay

function closeSearch() {
  searchResults.classList.add('hidden');
}
function clearSearchInput() {
  clearTimeout(searchDebounce);   // cancel a queued search
  searchSeq++;                    // invalidate any in-flight response
  lastSearchData = null;
  searchInput.value = '';
  searchSpinner.classList.add('hidden');
  searchResults.innerHTML = '';
  closeSearch();
}

// Scroll a row into view and flash it briefly.
function flashEl(el) {
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.remove('row-flash');
  void el.offsetWidth;            // restart the animation if re-flashing
  el.classList.add('row-flash');
  setTimeout(() => el.classList.remove('row-flash'), 1600);
}

// Called at the end of the trades / positions render so a search-initiated
// navigation can flash the matching row once it actually exists in the DOM.
function consumeSearchHighlight(type) {
  if (!pendingSearchHighlight || pendingSearchHighlight.type !== type) return;
  const { key } = pendingSearchHighlight;
  pendingSearchHighlight = null;
  let row = null;
  if (type === 'trade')    row = tradesTbody.querySelector(`tr[data-trade-id="${key}"]`);
  if (type === 'position') row = positionsTbody.querySelector(`tr[data-ticker="${CSS.escape(String(key))}"]`);
  flashEl(row);
}

searchInput.addEventListener('input', () => {
  const q = searchInput.value.trim();
  clearTimeout(searchDebounce);
  if (q.length < 2) {
    searchSpinner.classList.add('hidden');
    closeSearch();
    return;
  }
  searchDebounce = setTimeout(() => runSearch(q), 300);
});

async function runSearch(q) {
  if (!activeUserId) return;
  const seq = ++searchSeq;
  searchSpinner.classList.remove('hidden');
  try {
    const data = await apiFetch(`/search?user_id=${activeUserId}&q=${encodeURIComponent(q)}`);
    if (seq !== searchSeq) return;   // a newer keystroke already fired
    lastSearchData = data;
    renderSearchResults(data, q);
  } catch (e) {
    if (seq !== searchSeq) return;
    searchResults.innerHTML = `<div class="sr-empty">${escHtml(i18n.t('common.search_failed', { error: e.message }))}</div>`;
    searchResults.classList.remove('hidden');
  } finally {
    if (seq === searchSeq) searchSpinner.classList.add('hidden');
  }
}

function renderSearchResults(data, q) {
  lastSearchQuery = q;
  // Each bucket is now { results, has_more, next_cursor }.
  const tradesB    = data.trades || { results: [] };
  const positionsB = data.positions || { results: [] };
  const cashB      = data.cash_transactions || { results: [] };
  const trades    = tradesB.results || [];
  const positions = positionsB.results || [];
  const cash      = cashB.results || [];

  if (!trades.length && !positions.length && !cash.length) {
    searchResults.innerHTML = `<div class="sr-empty">${escHtml(i18n.t('search.no_results', { query: q }))}</div>`;
    searchResults.classList.remove('hidden');
    return;
  }

  let html = '';
  if (trades.length)    html += _searchSection(i18n.t('search.section_trades'), tradesB, _tradeRow, 'trades');
  if (positions.length) html += _searchSection(i18n.t('search.section_positions'), positionsB, _positionRow, 'positions');
  if (cash.length)      html += _searchSection(i18n.t('search.section_cash'), cashB, _cashRow, 'cash_transactions');
  searchResults.innerHTML = html;
  searchResults.classList.remove('hidden');

  // Wire clicks for the clickable buckets (cash rows are intentionally inert).
  searchResults.querySelectorAll('.sr-trade').forEach(el => {
    el.addEventListener('click', () => {
      const t = trades[+el.dataset.i];
      pendingSearchHighlight = { type: 'trade', key: t.trade_id };
      clearSearchInput();
      switchTab('trades');
    });
  });
  searchResults.querySelectorAll('.sr-position').forEach(el => {
    el.addEventListener('click', () => {
      const p = positions[+el.dataset.i];
      pendingSearchHighlight = { type: 'position', key: p.ticker };
      clearSearchInput();
      switchTab('positions');
    });
  });
  // "View all" opens the full paginated results view for that bucket.
  searchResults.querySelectorAll('.sr-viewall').forEach(el => {
    el.addEventListener('click', () => openSearchAll(el.dataset.viewall, lastSearchQuery));
  });
}

// `bucket` is { results, has_more, ... }. We display up to 5; "View all" appears
// whenever more exist (either >5 loaded here, or has_more on the server).
function _searchSection(label, bucket, rowFn, kind) {
  const items = bucket.results || [];
  const rows = items.slice(0, 5).map((it, i) => rowFn(it, i)).join('');
  let viewAll = '';
  if (items.length > 5 || bucket.has_more) {
    const count = bucket.has_more ? `${items.length}+` : String(items.length);
    viewAll = `<div class="sr-viewall" data-viewall="${kind}">${escHtml(i18n.t('search.view_all', { n: count }))}</div>`;
  }
  return `<div class="sr-section"><div class="sr-section-header">${label}</div>${rows}${viewAll}</div>`;
}

function _tradeRow(t, i) {
  return `<div class="sr-row sr-trade" data-i="${i}">
    <strong>${escHtml(t.ticker)}</strong>
    ${badge(t.trade_type)}<span class="sr-action">${escHtml(i18n.t('trades.actions.' + t.action))}</span>
    <span class="sr-meta">${formatDate(t.trade_date)}</span>
    <span class="badge badge-${t.status}">${escHtml(i18n.t('trades.status.' + t.status))}</span>
  </div>`;
}

function _positionRow(p, i) {
  return `<div class="sr-row sr-position" data-i="${i}">
    <strong>${escHtml(p.ticker)}</strong>
    <span class="sr-meta">${formatNumber(p.total_remaining_quantity)} rem.</span>
    <span class="sr-meta">${formatCurrency(p.total_cost_basis)} basis</span>
  </div>`;
}

function _cashRow(c) {
  const cls  = c.amount >= 0 ? 'pnl-pos' : 'pnl-neg';
  const sign = c.amount > 0 ? '+' : '';
  return `<div class="sr-row sr-cash sr-inert">
    <span class="badge badge-${c.transaction_type.replace(/_/g, '-')}">${escHtml(i18n.t('cash.types.' + c.transaction_type))}</span>
    <span class="${cls}">${sign}${formatCurrency(c.amount)}</span>
    <span class="sr-meta">${escHtml(c.note ?? '')}</span>
    <span class="sr-meta">${formatDate(c.created_at)}</span>
  </div>`;
}

// ── "View all X results": full paginated results view for one bucket ────────────
const searchAllOverlay  = document.getElementById('search-all-overlay');
const searchAllTitle    = document.getElementById('search-all-title');
const searchAllList     = document.getElementById('search-all-list');
const searchAllEmpty    = document.getElementById('search-all-empty');
const searchAllError    = document.getElementById('search-all-error');
const searchAllSpinner  = document.getElementById('search-all-spinner');
const searchAllLoadmore = document.getElementById('search-all-loadmore');

// Bucket name (matches the API `type` param + response key) -> title + row renderer.
const SEARCH_ALL = {
  trades:            { titleKey: 'search.section_trades',    rowFn: _tradeRow    },
  positions:         { titleKey: 'search.section_positions', rowFn: _positionRow },
  cash_transactions: { titleKey: 'search.section_cash',      rowFn: _cashRow     },
};

let saKind = null, saQuery = '', saCursor = null, saHasMore = false;
let saItems = [], saLoading = false;

function openSearchAll(kind, q) {
  if (!SEARCH_ALL[kind] || !activeUserId) return;
  saKind = kind; saQuery = q; saItems = []; saCursor = null; saHasMore = false; saLoading = false;
  searchAllTitle.textContent = i18n.t('search.matching', { title: i18n.t(SEARCH_ALL[kind].titleKey), query: q });
  searchAllList.innerHTML = '';
  searchAllEmpty.classList.add('hidden');
  searchAllError.classList.add('hidden');
  searchAllLoadmore.classList.add('hidden');
  searchAllOverlay.classList.remove('hidden');
  closeSearch();                 // hide the dropdown behind the overlay
  fetchSearchAll(false);
}

function closeSearchAll() {
  searchAllOverlay.classList.add('hidden');
}

function fetchSearchAll(append) {
  if (saLoading) return Promise.resolve();
  saLoading = true;
  if (!append) searchAllSpinner.classList.remove('hidden');

  let url = `/search?user_id=${activeUserId}&q=${encodeURIComponent(saQuery)}&type=${saKind}`;
  if (append && saCursor) url += `&cursor=${encodeURIComponent(saCursor)}`;

  return apiFetch(url)
    .then(data => {
      const bucket = data[saKind] || { results: [] };
      const newItems = bucket.results || [];
      saHasMore = bucket.has_more;
      saCursor  = bucket.next_cursor;
      saItems = saItems.concat(newItems);
      renderSearchAllRows(newItems, append);
      updateSearchAllChrome();
    })
    .catch(e => {
      searchAllError.textContent = i18n.t('common.search_failed', { error: e.message });
      searchAllError.classList.remove('hidden');
      updateSearchAllChrome();
    })
    .finally(() => { saLoading = false; searchAllSpinner.classList.add('hidden'); });
}

function renderSearchAllRows(items, append) {
  if (!append) {
    searchAllList.innerHTML = '';
    if (!items.length) { searchAllEmpty.classList.remove('hidden'); return; }
  }
  searchAllEmpty.classList.add('hidden');
  const rowFn = SEARCH_ALL[saKind].rowFn;
  const base = append ? searchAllList.children.length : 0;
  searchAllList.insertAdjacentHTML(
    'beforeend',
    items.map((it, i) => rowFn(it, base + i)).join(''),
  );
  wireSearchAllNav();   // (re)bind via onclick so it's idempotent across appends
}

// Trades/positions rows navigate to their tab and flash; cash rows stay inert.
function wireSearchAllNav() {
  searchAllList.querySelectorAll('.sr-trade').forEach(el => {
    el.onclick = () => {
      const t = saItems[+el.dataset.i];
      pendingSearchHighlight = { type: 'trade', key: t.trade_id };
      closeSearchAll(); clearSearchInput(); switchTab('trades');
    };
  });
  searchAllList.querySelectorAll('.sr-position').forEach(el => {
    el.onclick = () => {
      const p = saItems[+el.dataset.i];
      pendingSearchHighlight = { type: 'position', key: p.ticker };
      closeSearchAll(); clearSearchInput(); switchTab('positions');
    };
  });
}

function updateSearchAllChrome() {
  renderListFooter(searchAllLoadmore, {
    loaded: saItems.length, total: saItems.length,
    hasMore: saHasMore, capped: false,
    pageSize: 20, nounP: i18n.t('common.nouns.results'),
    onMore: () => fetchSearchAll(true),
  });
}

document.getElementById('search-all-close').addEventListener('click', closeSearchAll);
searchAllOverlay.addEventListener('click', (e) => {
  if (e.target === searchAllOverlay) closeSearchAll();   // backdrop click
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !searchAllOverlay.classList.contains('hidden')) closeSearchAll();
});

searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { clearSearchInput(); searchInput.blur(); }
});
searchInput.addEventListener('focus', () => {
  if (searchInput.value.trim().length >= 2 && searchResults.innerHTML) {
    searchResults.classList.remove('hidden');
  }
});

// Clicking anywhere outside the search closes the dropdown without navigating.
document.addEventListener('click', (e) => {
  if (!globalSearch.contains(e.target)) closeSearch();
});

// Startup: load settings first so we know the configured language, load that
// locale (English fallback) before rendering any UI, then trade types + users.
loadAppSettings()
  .then(() => Promise.all([
    i18n.load(appSettings.language || 'en'),
    loadTradeTypes(),
  ]))
  .then(() => {
    i18n.applyToDOM();   // translate any static [data-i18n] markup that's present
    loadUsers();
  });
