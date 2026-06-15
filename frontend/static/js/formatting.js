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
  base_currency: 'USD',
  language: 'en',
  date_format: 'MM/DD/YYYY',
  date_format_manual_override: '0',
  decimal_separator: '.',
  price_refresh_interval_minutes: '15',
  price_source: 'yahoo_finance',
  default_broker_id: '',
  fiscal_year_start_month: '1',
};

// Locale inferred from currency, per spec: USD → en-US, EUR → de-DE, GBP → en-GB.
const CURRENCY_LOCALE = { USD: 'en-US', EUR: 'de-DE', GBP: 'en-GB' };

// The portfolio's reporting currency: base_currency (multi-currency reporting
// base) falling back to the legacy `currency` setting. All base-currency money
// — stats, cash balance, converted totals — formats with this.
function reportingCurrency() {
  return appSettings.base_currency || appSettings.currency || 'USD';
}

// Resolve the locale for currency/number formatting. The base comes from the
// currency, but an explicit decimal_separator overrides it so the user always
// gets the separator they chose (the currency symbol still comes from the
// `currency` option, independent of locale).
function _activeLocale() {
  const base = CURRENCY_LOCALE[reportingCurrency()] || 'en-US';
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
    currency: reportingCurrency(),
  }).format(safe);
}

// Format an amount in an explicit currency code (e.g. a position held in EUR
// while the base currency is USD). Falls back to the reporting currency.
function formatCurrencyIn(value, code) {
  const n = Number(value);
  const safe = Number.isFinite(n) ? n : 0;
  try {
    return new Intl.NumberFormat(_activeLocale(), {
      style: 'currency',
      currency: code || reportingCurrency(),
    }).format(safe);
  } catch {
    return formatCurrency(safe);  // unknown code → reporting currency
  }
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
    currency: reportingCurrency(),
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

// formatDateTime('2026-06-08 14:32:07') → "06/08/2026, 14:32:07": the date in the
// user's date_format plus 24-hour time to the second. The date part still routes
// through formatDate, so the day-format setting is honored.
//   - utc:false (default) — the value is a naive local timestamp (user-entered
//     trade/event datetimes from a datetime-local input); shown verbatim.
//   - utc:true — the value is a UTC server timestamp (e.g. created_at); converted
//     to the viewer's local time before formatting.
// A date-only value (legacy rows with no time) falls back to formatDate — there is
// no time to show — so this is always safe to call on mixed old/new data.
function formatDateTime(value, { utc = false } = {}) {
  if (!value) return '';
  const s = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return formatDate(s);   // date-only → no time
  const m = s.replace(' ', 'T').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return formatDate(s);   // unrecognized shape — best-effort date only
  let y, mo, d, hh, mi, ss;
  if (utc) {
    const dt = new Date(`${s.replace(' ', 'T')}Z`);
    if (isNaN(dt.getTime())) return formatDate(s);
    const p = (n) => String(n).padStart(2, '0');
    [y, mo, d] = [dt.getFullYear(), p(dt.getMonth() + 1), p(dt.getDate())];
    [hh, mi, ss] = [p(dt.getHours()), p(dt.getMinutes()), p(dt.getSeconds())];
  } else {
    [, y, mo, d, hh, mi, ss] = m;
    ss = ss || '00';
  }
  return `${formatDate(`${y}-${mo}-${d}`)}, ${hh}:${mi}:${ss}`;
}
