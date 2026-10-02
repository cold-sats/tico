"""GitHub moves a product-lane task through the pull request linked to it.

A task carries its pull request as a link (`hub task link`). The repository's webhook posts here
signed with `TICO_GITHUB_WEBHOOK_SECRET`; nothing else on this path is trusted:

- a pull request opened for review  -> the link is `open`,   the task is `review`
- the pull request merged or closed -> the task is `ready` once every PR is finished
- checks, conflicts and reviews     -> specific owner notices grouped within three minutes
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


def queue_wake(c, task, item):
    """Keep one bounded, durable burst per task; the scheduler sends it within three minutes."""
    from .repositories import metadata, save_metadata
    key = "github-task-wake:" + task["id"]
    burst = metadata(c, key)
    items = burst.get("items", [])
    if item not in items:
        items = (items + [item[:1000]])[-50:]
    save_metadata(c, key, {"due": burst.get("due") or H.shift(H.now(), seconds=170), "items": items})


def flush_wakes(c):
    from .repositories import metadata
    sent = []
    for row in c.execute("SELECT key FROM registry_metadata WHERE key LIKE 'github-task-wake:%'").fetchall():
        burst = metadata(c, row["key"])
        if burst.get("due", "") > H.now():
            continue
        task = H.task(c, row["key"].split(":", 1)[1])
        if task and task["status"] in H.ACTIVE_STATUSES:
            H._wake(c, task, task["owner"], "\n".join(burst.get("items", [])))
            sent.append(task["id"])
        c.execute("DELETE FROM registry_metadata WHERE key=?", (row["key"],))
    return sent


def _pr_status(c, task, note):
    # Retain the legacy product/custom pipeline opt-in.
    product = (task.get("lane") or "company") == "product" or task.get("type_id") not in (None, H.GENERAL_TYPE)
    if not product or task["status"] not in H.ACTIVE_STATUSES:
        return None
    links = [l for l in H.task_links(c, task["id"]) if l["kind"] == "pr"]
    if links and all(l["state"] in ("merged", "closed", "shipped") for l in links):
        status = "ready"
    elif any(l["state"] == "open" for l in links):
        status = "review"
    else:
        status = "doing"
    if status == task["status"]:
        return None
    _move(c, task, status, note)
    return (task["id"], status)


def pull_request(c, payload):
    pr = payload.get("pull_request") or {}
    url = str(pr.get("html_url") or "").split("?")[0].rstrip("/")
    action = str(payload.get("action") or "")
    links = _links_for(c, url)
    moved = []
    for link in links:
        task = H.task(c, link["task_id"])
        if not task:
            continue
        state = "merged" if pr.get("merged") else ("closed" if pr.get("state") == "closed" or action == "closed"
                else "draft" if pr.get("draft") or action == "converted_to_draft" else "open")
        mergeable = "conflict" if pr.get("mergeable") is False or pr.get("mergeable_state") == "dirty" else (
                    "clean" if pr.get("mergeable") is True else "unknown")
        match = PR_LINK.match(url)
        c.execute("UPDATE task_links SET state=?,mergeable=?,repo=?,number=?,branch=?,updated=?,"
                  "pr_sha=coalesce(?,pr_sha),pr_merged_at=coalesce(?,pr_merged_at) WHERE id=?",
                  (state, mergeable, match.group(1) + "/" + match.group(2) if match else None,
                   int(match.group(3)) if match else pr.get("number"), (pr.get("head") or {}).get("ref"), H.now(),
                   pr.get("merge_commit_sha") if state == "merged" else None,
                   pr.get("merged_at") or H.now() if state == "merged" else None, link["id"]))
        detail = H._json(link.get("detail_json"), {}) or {}
        head_sha = (pr.get("head") or {}).get("sha")
        if head_sha:
            if detail.get("head_sha") != head_sha:
                detail.pop("checks", None)
                c.execute("UPDATE task_links SET checks='pending' WHERE id=?", (link["id"],))
            detail["head_sha"] = head_sha
            c.execute("UPDATE task_links SET detail_json=? WHERE id=?", (json.dumps(detail), link["id"]))
        item = f"{link['title']} {state}" if state != "closed" else f"{link['title']} was closed without merging"
        if mergeable == "conflict":
            item += ": Merge conflict"
        if link["state"] != state or link.get("mergeable") != mergeable:
            queue_wake(c, task, item)
        move = _pr_status(c, task, f"Pull request {item}.")
        if move:
            moved.append(move)
        H.event(c, H.KEEPER, "github.pull_request", task["id"], {"action": action, "url": url})
    return {"pr": url, "action": action, "tasks": len(links), "moved": moved}


def pr_signal(c, event, payload):
    """Checks, commit statuses, reviews and review comments update every attached PR."""
    repo = str((payload.get("repository") or {}).get("full_name") or "")
    pr = payload.get("pull_request") or {}
    signal = payload.get("check_run") or payload.get("check_suite") or payload
    prs = signal.get("pull_requests") or ([pr] if pr else [])
    urls = {p.get("html_url") or f"https://github.com/{repo}/pull/{p['number']}" for p in prs if p.get("number") or p.get("html_url")}
    links = []
    for url in urls:
        links.extend(_links_for(c, url))
    if event == "status":
        # GitHub commit statuses have no PR list. Remember the head SHA from PR events.
        sha = payload.get("sha")
        links = H._rows(c.execute("SELECT * FROM task_links WHERE kind='pr' AND repo=? "
                                  "AND json_extract(detail_json,'$.head_sha')=?", (repo, sha)))
    for link in links:
        task = H.task(c, link["task_id"])
        if not task:
            continue
        detail = H._json(link.get("detail_json"), {}) or {}
        fields = {}
        label = link["title"]
        if event in ("check_run", "check_suite", "status"):
            if signal.get("head_sha") and detail.get("head_sha") and signal["head_sha"] != detail["head_sha"]:
                continue
            result = signal.get("conclusion") or signal.get("state") or "pending"
            state = "passing" if result in ("success", "neutral", "skipped") else (
                    "pending" if result in ("pending", "queued", "in_progress", "requested", "waiting") else "failing")
            checks = detail.get("checks", {})
            name = str(signal.get("name") or signal.get("context") or "Checks")[:200]
            checks[name] = state
            detail["checks"] = dict(list(checks.items())[-100:])
            fields["checks"] = "failing" if "failing" in checks.values() else "pending" if "pending" in checks.values() else "passing"
            item = f"Checks {state} on {label}: {name}"
        elif event == "pull_request_review":
            state = str((payload.get("review") or {}).get("state") or "").lower()
            if payload.get("action") == "dismissed":
                state = "commented"
            if state not in ("approved", "changes_requested", "commented"):
                continue
            fields["review_state"] = state
            item = f"Review {state.replace('_', ' ')} on {label}"
        else:
            action = payload.get("action")
            if action not in ("created", "deleted"):
                continue
            comment_id = str((payload.get("comment") or {}).get("id") or "")
            comments = detail.get("comments", {})
            if comment_id:
                if action == "created" and comments.get(comment_id) == "created":
                    continue
                if action == "deleted" and comments.get(comment_id) == "deleted":
                    continue
                comments[comment_id] = action
                detail["comments"] = dict(list(comments.items())[-100:])
            fields["pending_comments"] = max(0, (link.get("pending_comments") or 0) + (1 if action == "created" else -1))
            item = f"{fields['pending_comments']} review comments on {label}"
        fields.update(detail_json=json.dumps(detail), updated=H.now())
        c.execute("UPDATE task_links SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                  (*fields.values(), link["id"]))
        if any(link.get(k) != v for k, v in fields.items() if k != "updated"):
            queue_wake(c, task, item)
    return {"tasks": len({l["task_id"] for l in links})}


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


def ship_deployed(c, settings):
    """Every `ready` task whose merged pull request is in the running release is shipped."""
    commit, repo = settings.release_commit, settings.release_repo
    if not commit or not repo:
        return []
    here = c.execute("SELECT seq FROM main_pushes WHERE sha=?", (commit,)).fetchone()
    shipped = []
    for task in H._rows(c.execute("SELECT * FROM tasks WHERE status='ready'")):
        if H.children_summary(c, task["id"])["open"]:
            continue
        links = [l for l in H.task_links(c, task["id"]) if l["kind"] == "pr"]
        merged_links = [l for l in links if l["state"] == "merged"]
        if not merged_links or any(l["state"] not in ("merged", "closed", "shipped") for l in links):
            continue
        included = True
        for link in merged_links:
            match = PR_LINK.match(link["url"])
            if not match or f"{match.group(1)}/{match.group(2)}".lower() != repo.lower():
                included = False
                break
            merged = c.execute("SELECT seq FROM main_pushes WHERE sha=?", (link["pr_sha"],)).fetchone()
            if not (link["pr_sha"] == commit or here and merged and merged["seq"] <= here["seq"]):
                included = False
                break
        if not included:
            continue
        _move(c, task, "done", f"Shipped in release {commit[:12]} ({', '.join(l['title'] for l in merged_links)}).")
        for link in merged_links:
            c.execute("UPDATE task_links SET state='shipped',updated=? WHERE id=?", (H.now(), link["id"]))
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
            elif event in ("check_run", "check_suite", "status", "pull_request_review", "pull_request_review_comment"):
                result = pr_signal(c, event, payload)
            elif event == "push":
                result = push(c, payload)
                result["shipped"] = ship_deployed(c, settings)
            else:
                return Response(status_code=204)
        return {"ok": True, **result}
