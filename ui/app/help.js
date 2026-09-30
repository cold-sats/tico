/* ui/app/help.js — Help page
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// The shared hub contract in clients/hubtools.py. Keep this compact index in lockstep with it;
// ui/tests/help-page.cjs checks the rendered totals and the backend checks CLI ↔ MCP parity.
const HELP_TOOL_GROUPS = [
  ["Context & meetings", ["context search", "context show", "meetings search", "meetings transcript", "meetings import"]],
  ["Calendar", ["calendar upcoming", "calendar status", "calendar schedule"]],
  ["Identity & messages", ["whoami", "say", "ask", "answer", "notice"]],
  ["Tasks", ["task create", "task ask", "task update", "task comment", "task link", "task label", "task close", "task attach", "task list", "task show"]],
  ["Goals & measures", ["goals", "goal show", "goal create", "goal status", "goal auto", "goal refresh", "goal checkin", "goal checkins", "goal needs-you", "goal update", "kpi list", "kpi show", "kpi add", "kpi update", "kpi link", "kpi unlink", "kpi log", "kpi readings", "proposal create", "proposal list", "proposal decide"]],
  ["Market", ["market show", "market find", "market edges", "market delta", "market ask", "market report", "market resolve", "market apply", "market sweep", "market refresh"]],
  ["Listening", ["listen save", "listen decide", "listen show", "listen runs", "listen stats", "intake list", "intake resolve"]],
  ["History & routines", ["history", "routine list", "routine set", "routine update", "routine delete"]],
  ["Approvals & Needs you", ["approval request", "approval show", "batch start", "batch next", "batch respond", "batch commit", "batch abandon"]],
  ["Status & coordination", ["status set", "status list", "status history", "turns", "inbox", "ack", "board", "org", "fleet", "bot onboarded"]],
  ["Data & tools", ["sql", "integrations", "integration", "queries", "learn", "decisions"]],
  ["Templates & local setup", ["catalog"], ["bot create", "bot check"]]
];
const helpMcpName = command => 'hub_' + command.replaceAll(' ', '_');
function helpToolGroupHTML([title, shared, local = []]) {
  const row = (command, cliOnly = false) => `<li class="help-tool-row" data-transport="${cliOnly ? 'cli' : 'shared'}">
    <code>hub ${esc(command)}</code>${cliOnly
      ? '<span><span aria-hidden="true">—</span><span class="help-cli-only">CLI only</span></span>'
      : `<code>${esc(helpMcpName(command))}</code>`}</li>`;
  return `<section class="help-tool-group"><h3>${esc(title)}</h3>
    <div class="help-tool-head"><span>CLI</span><span>MCP</span></div>
    <ul class="help-tool-list">${shared.map(command => row(command)).join('')}${local.map(command => row(command, true)).join('')}</ul>
  </section>`;
}

function pageHelp() {
  $('#main').innerHTML = `<article class="help-page" id="help-page">
    <header class="help-hero">
      <div class="help-eyebrow">How Tico works</div>
      <h1>The coordination layer for your humans and bots.</h1>
      <p class="help-lede">One place to find bots, talk to them, hand off work and see what happened.</p>
      <div class="help-actions"><button class="primary" type="button" data-gs-tour>Take the tour</button><a class="gs-link" href="#/settings" data-gs-tab="health">Settings &gt; Health</a><a class="gs-link" href="${GH}/blob/main/docs/glossary.md" target="_blank" rel="noopener noreferrer">Glossary</a></div>
    </header>

    <section class="help-flow" aria-label="How humans, Tico, and bots work together">
      <div class="help-flow-node"><span>Humans</span><strong>Set direction and decide</strong></div>
      <div class="help-flow-arrow" aria-hidden="true">→</div>
      <div class="help-flow-node tico"><span>Tico</span><strong>Coordinates the team</strong></div>
      <div class="help-flow-arrow" aria-hidden="true">→</div>
      <div class="help-flow-node"><span>Bots</span><strong>Do the work</strong></div>
    </section>

    <section class="help-steps" aria-label="Tico's four building blocks">
      <div class="help-step"><h2>Know the team</h2><p>The registry lists each bot, who can use it and where it runs.</p></div>
      <div class="help-step"><h2>Talk and delegate</h2><p>Chat with a bot; turn a request into a task with an owner.</p></div>
      <div class="help-step"><h2>Version every bot</h2><p>Each bot's instructions and memory live in its own Git repository.</p></div>
      <div class="help-step"><h2>Share context</h2><p>Bots and external agents reach goals, docs, meetings and tasks through MCP or the CLI.</p></div>
    </section>
    <details class="help-tools">
      <summary><strong>MCP + CLI function index</strong><small>${HELP_TOOL_GROUPS.reduce((n, [, shared]) => n + shared.length, 0)} shared functions · ${HELP_TOOL_GROUPS.reduce((n, [, , local = []]) => n + local.length, 0)} local CLI functions</small></summary>
      <div class="help-tools-body">
        <p class="help-tools-intro">MCP at <code>/api/v2/mcp</code> or the <code>hub</code> CLI: <code>hub task create</code> is <code>hub_task_create</code>. Bot setup commands are CLI-only.</p>
        <div class="help-tool-groups">${HELP_TOOL_GROUPS.map(helpToolGroupHTML).join('')}</div>
      </div>
    </details>
    <p class="help-foot">${S.config.version ? `<span id="help-version">Version ${esc(nvVersion(S.config.version))}</span>` : ''}</p>
  </article>`;
  window.supportHelp?.($('#help-page'));    // Contact support and Your requests (ui/support.js)
}
