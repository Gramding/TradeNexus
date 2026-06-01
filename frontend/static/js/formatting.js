// ── Centralized number / date formatting ──────────────────────────────────────
// Every place in the UI that shows money, a number, or a date MUST go through
// these functions — never format inline. They read the live appSettings object,
// which app.js loads once from GET /settings on startup.

// Global app settings. Defaults match the DB seed so formatting works before the
// fetch resolves (or if it fails). app.js merges the server values into this same
// object via Object.assign, so all formatters pick up the change automatically.
const appSettings = {
  display_name: 'Trader',
  currency: 'USD',
  language: 'en',
  date_format: 'MM/DD/YYYY',
  date_format_manual_override: '0',
  decimal_separator: '.',
  price_refresh_interval_minutes: '15',
  default_broker_id: '',
  fiscal_year_start_month: '1',
};

// Locale inferred from currency, per spec: USD → en-US, EUR → de-DE, GBP → en-GB.
const CURRENCY_LOCALE = { USD: 'en-US', EUR: 'de-DE', GBP: 'en-GB' };

// Resolve the locale for currency/number formatting. The base comes from the
// currency, but an explicit decimal_separator overrides it so the user always
// gets the separator they chose (the currency symbol still comes from the
// `currency` option, independent of locale).
function _activeLocale() {
  const base = CURRENCY_LOCALE[appSettings.currency] || 'en-US';
  if (appSettings.decimal_separator === ',') return 'de-DE';            // comma decimal
  if (appSettings.decimal_separator === '.') return base === 'de-DE' ? 'en-US' : base;  // dot decimal
  return base;
}

// formatCurrency(1234.5) → "$1,234.50" (USD) / "1.234,50 €" (EUR, comma separator)
function formatCurrency(value) {
  const n = Number(value);
  const safe = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat(_activeLocale(), {
    style: 'currency',
    currency: appSettings.currency || 'USD',
  }).format(safe);
}

// Plain number display (quantities, share counts) — honors the decimal separator
// but has no currency symbol.
function formatNumber(value, maxFractionDigits = 6) {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return '—';
  return new Intl.NumberFormat(_activeLocale(), { maximumFractionDigits: maxFractionDigits }).format(n);
}

// The active currency symbol on its own (for compact chart axes, etc.).
function currencySymbol() {
  const part = new Intl.NumberFormat(_activeLocale(), {
    style: 'currency',
    currency: appSettings.currency || 'USD',
  }).formatToParts(0).find(p => p.type === 'currency');
  return part ? part.value : '$';
}

// formatDate('2025-06-01') → "06/01/2025" (MM/DD/YYYY) etc. Parses the date part
// directly (no Date object) to avoid any timezone shifting.
// formatOverride lets callers preview a format other than the saved one (e.g. the
// settings page); when omitted it uses the active appSettings.date_format.
function formatDate(isoString, formatOverride) {
  if (!isoString) return '';
  const m = String(isoString).slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return String(isoString);   // not a recognized ISO date — show as-is
  const [, y, mo, d] = m;
  switch (formatOverride || appSettings.date_format) {
    case 'DD/MM/YYYY': return `${d}/${mo}/${y}`;
    case 'DD.MM.YYYY': return `${d}.${mo}.${y}`;
    case 'YYYY-MM-DD': return `${y}-${mo}-${d}`;
    case 'MM/DD/YYYY':
    default:           return `${mo}/${d}/${y}`;
  }
}
