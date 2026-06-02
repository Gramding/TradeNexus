// frontend/i18n.js — a self-contained translation engine. No external libraries.
//
// Exposes window.i18n with: load(lang), t(key, vars), setLanguage(lang),
// applyToDOM(root). Translations are nested JSON keyed by dot-notation paths
// (see frontend/locales/*.json). English is always kept as a silent fallback.
(function () {
  'use strict';

  const DEFAULT_LANG  = 'en';
  const LOCALES_PATH  = 'locales';                 // relative to index.html
  const API_ROOT      = (typeof API !== 'undefined') ? API : 'http://localhost:8765';

  const i18n = {
    currentLang: DEFAULT_LANG,
    _active:   {},   // active-language translation tree
    _fallback: {},   // English tree, loaded once, used when a key is missing
  };

  // ── Internals ────────────────────────────────────────────────────────────────

  // Resolve a dot-notation key against a nested object. Returns the string value,
  // or undefined if any segment is missing or the leaf isn't a string.
  function _lookup(tree, key) {
    let cur = tree;
    const parts = key.split('.');
    for (const part of parts) {
      if (cur == null || typeof cur !== 'object' || !(part in cur)) return undefined;
      cur = cur[part];
    }
    return typeof cur === 'string' ? cur : undefined;
  }

  // Active language first, then the English fallback. undefined if neither has it.
  function _resolve(key) {
    const hit = _lookup(i18n._active, key);
    return hit !== undefined ? hit : _lookup(i18n._fallback, key);
  }

  // Replace {placeholders} in a template from vars. Unknown placeholders are left
  // intact so a missing var is visible rather than silently blanked.
  function _interpolate(template, vars) {
    if (!vars) return template;
    return template.replace(/\{(\w+)\}/g, function (whole, name) {
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole;
    });
  }

  async function _fetchLocale(lang) {
    const res = await fetch(LOCALES_PATH + '/' + lang + '.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error('HTTP ' + res.status + ' loading ' + lang + '.json');
    return res.json();
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  // Fetch locales/{lang}.json and make it the active set. Always ensures the
  // English fallback is loaded too. Falls back to English if the requested file
  // fails to load. Returns a promise resolving to the active translation tree.
  i18n.load = async function (lang) {
    lang = lang || DEFAULT_LANG;

    // Load (and keep) the English fallback exactly once.
    if (!i18n._fallback || Object.keys(i18n._fallback).length === 0) {
      try {
        i18n._fallback = await _fetchLocale(DEFAULT_LANG);
      } catch (e) {
        console.warn('i18n: could not load fallback ' + DEFAULT_LANG + '.json:', e.message);
        i18n._fallback = {};
      }
    }

    if (lang === DEFAULT_LANG) {
      i18n._active = i18n._fallback;
      i18n.currentLang = DEFAULT_LANG;
      return i18n._active;
    }

    try {
      i18n._active = await _fetchLocale(lang);
      i18n.currentLang = lang;
    } catch (e) {
      console.warn('i18n: could not load ' + lang + '.json, falling back to ' + DEFAULT_LANG + ':', e.message);
      i18n._active = i18n._fallback;
      i18n.currentLang = DEFAULT_LANG;
    }
    return i18n._active;
  };

  // Translate a dot-notation key, interpolating {vars}. Missing keys fall back to
  // English, then to the key itself (so gaps are visible but never break the UI).
  i18n.t = function (key, vars) {
    if (!key) return '';

    // Nested pluralization for common.ago: pick the singular/plural unit label
    // (n === 1 -> singular) and interpolate it into the localized "ago" template.
    if (key === 'common.ago' && vars && vars.unit != null) {
      const base       = String(vars.unit).toLowerCase().replace(/s$/, '');   // "hours" -> "hour"
      const plural     = Number(vars.n) !== 1;
      const unitLabel  = _resolve('common.units.' + base + (plural ? 's' : '')) || vars.unit;
      const template   = _resolve('common.ago');
      if (template === undefined) return key;
      return _interpolate(template, { n: vars.n, unit: unitLabel });
    }

    const template = _resolve(key);
    if (template === undefined) return key;
    return _interpolate(template, vars);
  };

  // Re-render every translated element in the DOM (or within `root`).
  i18n.applyToDOM = function (root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = i18n.t(el.getAttribute('data-i18n'));
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      el.setAttribute('placeholder', i18n.t(el.getAttribute('data-i18n-placeholder')));
    });
    root.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      el.setAttribute('title', i18n.t(el.getAttribute('data-i18n-title')));
    });
  };

  // Switch language: load it, persist to settings, then re-render the DOM.
  i18n.setLanguage = async function (lang) {
    await i18n.load(lang);

    // Keep the shared appSettings object (formatting.js) in sync if it's present.
    if (typeof appSettings !== 'undefined' && appSettings) {
      appSettings.language = i18n.currentLang;
    }

    // Persist via PUT /settings. A failure here shouldn't block the re-render —
    // the language is already loaded for this session.
    try {
      const res = await fetch(API_ROOT + '/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: i18n.currentLang }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
    } catch (e) {
      console.warn('i18n: failed to persist language to settings:', e.message);
    }

    i18n.applyToDOM();
    return i18n.currentLang;
  };

  window.i18n = i18n;
})();
