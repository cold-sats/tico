/* ui/app/core.js — State-free basics: route constants, $, esc, md, s3url
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

const API = '/api';
const GH = 'https://github.com/ticoteam/tico';
// The Overview page is gone. Old links and the native Mac shell still say
// Old routes redirect to Meetings.
const OVERVIEW = '#/overview';
const WELCOME = '#/welcome';          // first run: names, the company, the bot catalog, a computer
const CHAT = '#/chat';                // retired with the Tico chat: old links land on Tasks
const NOTES = '#/notes';               // legacy route
const RECORDINGS = '#/recordings';    // legacy route
const MEETINGS = '#/meetings';        // imported meeting transcripts: the list, Import, and each meeting
const UPDATES = '#/updates';          // the bots' daily and weekly updates, a feed (backend/updates.py)
const TASKS = '#/tasks';              // hub tasks and Issues in one page (List | Board)
const GOALS = '#/goals';              // the org chart with everyone's goals and a colour
const BOARD = '#/board';              // the old links still work, each opening its view
const ISSUES = '#/issues';
const RECURRING = '#/recurring';      // the Tasks page, opened on the Recurring view
const SETTINGS = '#/settings';
const HELP = '#/help';                // a short mental model for people joining the company
const CREDENTIALS = '#/credentials';   // the owner's connections: what is connected and whether it works
const SQL_PAGE = '#/sql';              // the owner's and admins' read-only query page over the hub database
const DOCS = '#/docs';              // company-wide documentation, separate from bot Docs tabs
const INTEGRATIONS = '#/integrations'; // integrations/*.md: how a bot uses each outside system, its queries, shared learnings
const MAIL = '#/mail';                // server-stored mail copies; #/inbox redirects here
const MESSAGING = '#/messaging';       // selected Message bot: setup, schedules, and example messages
// Bot notices still flow through /api/v2/inbox. People read mail on #/mail, not live Gmail.
const $ = (s, r=document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Bot text (final replies, status notes, playbooks) is untrusted: every render goes through safeMd.
const md = s => safeMd(s);
// bucket objects are only reachable through the presign redirect; markdown may name them as s3:// URIs
const s3url = key => `${API}/s3?key=${encodeURIComponent(String(key || '').replace(/^s3:\/\/[^/]+\//, ''))}`;
const mdS3 = md;   // safeMd already routes s3:// images through the hub
async function copyText(value) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  const area = document.createElement('textarea'); area.value = value; area.style.position = 'fixed'; area.style.opacity = '0';
  document.body.appendChild(area); area.select(); document.execCommand('copy'); area.remove();
}
