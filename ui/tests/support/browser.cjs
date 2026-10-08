// Preloaded by the runner: scripts use Playwright directly, including ones that do not serve page.cjs.
// Wrap its public creation methods so defaults are set before the script starts using a page.
const {applyTimeouts} = require('./load.cjs');
const playwright = require('playwright');

function contextTimeouts(context) {
  applyTimeouts(context);
  context.on('page', applyTimeouts);
  return context;
}

for (const engine of [playwright.chromium, playwright.firefox, playwright.webkit]) {
  const launch = engine.launch;
  engine.launch = async function (...args) {
    const browser = await launch.apply(this, args);
    const newContext = browser.newContext;
    browser.newContext = async function (...options) {
      return contextTimeouts(await newContext.apply(this, options));
    };
    return browser;
  };
  const persistent = engine.launchPersistentContext;
  engine.launchPersistentContext = async function (...args) {
    return contextTimeouts(await persistent.apply(this, args));
  };
}
