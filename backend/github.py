"""GitHub moves a product-lane task through the pull request linked to it.

A task carries its pull request as a link (`hub task link`). The repository's webhook posts here
signed with `TICO_GITHUB_WEBHOOK_SECRET`; nothing else on this path is trusted:

- a pull request opened for review  -> the link is `open`,   the task is `review`
- the pull request merged           -> the link is `merged`, the task is `ready`
- the pull request closed unmerged  -> the link is `closed`, the task is back to `doing`, owner told
- a push to main                    -> the commits are recorded, in order, in `main_pushes`

The last hop is a fact of the deploy, not of GitHub: the release manifest names the commit the
running code was built from (`release.py` writes it from CI), and `ship_deployed` marks `ready`
tasks `done` once their merge commit is at or before that commit on main. Only the repository
this release came from ships that way; a merged link in another repository stays `ready`.
"""
import hashlib
import hmac
import json
import re

from fastapi import Request, Response

from . import hubdb as H
from .batch_work import isolated
from .store import Problem

PATH = "/api/v2/github/webhook"   # under /api/v2: the runner hostname routes only that prefix
PR_LINK = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)/?$")


def verify(secret, headers, body):
    """The `X-Hub-Signature-256` GitHub sends, checked in constant time. False when unset."""
    if not secret:
        return False
    given = str(headers.get("x-hub-signature-256") or "")
    want = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given, want)


def _links_for(c, url):
    return H._rows(c.execute("SELECT * FROM task_links WHERE kind='pr' AND url=?", (url,)))


def _move(c, task, status, note):
    """The keeper moves the task; a mover's rights, a version bump like the API's."""
    if task["status"] == status or task["status"] in ("done", "closed"):
        return task
    H.task_update(c, H.KEEPER, task["id"], status=status, note=note, mover=True)
    c.execute("UPDATE tasks SET version=version+1 WHERE id=?", (task["id"],))
    return H.task(c, task["id"])


def flush_wakes(c):
    """Send each due PR burst independently; keep a failed or blocked notice for retry."""
    from .repositories import metadata
    sent = []
    for row in c.execute("SELECT key FROM registry_metadata WHERE key LIKE 'github-task-wake:%'").fetchall():
        with isolated(c, "github_wake", row["key"]):
            burst = metadata(c, row["key"])
            if burst.get("due", "") > H.now():
                continue
            task = H.task(c, row["key"].split(":", 1)[1])
            if task and task["status"] in (*H.ACTIVE_STATUSES, "blocked"):
                H._wake(c, task, task["owner"], "\n".join(burst.get("items", [])))
            c.execute("DELETE FROM registry_metadata WHERE key=?", (row["key"],))
            if task and task["status"] in (*H.ACTIVE_STATUSES, "blocked"):
                sent.append(task["id"])
    return sent


def pull_request(c, payload):
    """One `pull_request` event; returns what was done, for the log."""
    pr = payload.get("pull_request") or {}
    url = str(pr.get("html_url") or "").split("?")[0].rstrip("/")
    action = str(payload.get("action") or "")
    links = _links_for(c, url)
    if not links:
        return {"pr": url, "action": action, "tasks": 0}
    moved = []
    for link in links:
        task = H.task(c, link["task_id"])
        if not task:
            continue
        # Custom types opt into PR moves now that new tasks use the company lane.
        product = (task.get("lane") or "company") == "product" or task.get("type_id") not in (None, H.GENERAL_TYPE)
        active = task["status"] in H.ACTIVE_STATUSES
        if action in ("opened", "reopened", "ready_for_review") and not pr.get("draft"):
            c.execute("UPDATE task_links SET state='open' WHERE id=?", (link["id"],))
            if product and active and task["status"] in ("open", "doing", "waiting"):
                _move(c, task, "review", f"Pull request {link['title']} is open for review.")
                moved.append((task["id"], "review"))
        elif action == "converted_to_draft":
            c.execute("UPDATE task_links SET state='draft' WHERE id=?", (link["id"],))
        elif action == "closed" and pr.get("merged"):
            sha = str(pr.get("merge_commit_sha") or "")
            c.execute("UPDATE task_links SET state='merged', pr_sha=?, pr_merged_at=? WHERE id=?",
                      (sha, str(pr.get("merged_at") or H.now()), link["id"]))
            if product and active:
                _move(c, task, "ready", f"Pull request {link['title']} merged; waiting for the deploy.")
                moved.append((task["id"], "ready"))
        elif action == "closed":
            c.execute("UPDATE task_links SET state='closed' WHERE id=?", (link["id"],))
            if product and active and task["status"] in ("review", "ready"):
                after = _move(c, task, "doing", f"Pull request {link['title']} was closed without merging.")
                H._wake(c, after, after["owner"], f"Pull request {link['title']} was closed without merging: {after['title']}")
                moved.append((task["id"], "doing"))
        H.event(c, H.KEEPER, "github.pull_request", link["task_id"], {"action": action, "url": url})
    return {"pr": url, "action": action, "tasks": len(links), "moved": moved}


def push(c, payload):
    """A push to the default branch: every commit, in order, so a deploy can be placed on main."""
    ref = str(payload.get("ref") or "")
    repo = str((payload.get("repository") or {}).get("full_name") or "")
    default = str((payload.get("repository") or {}).get("default_branch") or "main")
    if ref != "refs/heads/" + default:
        return {"ref": ref, "commits": 0}
    shas = [str(x.get("id") or "") for x in (payload.get("commits") or [])]
    head = str((payload.get("head_commit") or {}).get("id") or "")
    if head and head not in shas:
        shas.append(head)
    n = 0
    for sha in shas:
        if sha and not c.execute("SELECT 1 FROM main_pushes WHERE sha=?", (sha,)).fetchone():
            c.execute("INSERT INTO main_pushes(sha, repo, pushed_at) VALUES(?,?,?)", (sha, repo, H.now()))
            n += 1
    return {"ref": ref, "commits": n}


DEPLOY_QUERY = ("SELECT l.*,p.seq AS merge_seq FROM task_links l JOIN tasks t ON t.id=l.task_id "
               "LEFT JOIN main_pushes p ON p.sha=l.pr_sha "
               "WHERE l.kind='pr' AND l.state='merged' AND l.url LIKE ? ESCAPE '\\' "
               "AND l.pr_sha IS NOT NULL AND t.status='ready'")


def ship_deployed(c, settings):
    """Every `ready` task whose merged pull request is in the running release is shipped."""
    commit, repo = settings.release_commit, settings.release_repo
    if not commit or not repo:
        return []
    here = c.execute("SELECT seq FROM main_pushes WHERE sha=?", (commit,)).fetchone()
    shipped = []
    for link in H._rows(c.execute(
            DEPLOY_QUERY,
            ("https://github.com/" + repo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/pull/%",))):
        with isolated(c, "ship_deployed", link["id"]):
            m = PR_LINK.match(link["url"])
            if not m or f"{m.group(1)}/{m.group(2)}".lower() != repo.lower():
                continue
            included = link["pr_sha"] == commit or (here and link["merge_seq"] and link["merge_seq"] <= here["seq"])
            if not included:
                continue
            task = H.task(c, link["task_id"])
            if not task or task["status"] != "ready":
                continue
            _move(c, task, "done", f"Shipped in release {commit[:12]} ({link['title']}).")
            c.execute("UPDATE task_links SET state='shipped' WHERE id=?", (link["id"],))
            H.event(c, H.KEEPER, "github.shipped", task["id"], {"release": commit, "url": link["url"]})
            shipped.append(task["id"])
    return shipped


def install_github(app, settings, store):
    @app.post(PATH)
    async def webhook(request: Request):
        body = await request.body()
        app_secret = app.state.github_app.webhook_secret()
        if not (verify(settings.github_webhook_secret, request.headers, body) or verify(app_secret, request.headers, body)):
            # unset: nothing to verify against, and the path does not exist for anyone
            raise Problem("forbidden", "Bad signature", 403 if settings.github_webhook_secret else 404)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            raise Problem("payload", "Send JSON", 400)
        event = str(request.headers.get("x-github-event") or "")
        if event == "ping":
            return {"ok": True}
        if event in ("installation", "installation_repositories"):
            from .repositories import sync
            app.state.github_app.cache.clear()
            app.state.github_app.live.clear()
            app.state.github_app.installation(refresh=True)
            sync(app.state.github_app)
            return {"ok": True}
        with store.transaction() as c:
            if event == "pull_request":
                result = pull_request(c, payload)
            elif event == "push":
                result = push(c, payload)
                result["shipped"] = ship_deployed(c, settings)
            else:
                return Response(status_code=204)
        return {"ok": True, **result}
