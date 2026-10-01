/* ui/app/chat-goal.js — A chat's pinned goal: the target button in the composer, the bar above the thread, and
   the one line a met or stopped goal leaves in the chat. The harness (Codex, Claude Code) keeps working toward it.
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// GET/POST /api/v2/conversations/{id}/goal. Old servers answer 404, which reads as "not supported".
const goalPath = conv => `/v2/conversations/${encodeURIComponent(conv)}/goal`;
const GOAL_CHIPS = {active: ['Working', 'in-progress'], paused: ['Paused', 'waiting'], met: ['Met', 'ok'], stopped: ['Stopped', 'fail']};
const GOAL_MAX = 4000;
// A goal that is still pinned to the chat: working toward it, or paused.
const goalPinned = g => !!g && (g.status === 'active' || g.status === 'paused');
const goalEnded = g => !!g && (g.status === 'met' || g.status === 'stopped');

async function chatGoalLoad(state) {
  if (!state?.conv) return;
  let d = null;
  try { d = await get(goalPath(state.conv.id)); } catch { d = null; }
  if (V2C !== state) return;
  state.goalSupported = !!d?.supported;
  state.commands = Array.isArray(d?.commands) ? d.commands : null;
  chatGoalApply(state, d?.goal || null, {quiet: true});
}
// A goal from the API or the live stream: kept on the chat, drawn in the bar and the thread, and mirrored on the
// bot's row in the sidebar.
function chatGoalApply(state, goal, {quiet = false} = {}) {
  if (!state || V2C !== state) return;
  const was = state.goal;
  if (goal && was && goal.id === was.id && goal.updated_at && was.updated_at && goal.updated_at < was.updated_at) return;   // a stale event
  state.goal = goal && goal.status !== 'cleared' ? goal : null;
  if (!goalPinned(state.goal)) state.goalOpen = false;
  // The row's mark covers every chat the viewer can read, so a quiet load only ever adds it; a change made or
  // streamed here sets it either way.
  const bot = (S.emps || []).find(e => e.name === state.slug), active = state.goal?.status === 'active';
  if (bot && !!bot.goal_active !== active && (active || !quiet)) { bot.goal_active = active; renderTree(); }
  chatGoalRender(state);
  if (!quiet || goalEnded(state.goal) !== goalEnded(was)) v2ChatRender(state);
}
async function chatGoalAct(action, objective) {
  const state = V2C;
  if (!state?.conv) return false;
  const body = {action};
  if (objective != null) body.objective = objective;
  try {
    const r = await post(goalPath(state.conv.id), body);
    chatGoalApply(state, r.goal || null);
    return true;
  } catch (e) {
    if (e.status === 409 && (e.body?.error?.code === 'goal_unsupported' || e.body?.error === 'goal_unsupported' || /goal_unsupported/.test(e.message))) {
      state.goalSupported = false; chatGoalRender(state);
      toast("This bot's harness doesn't support goals.", true);
    } else toast(e.message, true);
    return false;
  }
}
// Set a new goal, or change the text of the one that is pinned.
const chatGoalSave = text => chatGoalAct(goalPinned(V2C?.goal) ? 'edit' : 'set', text);
function chatGoalEdit(open = true) {
  const state = V2C; if (!state) return;
  state.goalEditing = open;
  if (open) state.goalOpen = false;
  chatGoalRender(state, true);
  if (open) { const box = $('#chat-goal textarea'); box?.focus(); box?.setSelectionRange(box.value.length, box.value.length); }
}

function chatGoalBarHTML(g) {
  const [chip, tone] = GOAL_CHIPS[g.status] || ['', ''];
  return `<div class="cg-bar" role="button" tabindex="0" aria-expanded="false" aria-label="Goal">
      <span class="nav-icon cg-icon" aria-hidden="true">target</span>
      <div class="cg-text">${esc(g.objective || '')}</div>
      ${chip ? `<span class="pill ${tone} cg-chip">${chip}</span>` : ''}</div>
    <div class="cg-actions" hidden>
      <button class="ghost" type="button" data-goal="edit">Edit</button>
      <button class="ghost" type="button" data-goal="${g.status === 'paused' ? 'resume' : 'pause'}">${g.status === 'paused' ? 'Resume' : 'Pause'}</button>
      <button class="ghost" type="button" data-goal="clear">Clear</button>
    </div>`;
}
const chatGoalFormHTML = text => `<form class="cg-edit">
    <span class="nav-icon cg-icon" aria-hidden="true">target</span>
    <textarea rows="2" maxlength="${GOAL_MAX}" aria-label="Goal" placeholder="What should it get done?">${esc(text || '')}</textarea>
    <div class="cg-edit-go"><button class="ghost" type="button" data-goal="cancel">Cancel</button><button class="primary" type="submit">Save</button></div>
  </form>`;

// The bar sits above the thread and never scrolls with it. `force` redraws a form that is being typed in.
function chatGoalRender(state, force = false) {
  if (!state || V2C !== state) return;
  const host = $('#chat-goal');
  if (host) {
    const g = state.goal, editing = state.goalEditing && state.goalSupported;
    if (editing) {
      if (force || !host.querySelector('.cg-edit')) {
        host.innerHTML = chatGoalFormHTML(goalPinned(g) ? g.objective : '');
        chatGoalWireForm(host);
      }
    } else if (goalPinned(g)) {
      const key = `${g.id}|${g.status}|${g.updated_at}|${g.objective}`;
      if (force || host.dataset.key !== key || !host.querySelector('.cg-bar')) {
        host.innerHTML = chatGoalBarHTML(g); host.dataset.key = key;
        chatGoalWireBar(state, host);
      }
    } else { host.innerHTML = ''; host.dataset.key = ''; }
    host.hidden = !host.innerHTML;
    host.classList.toggle('open', !!state.goalOpen && !editing);
    host.querySelector('.cg-bar')?.setAttribute('aria-expanded', String(!!state.goalOpen));
    const actions = host.querySelector('.cg-actions'); if (actions) actions.hidden = !state.goalOpen;
  }
  const P = BOT_PILL?.slug === state.slug ? BOT_PILL : null, btn = P && pq(P, '.p-goal');
  if (btn) {
    btn.hidden = !state.goalSupported;
    btn.classList.toggle('on', goalPinned(state.goal));
    btn.setAttribute('aria-pressed', String(goalPinned(state.goal)));
  }
}
function chatGoalWireBar(state, host) {
  const bar = host.querySelector('.cg-bar');
  const toggle = () => { state.goalOpen = !state.goalOpen; chatGoalRender(state); };
  bar.onclick = toggle;
  bar.onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } };
  host.querySelectorAll('[data-goal]').forEach(b => b.onclick = async () => {
    const act = b.dataset.goal;
    if (act === 'edit') return chatGoalEdit(true);
    b.disabled = true;
    await chatGoalAct(act);
    b.disabled = false;
  });
}
function chatGoalWireForm(host) {
  const form = host.querySelector('form'), box = form.querySelector('textarea');
  // The box fits the goal being edited, up to its CSS cap.
  const fit = () => { box.style.height = 'auto'; box.style.height = box.scrollHeight + 2 + 'px'; };
  box.addEventListener('input', fit); fit();
  const save = async () => {
    const text = box.value.trim();
    if (!text) { box.focus(); return; }
    form.querySelector('[type=submit]').disabled = true;
    if (await chatGoalSave(text)) chatGoalEdit(false);
    else form.querySelector('[type=submit]').disabled = false;
  };
  form.onsubmit = ev => { ev.preventDefault(); void save(); };
  // Return saves and Shift+Return is a new line, as in the composer; Esc puts it away.
  box.onkeydown = ev => {
    if (ev.key === 'Escape') { ev.preventDefault(); chatGoalEdit(false); }
    else if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing && !touchKeyboard()) { ev.preventDefault(); void save(); }
  };
  form.querySelector('[data-goal="cancel"]').onclick = () => chatGoalEdit(false);
}
// The composer's target: no goal opens the form; a pinned goal opens the bar.
function chatGoalButton() {
  const state = V2C; if (!state) return;
  if (state.goalEditing) return chatGoalEdit(false);
  if (!goalPinned(state.goal)) return chatGoalEdit(true);
  state.goalOpen = !state.goalOpen; chatGoalRender(state);
  $('#chat-goal')?.scrollIntoView({block: 'nearest'});
}
// A met or stopped goal leaves one line in the thread, where it ended; nothing else announces it. A line the server
// already wrote for it (refs.goal_id) stands instead.
function chatGoalLine(state, messages) {
  const g = state.goal;
  if (!goalEnded(g)) return null;
  if (messages.some(m => m.refs?.goal_id === g.id || m.refs?.goal?.id === g.id)) return null;
  const end = String(g.ended_at || g.updated_at || '');
  const at = end ? messages.filter(m => String(m.created || '') <= end).length : messages.length;
  const what = `${g.status === 'met' ? 'Goal met' : 'Goal stopped'}`;
  const full = [g.objective, g.note].filter(Boolean).join(' · ');
  return {at, html: `<div class="chat-system chat-goal-line" title="${esc(full)}"><span class="nav-icon cg-icon" aria-hidden="true">target</span>
    <b>${what}:</b> <span class="cg-line-text">${esc(g.objective || '')}</span>${g.note ? `<span class="cg-line-note">· ${esc(g.note)}</span>` : ''}</div>`};
}
