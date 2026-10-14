/* ui/app/native.js — The desktop app's bridge
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// The native shell owns window placement: an ordinary window the person moves and resizes, with the page's own
// compact layout up to 760px.
// The app's bridge (app/src/main.rs BRIDGE_SCRIPT): one function, one message per name.
const nativeHandler = name => window.ticoNative ? window.ticoNative(name) : undefined;
