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
const btnClearFilters   = document.getElementById('btn-clear-filters');
const tradesSpinner     = document.getElementById('trades-spinner');
const tradesError       = document.getElementById('trades-error');
const tradesTbody       = document.getElementById('trades-tbody');
const tradesEmpty       = document.getElementById('trades-empty');
const tradesTableWrap   = document.getElementById('trades-table-wrap');

const addTradeForm      = document.getElementById('add-trade-form');
const tradeTicker       = document.getElementById('trade-ticker');
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
    li.textContent = 'No users yet.';
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

  switchTab('trades');
}

// ── Dashboard greeting ────────────────────────────────────────────────────────
function updateGreeting() {
  const el = document.getElementById('dashboard-greeting');
  if (!el) return;
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const name = (appSettings.display_name || 'Trader').trim() || 'Trader';
  el.textContent = `${part}, ${name}`;
}

// ── Delete user ───────────────────────────────────────────────────────────────
btnDeleteUser.addEventListener('click', async () => {
  const ok = await confirmDialog(
    `Delete "${activeUserName}" and all their trades? This cannot be undone.`
  );
  if (!ok) return;

  try {
    await apiFetch(`/users/${activeUserId}`, { method: 'DELETE' });
    activeUserId   = null;
    activeUserName = null;
    userPanel.classList.add('hidden');
    emptyState.classList.remove('hidden');
    showToast('User deleted.');
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
    showError(addUserError, 'Name and email are required.');
    return;
  }

  btnSaveUser.disabled = true;
  try {
    await apiFetch('/users', { method: 'POST', body: JSON.stringify({ name, email }) });
    newUserName.value = newUserEmail.value = '';
    addUserForm.classList.add('hidden');
    showToast('User created.');
    loadUsers();
  } catch (e) {
    showError(addUserError, e.message);
  } finally {
    btnSaveUser.disabled = false;
  }
}

// ── Trades table ──────────────────────────────────────────────────────────────
async function loadTrades() {
  if (!activeUserId) return;

  tradesSpinner.classList.remove('hidden');
  tradesTableWrap.classList.add('hidden');
  clearError(tradesError);

  const params = new URLSearchParams();
  const ticker = filterTicker.value.trim();
  const type   = filterTradeType.value;
  const action = filterAction.value;
  if (ticker) params.set('ticker', ticker);
  if (type)   params.set('trade_type', type);
  if (action) params.set('action', action);

  try {
    const trades = await apiFetch(`/users/${activeUserId}/trades?${params}`);
    currentTrades = trades;
    applyTradeSort();        // re-render with the active sort preserved
    tradesTableWrap.classList.remove('hidden');
  } catch (e) {
    showError(tradesError, 'Failed to load trades: ' + e.message);
  } finally {
    tradesSpinner.classList.add('hidden');
  }
}

// ── Client-side sorting ─────────────────────────────────────────────────────────
// The most recently loaded trades, kept in memory so re-sorting never re-fetches.
let currentTrades = [];
// Active sort, or null for the default order (trade_date desc, no arrow shown).
let activeSort = null;

// Maps a header's data-sort-key to the trade field and how to compare it.
const TRADE_SORT_COLUMNS = {
  date:       { field: 'trade_date',      type: 'date'   },
  ticker:     { field: 'ticker',          type: 'string' },
  type:       { field: 'trade_type',      type: 'string' },
  action:     { field: 'action',          type: 'string' },
  quantity:   { field: 'quantity',        type: 'number' },
  price:      { field: 'price_per_unit',  type: 'number' },
  total:      { field: 'total_value',     type: 'number' },
  commission: { field: 'commission',      type: 'number' },
  net:        { field: 'net_total_value', type: 'number' },
};

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

function getSortedTrades() {
  const data = currentTrades.slice();   // Array#sort is stable, so ties keep API order
  if (!activeSort) {
    // Default order: trade_date descending.
    data.sort((a, b) => compareTradeValues(b.trade_date, a.trade_date, 'date'));
    return data;
  }
  const col  = TRADE_SORT_COLUMNS[activeSort.key];
  const sign = activeSort.dir === 'asc' ? 1 : -1;
  data.sort((a, b) => sign * compareTradeValues(a[col.field], b[col.field], col.type));
  return data;
}

function updateSortIndicators() {
  document.querySelectorAll('#trades-table th[data-sort-key]').forEach(th => {
    const arrow = th.querySelector('.sort-arrow');
    if (!arrow) return;
    if (activeSort && activeSort.key === th.dataset.sortKey) {
      arrow.textContent = activeSort.dir === 'asc' ? '↑' : '↓';
    } else {
      arrow.textContent = '';
    }
  });
}

function applyTradeSort() {
  renderTradesTable(getSortedTrades());
  updateSortIndicators();
}

function onSortHeaderClick(key) {
  if (!activeSort || activeSort.key !== key) {
    activeSort = { key, dir: 'asc' };          // 1st click: ascending
  } else if (activeSort.dir === 'asc') {
    activeSort = { key, dir: 'desc' };         // 2nd click: descending
  } else {
    activeSort = null;                         // 3rd click: back to default
  }
  applyTradeSort();
}

document.querySelectorAll('#trades-table th[data-sort-key]').forEach(th => {
  th.addEventListener('click', () => onSortHeaderClick(th.dataset.sortKey));
});

function renderTradesTable(trades) {
  tradesTbody.innerHTML = '';

  if (!trades.length) {
    tradesEmpty.classList.remove('hidden');
    return;
  }
  tradesEmpty.classList.add('hidden');

  trades.forEach(t => {
    const tr = document.createElement('tr');
    tr.dataset.tradeId = t.id;
    tr.innerHTML = `
      <td>${formatDate(t.trade_date)}</td>
      <td><strong>${escHtml(t.ticker.toUpperCase())}</strong></td>
      <td>${badge(t.trade_type)}</td>
      <td>${badge(t.action)}</td>
      <td class="num">${formatNumber(t.quantity)}</td>
      <td class="num">${formatCurrency(t.price_per_unit)}</td>
      <td class="num">${formatCurrency(t.total_value)}</td>
      <td class="num">${formatCurrency(t.commission ?? 0)}</td>
      <td class="num">${t.net_total_value != null ? formatCurrency(t.net_total_value) : '—'}</td>
      <td class="notes-cell" title="${escHtml(t.notes ?? '')}">${escHtml(t.notes ?? '—')}</td>
      <td>
        <button class="edit-btn" title="Edit trade">✏</button>
        <button class="edit-btn dup-btn" title="Duplicate trade">⧉</button>
        <button class="danger" title="Delete trade">✕</button>
      </td>
    `;
    if (t.broker_color) {
      tr.style.setProperty('--broker-color', t.broker_color);
      tr.classList.add('has-broker-color');
    }
    tr.querySelector('.edit-btn').addEventListener('click', () => openEditTradeModal(t));
    tr.querySelector('.dup-btn').addEventListener('click', () => duplicateTrade(t));
    tr.querySelector('button.danger').addEventListener('click', () => deleteTrade(t.id, t.ticker));
    tradesTbody.appendChild(tr);
  });

  consumeSearchHighlight('trade');   // flash a row if search navigated here
}

async function deleteTrade(id, ticker) {
  const ok = await confirmDialog(`Delete the ${ticker} trade? This cannot be undone.`);
  if (!ok) return;
  try {
    await apiFetch(`/trades/${id}`, { method: 'DELETE' });
    showToast('Trade deleted.');
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

  tradeTicker.value   = (t.ticker || '').toUpperCase();
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

  updateAddTradeCommission();   // recompute commission estimate + formula
  updateTotalPreview();         // refresh the total preview from qty * price

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

btnClearFilters.addEventListener('click', () => {
  filterTicker.value = '';
  filterTradeType.value = '';
  filterAction.value = '';
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
      showToast(err.detail || 'Export failed.', true);
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
    showToast('Export failed: ' + e.message, true);
  } finally {
    btn.disabled = false;
  }
});

// ── Total preview ─────────────────────────────────────────────────────────────
function updateTotalPreview() {
  const qty   = parseFloat(tradeQuantity.value);
  const price = parseFloat(tradePrice.value);
  totalPreview.textContent = (qty > 0 && price >= 0) ? formatCurrency(qty * price) : '—';
}
tradeQuantity.addEventListener('input', updateTotalPreview);
tradePrice.addEventListener('input', updateTotalPreview);

// ── Passive price autofill ──────────────────────────────────────────────────────
// On ticker blur, look up a cached price (regardless of age, no live fetch) and
// pre-fill the price field if the user hasn't typed one. Fires once per ticker.
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

async function autofillPriceFromCache() {
  const ticker = tradeTicker.value.trim().toUpperCase();

  if (!ticker) { lastAutofillTicker = ''; return; }   // cleared → allow re-fire later
  if (ticker === lastAutofillTicker) return;          // already handled this entry
  lastAutofillTicker = ticker;

  // Never overwrite a price the user typed themselves.
  if (tradePrice.value.trim() !== '') return;

  try {
    const data = await apiFetch(`/prices/${encodeURIComponent(ticker)}?cache_only=true`);
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

tradeTicker.addEventListener('blur', autofillPriceFromCache);
// Once the user edits the price, the "autofilled" note no longer applies.
tradePrice.addEventListener('input', hidePriceAutofillHint);

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
    cashWarning.textContent = 'Your cash pool is empty. Consider adding a deposit first.';
    cashWarning.classList.remove('hidden');
    return;
  }

  const qty   = parseFloat(tradeQuantity.value)   || 0;
  const price = parseFloat(tradePrice.value)      || 0;
  const comm  = parseFloat(tradeCommission.value) || 0;
  const net   = qty * price + comm;

  if (net > formCashBalance) {
    const over = net - formCashBalance;
    cashWarning.classList.remove('soft');
    cashWarning.textContent =
      `⚠ This trade (${formatCurrency(net)}) would exceed your cash balance ` +
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

  const payload = {
    ticker:         tradeTicker.value.trim().toUpperCase(),
    trade_type:     tradeType.value,
    action:         tradeAction.value,
    quantity:       parseFloat(tradeQuantity.value),
    price_per_unit: parseFloat(tradePrice.value),
    trade_date:     tradeDate.value,
    notes:          tradeNotes.value.trim() || null,
    broker_id:      tradeBrokerEl.value ? parseInt(tradeBrokerEl.value) : null,
  };
  // Only send commission when the user has overridden it; otherwise the backend
  // auto-calculates from the broker.
  if (tradeCommOverride.checked) {
    payload.commission = parseFloat(tradeCommission.value) || 0;
  }

  btnSubmitTrade.disabled = true;
  try {
    await apiFetch(`/users/${activeUserId}/trades`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('Trade added.');
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
  totalPreview.textContent = '—';
  tradeCommOverride.checked = false;
  tradeCommission.readOnly  = true;
  tradeCommission.classList.remove('editable');
  applyDefaultBroker();          // reset restores the default broker too
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

let chartMonthly   = null;
let chartByType    = null;
let chartGrowth    = null;
let growthDataFull = [];
let growthRange    = 'all';

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
    const fyStartMonth = parseInt(appSettings.fiscal_year_start_month) || 1;
    const [s, growth] = await Promise.all([
      apiFetch(`/users/${activeUserId}/stats?fiscal_year_start_month=${fyStartMonth}`),
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
  const fyMonth = fyStart.toLocaleString('en-US', { month: 'short' });
  document.getElementById('stat-fiscal-range').textContent = `${fyMonth} ${fyStart.getFullYear()} — present`;

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
  const typeColors = typeLabels.map(l => CHART_COLORS[String(l).toLowerCase()] ?? '#7b8099');

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
          label:           'Portfolio Cost Basis',
          data:            data.map(d => ({ x: d.date, y: d.cost_basis })),
          borderColor:     '#4f8ef7',
          backgroundColor: 'rgba(79,142,247,0.07)',
          fill:            false,
          borderWidth:     2,
          tension:         0.3,
          ...dot,
        },
        {
          label:           'Realized P&L',
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

// ── Helpers for price cells ────────────────────────────────────────────────────

function _priceHtml(value) {
  return value != null ? formatCurrency(value) : '<span class="price-na">—</span>';
}

function _pnlHtml(value) {
  if (value == null) return '<span class="price-na">—</span>';
  const cls  = value >= 0 ? 'pnl-pos' : 'pnl-neg';
  const sign = value > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${formatCurrency(value)}</span>`;
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

function getSortedPositions() {
  const data = currentPositions.slice();   // stable sort keeps API order for ties
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
      arrow.textContent = activePositionSort.dir === 'asc' ? '↑' : '↓';
    } else {
      arrow.textContent = '';
    }
  });
}

function applyPositionSort() {
  renderPositionsRows(getSortedPositions());
  updatePositionSortIndicators();
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
  applyPositionSort();
}

function renderPositionsRows(positions) {
  if (positionsBalance != null) positionsCashBalance.textContent = formatCurrency(positionsBalance);
  positionsTbody.innerHTML = '';

  if (!positions.length) {
    positionsEmpty.classList.remove('hidden');
    return;
  }
  positionsEmpty.classList.add('hidden');

  positions.forEach(p => {
    const tr = document.createElement('tr');
    tr.dataset.ticker = p.ticker;
    tr.innerHTML = `
      <td><strong>${escHtml(p.ticker)}</strong></td>
      <td>${badge(p.trade_type)}</td>
      <td class="num">${formatNumber(p.total_remaining_quantity)}</td>
      <td class="num">${formatCurrency(p.avg_cost_per_unit)}</td>
      <td class="num">${formatCurrency(p.total_cost_basis)}</td>
      <td class="num price-col">${_priceHtml(p.current_price)}</td>
      <td class="num price-col">${_priceHtml(p.current_value)}</td>
      <td class="num price-col">${_pnlHtml(p.unrealized_pnl)}</td>
      <td class="num price-col">${_pnlPctHtml(p.unrealized_pnl_pct)}</td>
      <td><button class="sell-btn">Sell</button></td>
    `;
    if (p.broker_color) {
      tr.style.setProperty('--broker-color', p.broker_color);
      tr.classList.add('has-broker-color');
    }
    tr.querySelector('.sell-btn').addEventListener('click', () => openSellModal(p));
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

  if (minutesAgo < 1)       label.textContent = 'Prices last updated: just now';
  else if (minutesAgo === 1) label.textContent = 'Prices last updated: 1 min ago';
  else                       label.textContent = `Prices last updated: ${minutesAgo} min ago`;
}

// ── Refresh prices ─────────────────────────────────────────────────────────────
document.getElementById('btn-refresh-prices').addEventListener('click', async () => {
  if (!activeUserId) return;

  const tickers = [...new Set(
    Array.from(positionsTbody.querySelectorAll('tr[data-ticker]'))
      .map(tr => tr.dataset.ticker)
  )];
  if (!tickers.length) return;

  const btn   = document.getElementById('btn-refresh-prices');
  const label = document.getElementById('prices-last-updated');
  btn.disabled     = true;
  label.textContent = 'Refreshing…';
  showPriceSkeleton();

  try {
    await apiFetch('/prices/refresh', {
      method: 'POST',
      body: JSON.stringify({ tickers, source: 'yahoo_finance' }),
    });
  } catch (e) {
    showToast('Price refresh failed: ' + e.message, true);
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
    showToast('Failed to reload positions: ' + e.message, true);
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

  sellModalTicker.textContent = position.ticker;
  sellModalTypeBadge.className = `badge badge-${position.trade_type}`;
  sellModalTypeBadge.textContent = position.trade_type;

  sellLotsTbody.innerHTML = lots.map(lot => `
    <tr>
      <td>${formatDate(lot.trade_date)}${lot.status === 'partial' ? '<span class="lot-status-partial">(partial)</span>' : ''}</td>
      <td class="num">${formatNumber(lot.remaining_quantity)}</td>
      <td class="num">${formatCurrency(lot.price_per_unit)}</td>
    </tr>
  `).join('');

  const maxQty = position.total_remaining_quantity;
  sellQtyInput.max   = maxQty;
  sellMaxHint.textContent = `max ${formatNumber(maxQty)}`;
  sellQtyInput.value  = '';
  sellPriceInput.value = '';
  sellDateInput.value  = todayISO();
  sellNotesInput.value = '';

  sellPreviewBar.className = 'sell-preview-bar hidden';
  clearError(sellErrorEl);
  sellConfirmBtn.disabled    = false;
  sellConfirmBtn.textContent = 'Confirm Sale';

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
function computeSellEstimate(lots, qtySold, sellPrice) {
  let remaining   = qtySold;
  let costBasis   = 0;   // gross buy cost of the shares being sold
  let sellComm    = 0;   // estimated sell-side commission
  let buyCommProp = 0;   // proportional buy-side commission

  for (const lot of lots) {
    if (remaining <= 1e-9) break;
    const allocated = Math.min(lot.remaining_quantity, remaining);
    costBasis += allocated * lot.price_per_unit;
    sellComm  += estimateCommission(getBroker(lot.broker_id), allocated);
    if (lot.quantity > 0) {
      buyCommProp += (allocated / lot.quantity) * (lot.commission || 0);
    }
    remaining -= allocated;
  }

  const proceeds    = qtySold * sellPrice;
  const netProceeds = proceeds - sellComm;
  const netCost     = costBasis + buyCommProp;
  return {
    proceeds, sellComm, costBasis, buyCommProp,
    netProceeds, netCost,
    netPnl: netProceeds - netCost,
  };
}

function updateSellPreview() {
  const qty   = parseFloat(sellQtyInput.value);
  const price = parseFloat(sellPriceInput.value);

  if (!currentSellPosition || !(qty > 0) || !(price >= 0)) {
    sellPreviewBar.className = 'sell-preview-bar hidden';
    return;
  }

  const est  = computeSellEstimate(currentSellPosition.lots, qty, price);
  const sign = est.netPnl >= 0 ? '+' : '';

  sellPreviewBar.innerHTML =
    `<div class="sell-preview-line"><span>Proceeds</span><span>${formatCurrency(est.proceeds)}</span></div>` +
    `<div class="sell-preview-line"><span>Est. commission</span><span>−${formatCurrency(est.sellComm)}</span></div>` +
    `<div class="sell-preview-line sell-preview-total"><span>Net P&amp;L</span>` +
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

  sellConfirmBtn.disabled    = true;
  sellConfirmBtn.textContent = 'Selling…';

  try {
    for (const alloc of allocations) {
      await apiFetch(`/trades/${alloc.tradeId}/sell`, {
        method: 'POST',
        body: JSON.stringify({
          quantity_sold:       alloc.qty,
          sell_price_per_unit: price,
          sell_date:           date,
          notes,
        }),
      });
    }
    closeSellModal();
    showToast('Sale recorded.');
    loadPositions(); // refreshes both positions table and cash balance
  } catch (e) {
    showError(sellErrorEl, e.message);
    sellConfirmBtn.disabled    = false;
    sellConfirmBtn.textContent = 'Confirm Sale';
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

function openSettings() {
  settingThemeEl.querySelectorAll('.opt-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.value === currentSettings.theme));
  settingZoomEl.value = currentSettings.zoom;
  zoomDisplayEl.textContent = Math.round(currentSettings.zoom * 100) + '%';
  settingSidebarEl.querySelectorAll('.opt-btn').forEach(b =>
    b.classList.toggle('active', +b.dataset.value === currentSettings.sidebarWidth));
  settingDensityEl.querySelectorAll('.opt-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.value === currentSettings.density));
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

    if (item.dataset.page === 'general')     populateGeneralSettings();
    if (item.dataset.page === 'brokers')     loadBrokers();
    if (item.dataset.page === 'trade-types') loadTradeTypesPage();
    if (item.dataset.page === 'data')        { clearRestoreResult(); loadPriceCacheCount(); }
  });
});

// ── General settings page (auto-save) ─────────────────────────────────────────
function updateDateFormatPreview() {
  const fmt = document.getElementById('setting-date-format').value;
  document.getElementById('date-format-preview').textContent =
    'Preview: ' + formatDate(_localISO(new Date()), fmt);
}

// Reflect the current appSettings into the form controls.
function populateGeneralSettings() {
  document.getElementById('setting-display-name').value      = appSettings.display_name ?? '';
  document.getElementById('setting-currency').value          = appSettings.currency ?? 'USD';
  document.getElementById('setting-date-format').value       = appSettings.date_format ?? 'MM/DD/YYYY';
  document.getElementById('setting-decimal-separator').value = appSettings.decimal_separator ?? '.';
  document.getElementById('setting-refresh-interval').value  = String(appSettings.price_refresh_interval_minutes ?? '15');
  document.getElementById('setting-fiscal-month').value      = String(appSettings.fiscal_year_start_month ?? '1');
  updateDateFormatPreview();
}

const _statusTimers = new WeakMap();
function showSettingStatus(el, state, msg) {
  if (!el) return;
  clearTimeout(_statusTimers.get(el));
  if (state === 'saved') {
    el.textContent = '✓ Saved';
    el.className = 'settings-status saved';
    _statusTimers.set(el, setTimeout(() => {
      el.textContent = '';
      el.className = 'settings-status';
    }, 2000));
  } else {
    el.textContent = msg || 'Failed to save';
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
    showSettingStatus(statusEl, 'failed', 'Failed to save');
  }
}

document.querySelectorAll('#page-general [data-key]').forEach(el => {
  el.addEventListener('change', () => {
    const key = el.dataset.key;
    const statusEl = document.querySelector(`#page-general [data-status="${key}"]`);
    saveSetting(key, el.value, statusEl);
  });
});
document.getElementById('setting-date-format').addEventListener('change', updateDateFormatPreview);

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
    setRestoreResult('Choose a .db backup file first.', 'error');
    return;
  }

  const ok = await confirmDialog(
    'This will replace all current data with the backup. A safety backup of your current data will be created first. Continue?',
    'Continue'
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
    setRestoreResult('Database restored successfully. Reloading…', 'success');
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
  priceCacheCount.textContent = `${n} ticker${n === 1 ? '' : 's'} cached`;
}

async function loadPriceCacheCount() {
  cacheResult.className = 'hidden';
  cacheResult.textContent = '';
  try {
    const { count } = await apiFetch('/settings/price-cache');
    setCacheCount(count);
  } catch (e) {
    priceCacheCount.textContent = 'Cache size unavailable';
  }
}

btnClearCache.addEventListener('click', async () => {
  cacheResult.className = 'hidden';
  btnClearCache.disabled = true;
  try {
    const { deleted } = await apiFetch('/settings/price-cache', { method: 'DELETE' });
    setCacheCount(0);
    cacheResult.textContent = `Cleared ${deleted} cached price${deleted === 1 ? '' : 's'}.`;
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
const brokerFormError   = document.getElementById('broker-form-error');
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
    showError(brokersError, 'Failed to load brokers: ' + e.message);
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
  fillTypeSelect(filterTradeType, 'All types');
  fillTypeSelect(tradeType, 'Select…');
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

function renderTypeRowDisplay(tr, t) {
  const typeBadge = t.is_default
    ? '<span class="badge badge-default-type">Default</span>'
    : '<span class="badge badge-custom-type">Custom</span>';
  // Default types cannot be deleted, so they get no Delete button.
  const delBtn = t.is_default ? '' : '<button class="danger type-del-btn" title="Delete type">✕</button>';
  tr.innerHTML = `
    <td><strong>${escHtml(t.name)}</strong></td>
    <td class="num">${t.usage_count}</td>
    <td>${typeBadge}</td>
    <td>
      <button class="secondary type-edit-btn">Edit</button>
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
        <button class="type-save-btn">Save</button>
        <button type="button" class="secondary type-cancel-btn">Cancel</button>
      </div>
    </td>`;
  const input = tr.querySelector('.type-edit-input');
  input.value = t.name;
  input.focus();
  input.select();
  tr.querySelector('.type-cancel-btn').addEventListener('click', () => renderTypeRowDisplay(tr, t));
  tr.querySelector('.type-save-btn').addEventListener('click', () => saveTypeRename(t, input.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); saveTypeRename(t, input.value); }
    if (e.key === 'Escape') renderTypeRowDisplay(tr, t);
  });
}

async function saveTypeRename(t, rawName) {
  const name = rawName.trim();
  if (!name) { showToast('Name cannot be empty.', true); return; }
  if (name === t.name) { renderTradeTypesTable(); return; }   // no change

  const ok = await confirmDialog(
    `Renaming this type will update all ${t.usage_count} trades that use it. Continue?`,
    'Rename'
  );
  if (!ok) return;

  try {
    const res = await apiFetch(`/trade-types/${t.id}`, {
      method: 'PUT',
      body: JSON.stringify({ name }),
    });
    showToast(`Renamed. ${res.trades_updated} trades updated.`);
    await loadTradeTypes();      // refresh dropdowns + list
    renderTradeTypesTable();
  } catch (e) {
    showToast(e.message, true);  // e.g. duplicate name
  }
}

async function deleteTradeType(t) {
  const ok = await confirmDialog(`Delete trade type "${t.name}"?`);
  if (!ok) return;
  clearError(tradeTypesError);
  try {
    await apiFetch(`/trade-types/${t.id}`, { method: 'DELETE' });
    showToast('Trade type deleted.');
    await loadTradeTypes();
    renderTradeTypesTable();
  } catch (e) {
    if (e.status === 400) {
      showError(tradeTypesError, e.message + ' Reassign those trades before deleting this type.');
    } else {
      showError(tradeTypesError, e.message);
    }
  }
}

document.getElementById('btn-add-trade-type').addEventListener('click', () => {
  tradeTypeFormWrap.classList.remove('hidden');
  tradeTypeNameInput.value = '';
  clearError(tradeTypeFormError);
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
  if (!name) { showError(tradeTypeFormError, 'Name cannot be empty.'); return; }
  try {
    await apiFetch('/trade-types', { method: 'POST', body: JSON.stringify({ name }) });
    showToast('Trade type added.');
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
      ? '<span class="broker-default-check" title="Default broker">✓</span>'
      : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${dot}${escHtml(b.name)}</strong>${check}</td>
      <td>${sourceBadge(b.price_source)}</td>
      <td class="broker-notes-cell" title="${escHtml(b.notes ?? '')}">${escHtml(b.notes ?? '—')}</td>
      <td>
        <button class="secondary broker-default-btn"${isDefault ? ' disabled' : ''}>${isDefault ? 'Default' : 'Set as default'}</button>
        <button class="secondary broker-edit-btn">Edit</button>
        <button class="danger broker-del-btn" title="Delete broker">✕</button>
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
  brokerFormTitle.textContent = broker ? 'Edit Broker' : 'Add Broker';
  brokerNameInput.value         = broker ? broker.name         : '';
  brokerSourceInput.value       = broker ? broker.price_source : 'yahoo_finance';
  brokerNotesInput.value        = broker ? (broker.notes ?? '') : '';
  brokerCommFlatInput.value     = broker && broker.commission_flat     ? broker.commission_flat     : '';
  brokerCommPerUnitInput.value  = broker && broker.commission_per_unit ? broker.commission_per_unit : '';
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

  if (!name) { showError(brokerFormError, 'Name is required.'); return; }
  if (commissionFlat < 0 || commissionPerUnit < 0) {
    showError(brokerFormError, 'Commission fees cannot be negative.');
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
    }) });
    closeBrokerForm();
    showToast(editingBrokerId ? 'Broker updated.' : 'Broker created.');
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
    showToast('Default broker set.');
    loadBrokers();   // re-render to move the checkmark
  } catch (e) {
    showToast(e.message, true);
  }
}

async function deleteBroker(id, name) {
  const ok = await confirmDialog(`Delete broker "${name}"? This cannot be undone.`);
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

    showToast('Broker deleted.');
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
  saveBtn.textContent = 'Save Changes';
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

  if (!ticker)                            { showError(editTradeError, 'Ticker is required.'); return; }
  if (isNaN(quantity) || quantity <= 0)   { showError(editTradeError, 'Quantity must be greater than 0.'); return; }
  if (isNaN(price_per_unit) || price_per_unit < 0) { showError(editTradeError, 'Price must be ≥ 0.'); return; }
  if (!trade_date)                        { showError(editTradeError, 'Trade date is required.'); return; }

  const btn = document.getElementById('btn-save-edit-trade');
  btn.disabled    = true;
  btn.textContent = 'Saving…';
  try {
    await apiFetch(`/trades/${editingTradeId}`, {
      method: 'PUT',
      body: JSON.stringify({ ticker, trade_type, action, quantity, price_per_unit, trade_date, notes, broker_id, commission }),
    });
    closeEditTradeModal();
    showToast('Trade updated.');
    loadTrades();
  } catch (e) {
    showError(editTradeError, e.message);
    btn.disabled    = false;
    btn.textContent = 'Save Changes';
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
      tradeTicker.focus();
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

function closeSearch() {
  searchResults.classList.add('hidden');
}
function clearSearchInput() {
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
    searchResults.innerHTML = `<div class="sr-empty">Search failed: ${escHtml(e.message)}</div>`;
    searchResults.classList.remove('hidden');
  } finally {
    if (seq === searchSeq) searchSpinner.classList.add('hidden');
  }
}

function renderSearchResults(data, q) {
  const trades = data.trades || [];
  const positions = data.positions || [];
  const cash = data.cash_transactions || [];

  if (!trades.length && !positions.length && !cash.length) {
    searchResults.innerHTML = `<div class="sr-empty">No results for “${escHtml(q)}”</div>`;
    searchResults.classList.remove('hidden');
    return;
  }

  let html = '';
  if (trades.length)    html += _searchSection('Trades', trades, _tradeRow, 'trades');
  if (positions.length) html += _searchSection('Positions', positions, _positionRow, 'positions');
  if (cash.length)      html += _searchSection('Cash Transactions', cash, _cashRow, 'cash');
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
  searchResults.querySelectorAll('.sr-viewall:not(.sr-inert)').forEach(el => {
    el.addEventListener('click', () => {
      const kind = el.dataset.viewall;
      clearSearchInput();
      if (kind === 'trades')    switchTab('trades');
      if (kind === 'positions') switchTab('positions');
    });
  });
}

function _searchSection(label, items, rowFn, kind) {
  const rows = items.slice(0, 5).map((it, i) => rowFn(it, i)).join('');
  let viewAll = '';
  if (items.length > 5) {
    const inert = kind === 'cash' ? ' sr-inert' : '';
    viewAll = `<div class="sr-viewall${inert}" data-viewall="${kind}">View all ${items.length} results</div>`;
  }
  return `<div class="sr-section"><div class="sr-section-header">${label}</div>${rows}${viewAll}</div>`;
}

function _tradeRow(t, i) {
  return `<div class="sr-row sr-trade" data-i="${i}">
    <strong>${escHtml(t.ticker)}</strong>
    ${badge(t.trade_type)}<span class="sr-action">${escHtml(t.action)}</span>
    <span class="sr-meta">${formatDate(t.trade_date)}</span>
    ${badge(t.status)}
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
    ${badge(c.transaction_type)}
    <span class="${cls}">${sign}${formatCurrency(c.amount)}</span>
    <span class="sr-meta">${escHtml(c.note ?? '')}</span>
    <span class="sr-meta">${formatDate(c.created_at)}</span>
  </div>`;
}

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

// Load settings + trade types once on startup, then the user list.
Promise.all([loadAppSettings(), loadTradeTypes()]).then(loadUsers);
