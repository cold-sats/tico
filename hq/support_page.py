"""The page a person with no app reads replies on: `GET /support/{ticket_id}#s=<secret>` (support.py).

The installer and `tico-setup doctor` print this link when they file a ticket. The secret is in the fragment, which a
browser never sends, so no request line, proxy or log holds it. The page is one constant document: nothing from the
request or the ticket is written into it on the server. Its script reads the ticket id from the path and the secret from
the fragment, asks the JSON routes with the X-Ticket-Secret header, and puts every value into the page as text, never
as markup. The Content-Security-Policy allows exactly this script and this style, by hash, and connections to HQ only.
"""
import base64
import hashlib

from fastapi.responses import HTMLResponse

STYLE = """
body{font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f6f4;color:#1d1d1b}
main{max-width:44rem;margin:0 auto;padding:2rem 1rem}
h1{font-size:1.4rem;margin:0 0 .25rem}
.meta{color:#5d5d58;margin:0 0 1.5rem}
.msg{background:#fff;border:1px solid #deded8;border-radius:8px;padding:.75rem 1rem;margin:0 0 .75rem}
.msg.staff{border-color:#9bb8e8}
.who{font-size:.85rem;color:#5d5d58;margin:0 0 .25rem}
.body{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
textarea{width:100%;box-sizing:border-box;min-height:7rem;font:inherit;padding:.5rem}
button{font:inherit;padding:.4rem .9rem;margin:.5rem .5rem 0 0}
#note{color:#8a1c1c;min-height:1.5rem}
@media (prefers-color-scheme:dark){body{background:#1b1b1a;color:#ececea}.msg{background:#262625;border-color:#3a3a38}
.msg.staff{border-color:#3d5a8a}.meta,.who{color:#a5a5a0}}
"""

SCRIPT = """
(function () {
  "use strict";
  var TICKET = /^TK-[A-Z2-7]{8}$/, SECRET = /^[A-Za-z0-9_-]{20,64}$/;
  var id = decodeURIComponent(location.pathname.split("/").pop() || "");
  var match = /(?:^#|&)s=([^&]*)/.exec(location.hash || "");
  var secret = match ? decodeURIComponent(match[1]) : "";
  var $ = function (name) { return document.getElementById(name); };
  function note(text) { $("note").textContent = text || ""; }
  function call(method, path, body) {
    var options = {method: method, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
                   headers: {"X-Ticket-Secret": secret, "Accept": "application/json"}};
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch("/v1/support/" + id + (path || ""), options);
  }
  function problem(status) {
    if (status === 404) { return "This link does not open a request: it is incomplete, or the request was deleted."; }
    if (status === 409) { return "This request is closed. Run the installer or tico-setup doctor again to start a new one."; }
    if (status === 429) { return "Too many requests from this address. Try again in an hour."; }
    return "Tico support did not answer (" + status + "). Try again in a few minutes.";
  }
  var STATUS = {open: "Open: Tico support has it.", answered: "Answered: Tico support replied.", closed: "Closed."};
  function show(ticket) {
    $("title").textContent = "Tico support request " + ticket.ticket_id;
    $("meta").textContent = (STATUS[ticket.status] || String(ticket.status)) + " Opened " + ticket.created + ".";
    var list = $("thread");
    while (list.firstChild) { list.removeChild(list.firstChild); }
    var messages = Array.isArray(ticket.messages) ? ticket.messages : [];
    if (!messages.length) {
      var empty = document.createElement("p");
      empty.className = "meta";
      empty.textContent = "No reply yet. This page checks again every minute.";
      list.appendChild(empty);
    }
    messages.forEach(function (m) {
      var item = document.createElement("article");
      item.className = "msg" + (m.from === "staff" ? " staff" : "");
      var who = document.createElement("p");
      who.className = "who";
      who.textContent = (m.from === "staff" ? "Tico support" : "You") + ", " + m.created;
      var body = document.createElement("p");
      body.className = "body";
      body.textContent = String(m.body == null ? "" : m.body);
      item.appendChild(who);
      item.appendChild(body);
      list.appendChild(item);
    });
    $("write").hidden = ticket.status === "closed";
  }
  function load() {
    return call("GET").then(function (r) {
      if (!r.ok) { note(problem(r.status)); return; }
      return r.json().then(function (ticket) { note(""); show(ticket); });
    }, function () { note("Could not reach Tico support. Check the connection and try again."); });
  }
  if (!TICKET.test(id) || !SECRET.test(secret)) {
    note("This link is incomplete: copy the whole link the installer printed, including the part after #.");
    return;
  }
  $("app").hidden = false;
  $("send").addEventListener("click", function () {
    var text = $("message").value.trim();
    if (!text) { return; }
    $("send").disabled = true;
    call("POST", "/messages", {message: text}).then(function (r) {
      if (r.status === 201) { $("message").value = ""; return load(); }
      note(problem(r.status));
    }, function () { note("Could not send it. Try again."); }).then(function () { $("send").disabled = false; });
  });
  $("refresh").addEventListener("click", load);
  $("delete").addEventListener("click", function () {
    if (!window.confirm("Delete this request and every message in it? Tico support can no longer read it.")) { return; }
    call("DELETE").then(function (r) {
      if (!r.ok) { note(problem(r.status)); return; }
      $("app").hidden = true;
      note("Deleted.");
    }, function () { note("Could not delete it. Try again."); });
  });
  load();
  setInterval(function () { if (!document.hidden) { load(); } }, 60000);
})();
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Tico support request</title>
<style>%s</style>
</head>
<body>
<main>
<h1 id="title">Tico support request</h1>
<p class="meta" id="meta"></p>
<p id="note" role="status"></p>
<div id="app" hidden>
<section id="thread" aria-live="polite"></section>
<div id="write">
<label for="message">Add a message</label>
<textarea id="message" maxlength="4000"></textarea>
<button type="button" id="send">Send</button>
</div>
<button type="button" id="refresh">Check for replies</button>
<button type="button" id="delete">Delete this request</button>
</div>
<noscript><p>This page needs JavaScript to read the reply.</p></noscript>
</main>
<script>%s</script>
</body>
</html>
""" % (STYLE, SCRIPT)


def _hash(text):
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


CSP = ("default-src 'none'; script-src %s; style-src %s; connect-src 'self'; img-src 'none'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'" % (_hash(SCRIPT), _hash(STYLE)))
HEADERS = {"Content-Security-Policy": CSP, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "Cross-Origin-Opener-Policy": "same-origin"}


def page():
    """The page, the same bytes for every ticket."""
    return HTMLResponse(PAGE, headers=HEADERS)
