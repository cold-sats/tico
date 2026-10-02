/* ui/app/refresh.js — The refresh loop
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- refresh loop + router
async function refresh(force) {
  try {
    const [st, issues, emps, people] = await Promise.all([get('/status'), get('/issues'), S.emps.length && !force && !S.emps.some(frNeedsSetup) ? S.emps : get('/employees'), S.people.length && !force ? {people: S.people} : get('/humans').catch(() => ({people: S.people || []}))]);
    S.status = st;
    S.issues = issues.map(i => {
      if (!pendingClosedIssues.has(i.number)) return i;
      if (i.state === 'CLOSED') pendingClosedIssues.delete(i.number);
      return {...i, state: 'CLOSED', needs_human: false};
    });
    S.emps = namedRoster(emps);
    if (people?.people) setPeople(people);
  } catch (e) { S.status = null; }
  await v2Refresh();                    // hub.db status and needs-you (docs/history/hub-v2.md)
  if (S.me?.cloud) void updUnreadRefresh();
  renderTree(); renderHeartbeat(); pausedRender(); botAvatarsSync();
  if (BOT?.tab === 'chat' && !BOT.split) void loadBotChatTasks(BOT.slug);
  if (BOT && $('#bot-alert')) $('#bot-alert').innerHTML = botAlertHTML(BOT.slug);   // an alert comes and goes with the poll
  if (BOT && $('#bot-onboard-host') && ($('#bot-onboard') ? '1' : '') !== (frNeedsSetup(S.emps.find(x => x.name === BOT.slug)) ? '1' : '')) frBotRefresh(BOT.slug);   // the mark clears when the bot says it is set up
  if (BOT && $('#bot-ticker') && isKeeper(BOT.slug)) void botTickerLoad(BOT.slug);
  // Poll data without destroying an expanded document or a comment being typed.
  const reviewing = $('#main .req[open], #main .issue-compose:not([hidden])');
  if (force || !reviewing) {
    if (TASKS_ST && isTasksRoute(S.route)) void tasksLoad(TASKS_ST);   // the list itself reloads; only changed rows redraw
    // The Active column beside the chat was loaded once and never again, so a task the bot closed
    // stayed listed until a reload. The poll redraws it too.
    if (BOT && isKeeper(BOT.slug) && BOT.loaded.has('tasks')) void loadBotTasksV2(BOT.slug);
  }
}
