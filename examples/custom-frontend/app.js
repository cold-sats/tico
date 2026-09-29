// A small frontend for Tico with no build step and no dependencies. Read it top to bottom:
// 1. api()      every call to Tico, with the bearer session and the Idempotency-Key writes need
// 2. sign-in    OIDC through Tico, with PKCE, ending in a bearer session (docs/custom-frontend.md)
// 3. views      org chart, chat with live replies, tasks, Needs you
// Everything from the server is put on the page as text, never as HTML: a bot's reply is untrusted.
"use strict";

const TICO = String(window.TICO_URL || "").replace(/\/+$/, "");
const KEY = "tico.session";                    // sessionStorage: gone when the tab closes (see the docs' trade-offs)
const $ = (id) => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };

// ---------------------------------------------------------------- 1. calls

class Problem extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.detail || (body && JSON.stringify(body.detail)) || "HTTP " + status);
    this.status = status; this.code = e.code || ""; this.retryable = !!e.retryable;
  }
}

const session = {
  get token() { try { return sessionStorage.getItem(KEY) || ""; } catch { return ""; } },
  set token(v) { try { v ? sessionStorage.setItem(KEY, v) : sessionStorage.removeItem(KEY); } catch { /* private mode */ } },
};

async function api(path, { method = "GET", body, signal } = {}) {
  const headers = { Authorization: "Bearer " + session.token };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["Idempotency-Key"] = crypto.randomUUID();   // a retry with the same key is safe
  const res = await fetch(TICO + path, { method, headers, signal, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (res.status === 401) { session.token = ""; showSignIn(); }
  if (!res.ok) throw new Problem(res.status, data);
  return data;
}

function fail(err) {
  if (err && err.name === "AbortError") return;
  const box = $("error");
  box.textContent = err instanceof Problem ? err.message : "Could not reach " + TICO + " (is this page's origin in TICO_CORS_ORIGINS?)";
  box.hidden = false;
}

// ---------------------------------------------------------------- 2. sign-in

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function signIn() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(48)));            // 64 characters
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  sessionStorage.setItem("tico.verifier", verifier);
  // Tico signs the person in, then sends the browser back to `next` with a one-time code in the #fragment.
  const back = location.origin + location.pathname;
  location.assign(TICO + "/auth/login?" + new URLSearchParams({ next: back, code_challenge: challenge }));
}

async function finishSignIn() {
  const code = new URLSearchParams(location.hash.slice(1)).get("tico_code");
  if (!code) return;
  history.replaceState(null, "", location.pathname + location.search);            // the code is single-use; do not leave it in the URL
  const verifier = sessionStorage.getItem("tico.verifier") || "";
  sessionStorage.removeItem("tico.verifier");
  const res = await fetch(TICO + "/auth/token", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, code_verifier: verifier }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Problem(res.status, data);
  session.token = data.access_token;
}

async function signOut() {
  try { await api("/auth/token/revoke", { method: "POST" }); } catch { /* already gone */ }
  session.token = "";
  showSignIn();
}

function showSignIn() {
  for (const id of ["org", "chat", "tasks", "needs", "tabs", "sign-out"]) $(id).hidden = true;
  $("who").textContent = "";
  $("signin").hidden = false;
  stopWatching();
}

// ---------------------------------------------------------------- 3. views

const tabs = {
  org: loadOrg,
  chat: loadChatBots,
  tasks: loadTasks,
  needs: loadNeeds,
};

function open(tab) {
  $("error").hidden = true;
  for (const id of Object.keys(tabs)) $(id).hidden = id !== tab;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === tab);
  if (tab !== "chat") stopWatching();
  tabs[tab]().catch(fail);
}

// Org chart: /api/v2/org returns people and bots, each with org_parent ("p:<person>", "b:<bot>", "g:<group>" or "").
async function loadOrg() {
  const org = await api("/api/v2/org");
  const nodes = [
    ...org.people.map((p) => ({ key: "p:" + p.id, parent: p.org_parent, label: p.name, sub: p.title, kind: "person" })),
    ...org.bots.map((b) => ({ key: "b:" + b.id, parent: b.org_parent, label: b.display_name, sub: b.description, kind: "bot", status: b.status })),
    ...(org.org_groups || []).map((g) => ({ key: "g:" + g.id, parent: g.org_parent, label: g.name, sub: "", kind: "group" })),
  ];
  const known = new Set(nodes.map((n) => n.key));
  const children = new Map();
  for (const n of nodes) {
    const parent = known.has(n.parent) ? n.parent : "";
    children.set(parent, [...(children.get(parent) || []), n]);
  }
  const build = (parent) => {
    const list = el("ul", null, parent ? "" : "tree");
    for (const n of children.get(parent) || []) {
      const li = el("li", n.label);
      li.append(el("span", n.kind === "bot" ? "bot" + (n.status ? " " + n.status : "") : n.kind, "badge"));
      if (n.sub) li.append(el("small", " " + n.sub));
      if (children.has(n.key)) li.append(build(n.key));
      list.append(li);
    }
    return list;
  };
  $("org").replaceChildren(el("h1", "Org chart"), build(""));
}

// Chat: the bot's personal chat room. Send with POST /api/v2/chat/{bot}; watch it with a stream.
let chat = { bot: "", cid: "", messages: [], live: "", abort: null };

async function loadChatBots() {
  const bots = await api("/api/v2/bots");
  const list = $("chat-bots");
  list.replaceChildren(...bots.map((b) => {
    const li = el("li"), btn = el("button", b.display_name || b.slug);
    btn.addEventListener("click", () => openChat(b).catch(fail));
    li.append(btn);
    return li;
  }));
}

async function openChat(bot) {
  stopWatching();
  chat = { bot: bot.slug, cid: "", messages: [], live: "", abort: null };
  $("chat-title").textContent = "Chat with " + (bot.display_name || bot.slug);
  $("send").hidden = false;
  const mine = await api("/api/v2/conversations?chat_with=" + encodeURIComponent(bot.slug));
  const room = mine.conversations[0];
  if (room) {
    chat.cid = room.id;
    chat.messages = (await api("/api/v2/conversations/" + encodeURIComponent(room.id) + "/messages")).messages;
    watch();
  }
  renderChat();
}

function renderChat() {
  const box = $("messages");
  const nodes = chat.messages.map((m) => el("div", m.body, "msg" + (m.from_actor.startsWith("bot:") ? "" : " me")));
  if (chat.live) nodes.push(el("div", chat.live, "msg live"));
  box.replaceChildren(...nodes);
  box.scrollTop = box.scrollHeight;
}

async function sendMessage(text) {
  const sent = await api("/api/v2/chat/" + encodeURIComponent(chat.bot), { method: "POST", body: { text } });
  chat.messages.push(sent.message);
  renderChat();
  if (!chat.cid) { chat.cid = sent.conversation.id; watch(); }
}

// Live replies: GET /api/v2/conversations/{cid}/watch is Server-Sent Events. The browser's EventSource
// cannot send an Authorization header, so read the stream with fetch. Each `snapshot` holds the newest
// messages and `execution.text`, the reply so far. A stream ends after about a minute; reconnecting
// sends a fresh snapshot, so nothing is lost and there is no cursor to keep.
function stopWatching() { if (chat.abort) chat.abort.abort(); chat.abort = null; }

function watch() {
  stopWatching();
  const mine = chat, abort = (chat.abort = new AbortController());
  (async () => {
    let delay = 500;
    while (!abort.signal.aborted && chat === mine) {
      try {
        const res = await fetch(TICO + "/api/v2/conversations/" + encodeURIComponent(mine.cid) + "/watch", {
          headers: { Authorization: "Bearer " + session.token, Accept: "text/event-stream" }, signal: abort.signal,
        });
        if (res.status === 401) { session.token = ""; return showSignIn(); }
        if (!res.ok) throw new Error("HTTP " + res.status);
        delay = 500;
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value.replace(/\r\n/g, "\n");
          let end;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const block = buffer.slice(0, end); buffer = buffer.slice(end + 2);
            onEvent(mine, block);
          }
        }
      } catch (err) {
        if (abort.signal.aborted) return;
        delay = Math.min(delay * 2, 15000);                                     // back off while the network is down
      }
      await new Promise((r) => setTimeout(r, delay));
    }
  })();
}

function onEvent(mine, block) {
  if (chat !== mine) return;
  const name = (/^event: (.*)$/m.exec(block) || [])[1];
  const data = (/^data: (.*)$/m.exec(block) || [])[1];
  if (name === "expired") { session.token = ""; return showSignIn(); }
  if (name !== "snapshot" || !data) return;                                     // ": keepalive" comments carry no data
  const snap = JSON.parse(data);
  chat.messages = snap.messages;
  const run = snap.execution;
  chat.live = run && ["leased", "running"].includes(run.state) ? run.text || run.label || "" : "";
  renderChat();
}

async function loadTasks() {
  const { tasks } = await api("/api/v2/tasks?status=open,doing,waiting,review,ready&limit=100");
  const table = el("table");
  table.append(row(["Task", "Owner", "Status"], "th"));
  for (const t of tasks) table.append(row([t.title, t.owner_name || t.owner, t.status]));
  $("tasks").replaceChildren(el("h1", "Tasks"), tasks.length ? table : el("p", "Nothing open."));
}

async function loadNeeds() {
  const { items } = await api("/api/v2/needs-you");
  const list = el("ul");
  for (const i of items) list.append(el("li", i.kind + ": " + i.title + (i.first_line && i.first_line !== i.title ? " - " + i.first_line : "")));
  $("needs").replaceChildren(el("h1", "Needs you"), items.length ? list : el("p", "Nothing is waiting on you."));
}

function row(cells, tag = "td") {
  const tr = el("tr");
  for (const c of cells) tr.append(el(tag, c));
  return tr;
}

// ---------------------------------------------------------------- start

async function start() {
  if (!TICO) return fail(new Error("Set TICO_URL in config.js"));
  $("sign-in").addEventListener("click", () => signIn().catch(fail));
  $("sign-out").addEventListener("click", signOut);
  $("send").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("text").value.trim();
    if (!text) return;
    $("text").value = "";
    sendMessage(text).catch(fail);
  });
  for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => open(b.dataset.tab));
  // A Tico on this computer with no sign-in provider (TICO_AUTH_PROXY=none) takes the owner token instead.
  if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(TICO)) {
    $("dev").hidden = false;
    $("dev-go").addEventListener("click", () => { session.token = $("dev-token").value.trim(); $("dev-token").value = ""; begin(); });
  }
  try { await finishSignIn(); } catch (err) { fail(err); }
  begin();
}

async function begin() {
  if (!session.token) return showSignIn();
  try {
    const [me, config] = await Promise.all([api("/api/v2/me"), api("/api/v2/config")]);
    $("company").textContent = config.app_name || config.company_name;
    $("who").textContent = me.email || me.actor;
    $("signin").hidden = true;
    $("tabs").hidden = false;
    $("sign-out").hidden = false;
    open("org");
  } catch (err) { if (!(err instanceof Problem && err.status === 401)) fail(err); }
}

start();
