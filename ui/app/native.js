/* ui/app/native.js — The desktop app's bridge: window mode and the rail button
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// The native shell owns window placement.
// The app's bridge (app/src/main.rs BRIDGE_SCRIPT): one function, one message per name.
const nativeHandler = name => window.ticoNative ? window.ticoNative(name) : undefined;
window.ticoWindowModeChanged = mode => {
  document.body.classList.toggle('rail-mode', mode === 'rail');
  const button = $('#rail'); if (!button) return;
  const rail = mode === 'rail';
  button.textContent = rail ? '⇤' : '⇥';
  const label = rail ? 'Return to full window' : 'Move to right rail';
  button.title = label; button.setAttribute('aria-label', label);
};
$('#rail').onclick = () => nativeHandler('windowMode')?.postMessage('toggle');
