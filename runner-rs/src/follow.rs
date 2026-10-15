//! Keeps this runner on the release its server runs (runner/release_update.py `Follower`, docs/updates.md).
//! The server names its release (`GET runners/desired`, or the event stream's `ready.release`). A checkout (Mac,
//! Linux) hands the move to `python -m runner.release_update`, the same separate process the Python runner starts,
//! which checks the tag out, restarts this runner through its supervisor and rolls back if it does not report in.
//! A Docker runner asks its updater sidecar for the matching image. The heartbeat says where it stands (`release`,
//! `kind`, `commit`, `update`), so Settings > Computers and Health see a Rust computer as they see a Python one.
//!
//! Not ported: following git main on a server that names no release (a development server), and the disk-space
//! early retry; a failed update is tried again after six hours or on the server's next release, as before.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};

use crate::client::Client;
use crate::util::{epoch_s, log, text_of};

const STATUS_FILE: &str = "update-status.json";
const RETRY_AFTER_S: f64 = 6.0 * 3600.0;
const DRAIN_S: u64 = 20 * 60;
const STALE_UPDATING_S: f64 = 15.0 * 60.0;
const NO_SUPERVISOR: &str = "no supervisor would start this runner again after an update: run `scripts/tico install` once on this computer and it updates itself";

/// A semantic version's sort key (release_update.py `key`), or None.
fn key(value: &str) -> Option<(u64, u64, u64, Vec<(u8, u64, String)>)> {
    static R: OnceLock<regex::Regex> = OnceLock::new();
    let r = R.get_or_init(|| regex::Regex::new(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$").unwrap());
    let c = r.captures(value.trim().trim_start_matches('v'))?;
    let n = |i: usize| c[i].parse::<u64>().ok();
    // A release sorts after its pre-releases: (1,) against (0, parts...).
    let order = match c.get(4) {
        None => vec![(1, 0, String::new())],
        Some(pre) => std::iter::once((0, 0, String::new()))
            .chain(pre.as_str().split('.').map(|p| p.parse::<u64>().map_or((1, 0, p.to_string()), |d| (0, d, String::new()))))
            .collect(),
    };
    Some((n(1)?, n(2)?, n(3)?, order))
}

/// Whether `have` should move to `want`: an untagged or unknown release always should.
pub fn behind(have: &str, want: &str) -> bool {
    match (key(have), key(want)) {
        (_, None) => false,
        (None, Some(_)) => true,
        (Some(h), Some(w)) => h < w,
    }
}

pub fn kind() -> &'static str {
    match std::env::var("TICO_RUNNER_KIND").as_deref() {
        Ok("mac") => "mac",
        Ok("linux") => "linux",
        Ok("docker") => "docker",
        _ if Path::new("/.dockerenv").exists() => "docker",
        _ if cfg!(target_os = "macos") => "mac",
        _ => "linux",
    }
}

/// launchd's job label, the systemd unit `scripts/tico install` writes, or TICO_SUPERVISED=1 (service.py supervised).
pub fn supervised() -> bool {
    let var = |k: &str| std::env::var(k).unwrap_or_default();
    var("XPC_SERVICE_NAME").starts_with("team.tico") || var("TICO_SYSTEMD_UNIT").starts_with("tico-") || var("TICO_SUPERVISED") == "1"
}

fn git(root: &Path, args: &[&str]) -> String {
    let out = Command::new("git").arg("-C").arg(root).args(args).env("GIT_TERMINAL_PROMPT", "0").stdin(Stdio::null()).output();
    match out {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => String::new(),
    }
}

fn is_commit(s: &str) -> bool {
    (s.len() == 40 || s.len() == 64) && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn checkout_commit(root: &Path) -> String {
    Some(git(root, &["rev-parse", "HEAD"])).filter(|c| is_commit(c)).unwrap_or_default()
}

/// The release a checkout's HEAD is exactly on, the image's TICO_VERSION in Docker, or "".
fn current_release(root: &Path) -> String {
    let value = if kind() == "docker" {
        std::env::var("TICO_VERSION").unwrap_or_default()
    } else {
        git(root, &["describe", "--tags", "--exact-match", "HEAD"])
    };
    let value = value.trim().trim_start_matches('v').to_string();
    if key(&value).is_some() {
        value
    } else {
        String::new()
    }
}

fn manifest_commit(root: &Path) -> String {
    let text = std::fs::read_to_string(root.join("release-manifest.json")).unwrap_or_default();
    let value: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
    Some(text_of(&value["commit"])).filter(|c| is_commit(c)).unwrap_or_default()
}

/// Which commit this process runs, for `scripts/tico status` and the updater's health check (service.py record_revision).
pub fn record_revision(directory: &Path) {
    let revision = checkout_commit(&crate::env::root());
    let path = directory.join("runner-revision");
    if revision.len() != 40 {
        let _ = std::fs::remove_file(path);
        return;
    }
    let _ = std::fs::write(path, json!({"version": crate::runner::RUNNER_VERSION, "revision": revision, "started": epoch_s()}).to_string());
}

fn read_status(directory: &Path) -> Value {
    let v: Value = std::fs::read_to_string(directory.join(STATUS_FILE)).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null);
    if v.is_object() {
        v
    } else {
        json!({})
    }
}

fn write_status(directory: &Path, fields: Value) {
    let path = directory.join(STATUS_FILE);
    let tmp = directory.join("update-status.tmp");
    if std::fs::write(&tmp, fields.to_string()).is_ok() {
        let _ = std::fs::rename(tmp, path);
    }
}

/// The updater sidecar next to a Docker runner (release_update.py `Sidecar`).
struct Sidecar {
    url: String,
    token_file: PathBuf,
}

impl Sidecar {
    fn from_env() -> Sidecar {
        Sidecar {
            url: std::env::var("TICO_UPDATER_URL").unwrap_or_default().trim_end_matches('/').to_string(),
            token_file: PathBuf::from(std::env::var("TICO_UPDATER_TOKEN_FILE").unwrap_or_else(|_| "/control/updater-token".into())),
        }
    }

    async fn call(&self, post: Option<Value>) -> Result<Value, String> {
        let token = std::fs::read_to_string(&self.token_file).unwrap_or_default().trim().to_string();
        let http = reqwest::Client::builder().timeout(Duration::from_secs(10)).build().map_err(|e| e.to_string())?;
        let request = match &post {
            Some(body) => http.post(format!("{}/update", self.url)).json(body),
            None => http.get(format!("{}/status", self.url)),
        };
        let reply = request.bearer_auth(token).send().await.map_err(|_| "unreachable".to_string())?;
        let status = reply.status().as_u16();
        if !(200..300).contains(&status) {
            return Err(status.to_string());
        }
        Ok(reply.json().await.unwrap_or(json!({})))
    }
}

#[derive(Default)]
struct Inner {
    desired: Option<String>,
    features: Value,
    state: String,
    error: String,
    target: String,
    pending: Option<String>,
    pending_since: Option<Instant>,
    running: bool,
}

pub struct Follower {
    directory: PathBuf,
    root: PathBuf,
    kind: &'static str,
    release: String,
    started: String,
    commit: String,
    pinned: bool,
    sidecar: Sidecar,
    inner: Mutex<Inner>,
}

static SHARED: OnceLock<Follower> = OnceLock::new();

/// Set up once at start, before the loop.
pub fn init(config: &Map<String, Value>, directory: &Path) {
    let root = crate::env::root();
    let kind = kind();
    let env = |k: &str| std::env::var(k).unwrap_or_default();
    // A checkout with `self_update: false` stays where it is; a container always has that flag, so it uses the sidecar.
    let pinned = config.get("pinned") == Some(&Value::Bool(true))
        || env("TICO_RUNNER_PINNED") == "1"
        || (kind != "docker" && (config.get("self_update") == Some(&Value::Bool(false)) || env("TICO_RUNNER_SELF_UPDATE") == "0"));
    let started = if kind == "docker" { String::new() } else { checkout_commit(&root) };
    let commit = Some(manifest_commit(&root)).filter(|c| !c.is_empty()).unwrap_or_else(|| started.clone());
    let release = current_release(&root);
    let _ = SHARED.set(Follower {
        directory: directory.to_path_buf(),
        root,
        kind,
        release,
        started,
        commit,
        pinned,
        sidecar: Sidecar::from_env(),
        inner: Mutex::new(Inner { state: "idle".into(), ..Default::default() }),
    });
}

pub fn shared() -> Option<&'static Follower> {
    SHARED.get()
}

impl Follower {
    /// Ask the server's release (`desired` when the stream already said it), then decide.
    pub async fn poll(&self, client: &Client, desired: Option<String>) {
        let desired = match desired {
            Some(d) => d,
            None => match client.get("runners/desired").await {
                Ok(answer) => {
                    self.inner.lock().unwrap().features = answer["features"].clone();
                    text_of(&answer["version"])
                }
                // A server from before this existed: nothing is sent it.
                Err(e) if e.status == 404 || e.status == 405 => {
                    self.inner.lock().unwrap().desired = None;
                    return self.decide().await;
                }
                Err(_) => return, // a blip: keep what we knew
            },
        };
        self.inner.lock().unwrap().desired = Some(desired);
        self.decide().await;
    }

    /// (state, error) of the last update to `want` when it should not be tried again yet.
    async fn outcome(&self, want: &str) -> Option<(String, String)> {
        if self.kind == "docker" {
            let status = self.sidecar.call(None).await.unwrap_or(json!({}));
            let to = text_of(&status["to"]);
            if to.trim_start_matches('v') != want {
                return None;
            }
            return match status["state"].as_str().unwrap_or_default() {
                s @ ("rolled_back" | "failed") => Some((s.into(), text_of(&status["message"]))),
                "pulling" | "restarting" => Some(("updating".into(), String::new())),
                // The image came up but does not say it is `want`: never loop on pulling it again.
                "healthy" => Some(("failed".into(), format!("updated to {want}, but this runner still reports {}", if self.release.is_empty() { "no release" } else { &self.release }))),
                _ => None,
            };
        }
        let status = read_status(&self.directory);
        if text_of(&status["target"]) != want {
            return None;
        }
        let at = status["at"].as_f64().or_else(|| text_of(&status["at"]).parse().ok()).unwrap_or(0.0);
        let age = epoch_s() - at;
        match status["state"].as_str().unwrap_or_default() {
            "updating" if age < STALE_UPDATING_S => Some(("updating".into(), String::new())),
            "updating" => Some(("failed".into(), "the update stopped without an outcome".into())),
            s @ ("failed" | "rolled_back" | "blocked") if age < RETRY_AFTER_S => Some((s.into(), text_of(&status["error"]))),
            _ => None,
        }
    }

    fn no_updater_hint(want: &str) -> String {
        if std::env::var("TICO_RUNNER_COMPOSE").as_deref() == Ok("1") {
            return "no updater is set up; run docker compose pull && docker compose up -d on this box".into();
        }
        format!("no updater is set up; move this runner onto the compose file that has one: on this box run curl -fsSL https://github.com/ticoteam/tico/releases/download/v{want}/install.sh -o install.sh && sh install.sh --runner --url <your Tico address> --code <new code from Settings > Computers > Add computer> --label <name>")
    }

    async fn decide(&self) {
        let want = self.inner.lock().unwrap().desired.clone().unwrap_or_default();
        let verdict: Option<(String, String)> = if want.is_empty() || !behind(&self.release, &want) {
            Some(("idle".into(), String::new()))
        } else if self.pinned {
            Some(("pinned".into(), format!("pinned to this release; the server runs {want}")))
        } else if self.kind != "docker" && !supervised() {
            Some(("blocked".into(), NO_SUPERVISOR.into()))
        } else if self.kind == "docker" && self.sidecar.url.is_empty() {
            Some(("blocked".into(), Self::no_updater_hint(&want)))
        } else {
            self.outcome(&want).await
        };
        let mut s = self.inner.lock().unwrap();
        s.target = want.clone();
        s.pending = None;
        s.running = false;
        match verdict {
            Some((state, error)) => {
                s.running = state == "updating";
                s.state = state;
                s.error = error;
                s.pending_since = None;
            }
            None => {
                s.state = "waiting".into();
                s.error.clear();
                s.pending = Some(want);
                s.pending_since.get_or_insert_with(Instant::now);
            }
        }
    }

    /// True while an update is due or under way; starts it once nothing runs. After DRAIN_S it stops claiming.
    pub async fn blocks_claims(&self, active: bool) -> bool {
        let (pending, since) = {
            let s = self.inner.lock().unwrap();
            if s.running {
                return true;
            }
            match &s.pending {
                None => return false,
                Some(p) => (p.clone(), s.pending_since),
            }
        };
        if !active {
            self.launch(&pending).await;
            return true;
        }
        since.is_some_and(|t| t.elapsed().as_secs() >= DRAIN_S)
    }

    async fn launch(&self, want: &str) {
        let started = if self.kind == "docker" {
            match self.sidecar.call(Some(json!({"version": want}))).await {
                Ok(_) => Ok(()),
                Err(code) if code == "409" => Ok(()), // the updater is already on it
                Err(code) if code == "unreachable" => Err("the updater did not answer".to_string()),
                Err(code) => Err(format!("the updater answered {code}")),
            }
        } else {
            self.spawn(want)
        };
        let mut s = self.inner.lock().unwrap();
        s.pending = None;
        match started {
            Ok(()) => {
                log(&format!("Tico runner: updating to {want}"));
                s.state = "updating".into();
                s.running = true;
            }
            Err(why) => {
                s.state = "failed".into();
                s.error = format!("could not start the update: {why}");
                write_status(&self.directory, json!({"state": "failed", "target": want, "error": s.error, "at": epoch_s()}));
            }
        }
    }

    /// `python -m runner.release_update` as its own process, so it outlives the runner it restarts. Under systemd the
    /// runner's unit kills its whole cgroup on restart, so the update is a transient unit of its own (release_update.py spawn).
    fn spawn(&self, want: &str) -> Result<(), String> {
        let python = crate::env::python();
        let pid = std::process::id().to_string();
        let dir = self.directory.to_string_lossy().to_string();
        let root = self.root.to_string_lossy().to_string();
        let args = ["-m", "runner.release_update", "--root", &root, "--version", want, "--state-dir", &dir, "--pid", &pid, "--started", &self.started];
        let log_path = self.directory.join("update.log");
        let unit = std::env::var("TICO_SYSTEMD_UNIT").unwrap_or_default();
        if unit.ends_with(".service") && !unit.contains('/') {
            let mut cmd = Command::new("systemd-run");
            cmd.args(["--user", "--quiet", "--collect", &format!("--unit=tico-update-{pid}"), &format!("--working-directory={root}")]);
            for name in ["PATH", "HOME", "TICO_SUPERVISED", "TICO_RUNNER_KIND"] {
                if let Ok(v) = std::env::var(name) {
                    if !v.is_empty() {
                        cmd.arg(format!("--setenv={name}={v}"));
                    }
                }
            }
            cmd.arg(format!("--setenv=TICO_SYSTEMD_UNIT={unit}"));
            let log = log_path.to_string_lossy();
            cmd.args(["-p", &format!("StandardOutput=append:{log}"), "-p", &format!("StandardError=append:{log}")]);
            let done = cmd.arg(&python).args(args).stdin(Stdio::null()).output().map_err(|e| e.to_string())?;
            return if done.status.success() { Ok(()) } else { Err(format!("systemd-run exited {}", done.status.code().unwrap_or(-1))) };
        }
        use std::os::unix::process::CommandExt;
        let out = std::fs::OpenOptions::new().create(true).append(true).open(&log_path).map_err(|e| e.to_string())?;
        let err = out.try_clone().map_err(|e| e.to_string())?;
        let mut cmd = Command::new(&python);
        cmd.args(args).current_dir(&self.root).stdin(Stdio::null()).stdout(out).stderr(err);
        // SAFETY: setsid is async-signal-safe; the child gets its own session, as Popen(start_new_session=True).
        unsafe {
            cmd.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
        cmd.spawn().map(|_| ()).map_err(|e| e.to_string())
    }

    /// What a heartbeat adds; nothing for a server that does not name a release.
    pub fn fields(&self, body: &mut Value) {
        let s = self.inner.lock().unwrap();
        if s.desired.is_none() {
            return;
        }
        body["release"] = json!(if self.release.is_empty() { "dev" } else { &self.release });
        body["kind"] = json!(self.kind);
        if s.features["runner_commit"] == true && !self.commit.is_empty() {
            body["commit"] = json!(self.commit);
        }
        body["update"] = json!({"state": s.state, "target": s.target, "error": s.error.chars().take(300).collect::<String>()});
    }

    /// After a 422 that names `commit`: an older server, so it is not sent again.
    pub fn drop_commit(&self) {
        self.inner.lock().unwrap().features["runner_commit"] = json!(false);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn versions_sort_as_release_update_does() {
        assert!(behind("0.3.44", "0.3.45"));
        assert!(behind("", "0.3.45")); // a checkout on main moves to the server's release
        assert!(behind("0.3.45-rc.1", "0.3.45"));
        assert!(!behind("0.3.45", "v0.3.45"));
        assert!(!behind("0.3.46", "0.3.45"));
        assert!(!behind("0.3.45", "")); // a server with no release asks nothing
    }

    #[tokio::test]
    async fn a_failed_update_waits_and_a_due_one_starts_once_idle() {
        let dir = std::env::temp_dir().join(format!("tico-follow-{}", uuid::Uuid::new_v4().simple()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = Follower {
            directory: dir.clone(),
            root: dir.clone(),
            kind: "linux",
            release: "0.3.44".into(),
            started: String::new(),
            commit: String::new(),
            pinned: false,
            sidecar: Sidecar { url: String::new(), token_file: dir.join("t") },
            inner: Mutex::new(Inner { state: "idle".into(), desired: Some("0.3.45".into()), ..Default::default() }),
        };
        std::env::set_var("TICO_SUPERVISED", "1");
        write_status(&dir, json!({"state": "rolled_back", "target": "0.3.45", "error": "did not report in", "at": epoch_s()}));
        f.decide().await;
        let mut body = json!({});
        f.fields(&mut body);
        assert_eq!(body["update"], json!({"state": "rolled_back", "target": "0.3.45", "error": "did not report in"}));
        assert_eq!(body["release"], "0.3.44");
        assert!(!f.blocks_claims(false).await);

        write_status(&dir, json!({"state": "rolled_back", "target": "0.3.45", "at": epoch_s() - RETRY_AFTER_S - 1.0}));
        f.decide().await;
        assert_eq!(f.inner.lock().unwrap().state, "waiting");
        assert!(!f.blocks_claims(true).await); // a turn is running: keep claiming until the drain time
        let _ = std::fs::remove_dir_all(dir);
    }
}
