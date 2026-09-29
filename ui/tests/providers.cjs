// Offline browser regression for the AI provider choice: a company that has not chosen yet gets
// "Which AI providers do you use?" as the first setup step, the default model list follows the
// ticked providers, Next saves through PUT /api/v2/providers with the revision it read, and
// Settings -> AI providers shows and edits the same choice. Fixtures only - no server, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const CONFIG = {environment_id: 'initech', company_name: 'Initech', app_name: 'Initech Hub',
  assistant_name: 'Ace', assistant_bot: 'coo', public_url: 'https://initech.test',
  runner_url: 'https://initech.test', github_owner: '', local: false, release: '',
  onboarding_needed: true, providers_configured: false};
const PROVIDERS = [
  {id: 'openai', label: 'OpenAI', runtime: 'codex', detail: 'Codex CLI', recommended: 'gpt-6-sol'},
  {id: 'anthropic', label: 'Anthropic', runtime: 'claude', detail: 'Claude Code', recommended: 'claude-opus-5'},
  {id: 'xai', label: 'xAI', runtime: 'grok', detail: 'Grok Build', recommended: 'grok-4.6'},
];
const MODELS = [
  {id: 'gpt-6-sol', label: 'gpt 6 sol', runtime: 'codex', provider: 'openai', efforts: ['high'], default_effort: 'high'},
  {id: 'gpt-5.6-sol', label: 'gpt 5.6 sol', runtime: 'codex', provider: 'openai', deprecated: true, efforts: ['low'], default_effort: 'low'},
  {id: 'claude-opus-5', label: 'opus 5', runtime: 'claude', provider: 'anthropic', efforts: ['high'], default_effort: 'high'},
  {id: 'claude-opus-5-5', label: 'opus 5.5', runtime: 'claude', provider: 'anthropic', efforts: ['high'], default_effort: 'high'},
  {id: 'grok-4.6', label: 'grok 4.6', runtime: 'grok', provider: 'xai', efforts: ['high'], default_effort: 'high'},
];

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const context = await browser.newContext({viewport: {width: 1100, height: 800}, serviceWorkers: 'block'});
    const puts = [];
    let choice = {configured: false, enabled: [], default: {runtime: '', model: ''}, revision: 0,
                  source: '', providers: PROVIDERS.map(row => ({...row, enabled: false}))};
    const view = () => ({...choice, providers: PROVIDERS.map(row => ({...row, enabled: choice.enabled.includes(row.id)}))});
    const me = {id: 'ana', name: 'Ana Rivera', role: 'owner', cloud: true, email: 'ana@acme.example', credential_access: false, config: CONFIG};
    await context.route('**/*', async route => {
      const request = route.request(), p = new URL(request.url()).pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const module = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (module) {
        const file = path.join(__dirname, '..', module[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
      }
      if (p === '/api/me') return json(me);
      if (p === '/api/v2/config') return json({...CONFIG, providers_configured: choice.configured});
      if (p === '/api/status') return json({cloud: true, keeper_alive: true, health_issues: [], active: [], recent_runs: []});
      if (p === '/api/employees') return json([]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/v2/catalog') return json({cards: []});
      if (p === '/api/v2/onboarding') return json({names: {company_name: 'Initech', app_name: 'Initech Hub', assistant_name: 'Ace'},
        answers: {}, selected: {}, completed: null, bots: [], machine: {runners: [], enrolled: false}, needed: true, recommended: []});
      if (p === '/api/v2/providers') {
        if (request.method() === 'PUT') {
          const body = request.postDataJSON();
          puts.push(body);
          const model = MODELS.find(row => row.id === body.model);
          choice = {...choice, configured: true, enabled: body.enabled, revision: choice.revision + 1,
                    default: {runtime: model.runtime, model: model.id}};
        }
        return json(view());
      }
      if (p === '/api/v2/models') return json({models: MODELS, harnesses: [], enabled_providers: choice.enabled, default: choice.default});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana Rivera', email: 'ana@acme.example'}]});
      if (p === '/api/v2/operations') return json({machines: [], services: [], issues: [], scheduler_enabled: true});
      if (p === '/api/v2/settings/history') return json({changes: [], transitions: []});
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));

    // The first step is the provider choice, seven steps in all, and nothing is ticked for them.
    await page.goto('https://tico-ui.test/');
    await page.waitForFunction(() => location.hash === '#/welcome');
    await page.locator('[data-providers-form]').waitFor();
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 1 of 7');
    assert.match(await page.locator('#onb-step').textContent(), /Which AI providers do you use\?/);
    assert.equal(await page.locator('[data-provider]:checked').count(), 0);
    assert.equal(await page.locator('[data-provider-model] option').textContent(), 'Tick a provider first');

    // Ticking a provider fills the model list with that provider's current models only.
    await page.locator('#onb-next').click();
    assert.match(await page.locator('#onb-status').textContent(), /Tick at least one provider/);
    assert.equal(puts.length, 0);
    await page.locator('[data-provider][value=anthropic]').check();
    assert.deepEqual(await page.locator('[data-provider-model] option').evaluateAll(els => els.map(el => el.value)),
      ['claude-opus-5', 'claude-opus-5-5']);
    assert.equal(await page.locator('[data-provider-model]').inputValue(), 'claude-opus-5');
    await page.locator('[data-provider][value=openai]').check();
    const values = await page.locator('[data-provider-model] option').evaluateAll(els => els.map(el => el.value));
    assert.ok(values.includes('gpt-6-sol') && !values.includes('gpt-5.6-sol'), 'retired models are not offered');
    await page.locator('[data-provider-model]').selectOption('claude-opus-5-5');
    await page.locator('[data-provider][value=openai]').uncheck();
    assert.equal(await page.locator('[data-provider-model]').inputValue(), 'claude-opus-5-5');

    // Next saves the choice with the revision the page read, then the names step follows.
    await page.locator('#onb-next').click();
    await page.locator('#onb-company').waitFor();
    assert.deepEqual(puts, [{enabled: ['anthropic'], model: 'claude-opus-5-5', expected_revision: 0}]);
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 2 of 7');

    // Settings shows the saved choice and edits it with the new revision.
    await page.goto('https://tico-ui.test/#/settings');
    await page.getByRole('tab', {name: 'AI providers'}).click();
    await page.locator('#set-prov').waitFor();
    assert.deepEqual(await page.locator('#set-prov [data-provider]:checked').evaluateAll(els => els.map(el => el.value)), ['anthropic']);
    assert.equal(await page.locator('#set-prov [data-provider-model]').inputValue(), 'claude-opus-5-5');
    await page.locator('#set-prov [data-provider][value=xai]').check();
    await page.locator('#set-prov [data-provider-model]').selectOption('grok-4.6');
    await page.locator('#set-prov-save').click();
    await page.waitForFunction(() => document.querySelector('#set-prov [data-provider][value=xai]')?.checked);
    assert.deepEqual(puts[1], {enabled: ['anthropic', 'xai'], model: 'grok-4.6', expected_revision: 1});
    assert.equal(await page.locator('#set-prov [data-provider-model]').inputValue(), 'grok-4.6');
    assert.deepEqual(errors, []);
    console.log('PASS: providers are the first setup step, filter the default model, save with a revision and edit in Settings.');
  } finally {
    await browser.close();
  }
})();
