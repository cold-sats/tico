/* ui/theme.js — The colour theme, set on <html data-theme> before the page paints (styles/tokens.css).
   Dark unless this browser saved Light or System; Settings changes it through window.ticoTheme. */
'use strict';
(() => {
  const KEY = 'tico.theme', CHOICES = ['dark', 'light', 'system'];
  const saved = () => { try { const v = localStorage.getItem(KEY); return CHOICES.includes(v) ? v : 'dark'; } catch { return 'dark'; } };
  const apply = v => { document.documentElement.dataset.theme = v; };
  apply(saved());
  // Another tab of the same browser changed it: follow.
  addEventListener('storage', ev => { if (ev.key === KEY) apply(saved()); });
  window.ticoTheme = {
    choices: CHOICES,
    get: saved,
    set(v) {
      if (!CHOICES.includes(v)) return;
      try { localStorage.setItem(KEY, v); } catch { /* private window: it holds until the tab closes */ }
      apply(v);
    },
  };
})();
