//! The computer screen (capability `screen_v1`): a virtual display people can watch, and with the hub's
//! `control` mode drive, from the web app. Off unless this computer's owner turned it on here: `TICO_SCREEN=1`, or
//! `tico-runner screen on` (runner.json `screen: true`). The hub keeps its own off/view/control setting on top.
//!
//! While on, on Linux, the runner supervises `Xvfb :99`, a window manager and two `x11vnc`, one taking input and one
//! view-only. Neither listens on TCP: each serves a unix socket in a fresh directory only the runner's user can enter,
//! so no bot and no other VNC server can stand in for either. They run with that directory as HOME, a clean
//! environment, and x11vnc's rc files, external commands and remote control off, so nothing a bot writes reaches
//! them. A session the hub opens (the stream's `screen_open`, or the 10 s poll of `runners/me/screen/sessions`
//! while on) is one websocket to the hub, with the runner's own token, piped to the socket its `control` flag picks
//! while that x11vnc is the one this runner started and still runs; the runner, not the browser, decides which. Bot turns get `DISPLAY=:99` while the
//! display is up, so headed browsers and computer use draw where people can see them.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::process::{Child, Command};
use tokio::sync::{watch, Notify};

use crate::client::{bearer, Client, CLIENT_VERSION};
use crate::util::{log, text_of};

pub const CAPABILITY: &str = "screen_v1";
pub const DISPLAY: &str = ":99";
pub const WIDTH: u32 = 1440;
pub const HEIGHT: u32 = 900;
/// The VNC endpoints, as sockets in the private directory.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Endpoint {
    Control,
    View,
}

impl Endpoint {
    fn socket(self) -> &'static str {
        match self {
            Endpoint::Control => "control.sock",
            Endpoint::View => "view.sock",
        }
    }
}
const TOOLS: &[&str] = &["Xvfb", "x11vnc"];
/// Either window manager will do. matchbox (under 1 MB) is what the images and install.sh put in: it shows one
/// window at a time, full screen, which suits a viewer; openbox costs about 120 MB more (imlib2, Python).
const WINDOW_MANAGERS: &[&str] = &["matchbox-window-manager", "openbox"];

fn window_manager() -> Option<&'static str> {
    let path = std::env::var("PATH").unwrap_or_default();
    WINDOW_MANAGERS.iter().copied().find(|w| crate::env::which(w, &path).is_some())
}
const LOCK_EVERY: Duration = Duration::from_secs(5);
/// The hub fails a session no computer answered within 30 s; the stream's word is the fast path.
const POLL_EVERY: Duration = Duration::from_secs(10);
/// The hub ends a session at 60 minutes; this is the runner's own backstop.
const SESSION_CAP: Duration = Duration::from_secs(61 * 60);
/// How often a computer with its screen on asks whether the hub takes screens (a hub update can add it).
const HUB_EVERY: Duration = Duration::from_secs(300);
const BACKOFF_MAX_S: u64 = 60;
/// Xvfb failing this many starts in a row is reported as the reason the screen is unavailable.
const XVFB_GIVE_UP: u32 = 3;

// ------------------------------------------------------------------------------------------ the local lock

/// Whether the owner turned the screen on here, and what says so. `TICO_SCREEN`, when set, wins over runner.json.
pub fn lock_from(config: Option<&Value>, env: Option<&str>) -> (bool, &'static str) {
    let word = |s: &str| matches!(s.trim().to_ascii_lowercase().as_str(), "1" | "true" | "on" | "yes");
    if let Some(e) = env.filter(|e| !e.trim().is_empty()) {
        return (word(e), "TICO_SCREEN");
    }
    let on = match config {
        Some(Value::Bool(b)) => *b,
        Some(Value::String(s)) => word(s),
        Some(Value::Number(n)) => n.as_i64() == Some(1),
        _ => false,
    };
    (on, "runner config")
}

/// The lock as it stands now, read from the registration file (so `screen on|off` reaches a running runner).
pub fn lock(config_path: &Path) -> (bool, &'static str) {
    let data: Value = std::fs::read_to_string(config_path).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null);
    lock_from(data.get("screen"), std::env::var("TICO_SCREEN").ok().as_deref())
}

/// The programs a screen needs that are not on PATH.
pub fn missing_tools() -> Vec<&'static str> {
    let path = std::env::var("PATH").unwrap_or_default();
    let mut missing: Vec<&'static str> = TOOLS.iter().copied().filter(|t| crate::env::which(t, &path).is_none()).collect();
    if window_manager().is_none() {
        missing.push("a window manager");
    }
    missing
}

/// The readiness `screen` field: None when off; available with its size, or not with a short reason.
pub fn report(on: bool, os: &str, missing: &[&str], failure: Option<&str>, vnc_up: bool) -> Option<Value> {
    if !on {
        return None;
    }
    let reason = if os != "linux" {
        Some("Linux only for now".to_string())
    } else if !missing.is_empty() {
        Some(format!("Missing {}", missing.join(", ")))
    } else {
        failure.map(String::from).or_else(|| (!vnc_up).then(|| "VNC is not running".to_string()))
    };
    Some(match reason {
        Some(r) => json!({"available": false, "reason": r}),
        None => json!({"available": true, "width": WIDTH, "height": HEIGHT}),
    })
}

/// A readiness `screen` field offers the capability only when it says available.
pub fn offers(report: Option<&Value>) -> bool {
    report.is_some_and(|r| r["available"] == true)
}

/// The VNC endpoint a hub session pipes to: input only when the hub said `control: true`.
pub fn endpoint_for(session: &Value) -> Endpoint {
    if session["control"] == true {
        Endpoint::Control
    } else {
        Endpoint::View
    }
}

// ------------------------------------------------------------------------------------------ shared state

struct Shared {
    on: AtomicBool,
    up: AtomicBool,
    /// Each x11vnc this runner started is running and serving its socket.
    control_up: AtomicBool,
    view_up: AtomicBool,
    /// The private directory (0700, made fresh each time the display starts) holding the sockets and HOME.
    dir: Mutex<Option<PathBuf>>,
    /// The hub takes `screen_v1` and readiness `screen` (`runners/desired` features): an older one refuses both.
    hub: AtomicBool,
    failure: Mutex<Option<String>>,
    missing: Mutex<Vec<&'static str>>,
    /// Sessions with a bridge running here, so a poll never opens a second one.
    bridging: Mutex<HashSet<String>>,
    wake: Notify,
    switch: watch::Sender<bool>,
}

fn shared() -> &'static Shared {
    static S: OnceLock<Shared> = OnceLock::new();
    S.get_or_init(|| Shared {
        on: AtomicBool::new(false),
        up: AtomicBool::new(false),
        control_up: AtomicBool::new(false),
        view_up: AtomicBool::new(false),
        dir: Mutex::new(None),
        hub: AtomicBool::new(false),
        failure: Mutex::new(None),
        missing: Mutex::new(vec![]),
        bridging: Mutex::new(HashSet::new()),
        wake: Notify::new(),
        switch: watch::channel(false).0,
    })
}

/// This heartbeat's readiness `screen` field.
pub fn readiness() -> Option<Value> {
    let s = shared();
    if !s.hub.load(Ordering::SeqCst) {
        return None;
    }
    let failure = s.failure.lock().unwrap().clone();
    let vnc_up = s.control_up.load(Ordering::SeqCst) && s.view_up.load(Ordering::SeqCst);
    report(s.on.load(Ordering::SeqCst), std::env::consts::OS, &s.missing.lock().unwrap(), failure.as_deref(), vnc_up)
}

/// `DISPLAY` for a bot turn while the virtual display is up.
pub fn display() -> Option<&'static str> {
    shared().up.load(Ordering::SeqCst).then_some(DISPLAY)
}

/// The event stream said the hub opened a session: poll for it now.
pub fn heard() {
    shared().wake.notify_one();
}

// ------------------------------------------------------------------------------------------ the supervisor

struct Proc {
    name: &'static str,
    args: Vec<String>,
    /// An x11vnc's endpoint: it serves only that socket in the private directory.
    socket: Option<Endpoint>,
    child: Option<Child>,
    started: Option<Instant>,
    failures: u32,
    next: Instant,
}

impl Proc {
    fn new(name: &'static str, args: &[&str]) -> Proc {
        Proc { name, args: args.iter().map(|a| a.to_string()).collect(), socket: None, child: None, started: None, failures: 0, next: Instant::now() }
    }

    fn vnc(socket: Endpoint, args: &[&str]) -> Proc {
        Proc { socket: Some(socket), ..Proc::new("x11vnc", args) }
    }

    /// Running, and (for an x11vnc) its socket is there.
    fn serving(&mut self, dir: &Path) -> bool {
        self.running() && self.socket.is_none_or(|e| dir.join(e.socket()).exists())
    }

    fn running(&mut self) -> bool {
        let Some(child) = self.child.as_mut() else { return false };
        match child.try_wait() {
            Ok(None) => true,
            other => {
                let lived = self.started.map(|s| s.elapsed()).unwrap_or_default();
                let status = other.ok().flatten().map(|s| s.to_string()).unwrap_or_else(|| "unknown".into());
                self.child = None;
                // A long run resets the backoff; quick deaths back off to BACKOFF_MAX_S.
                self.failures = if lived > Duration::from_secs(60) { 1 } else { self.failures + 1 };
                let wait = 1u64 << self.failures.min(6);
                self.next = Instant::now() + Duration::from_secs(wait.min(BACKOFF_MAX_S));
                log(&format!("Tico runner: screen: {} exited ({status}); starting it again in {}s", self.name, wait.min(BACKOFF_MAX_S)));
                false
            }
        }
    }

    fn start(&mut self, dir: &Path) {
        if Instant::now() < self.next {
            return;
        }
        let mut cmd = Command::new(self.name);
        cmd.args(&self.args);
        if let Some(endpoint) = self.socket {
            let path = dir.join(endpoint.socket());
            let _ = std::fs::remove_file(&path); // one a previous x11vnc of ours left
            // `-rfbport 0` alone still leaves an IPv6 listener on 5900 on every interface.
            cmd.args(["-rfbport", "0", "-rfbportv6", "-1", "-unixsock"]).arg(&path);
        }
        // Nothing of the runner's environment (its token, the bots' settings) and nothing a bot can write.
        cmd.env_clear()
            .env("PATH", std::env::var("PATH").unwrap_or_else(|_| "/usr/bin:/bin".into()))
            .env("HOME", dir)
            .env("DISPLAY", DISPLAY)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true);
        #[cfg(target_os = "linux")]
        unsafe {
            // A runner that dies without stopping them takes its display with it, so the next one can have :99.
            cmd.pre_exec(|| {
                libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
                Ok(())
            });
        }
        match cmd.spawn() {
            Ok(child) => {
                self.child = Some(child);
                self.started = Some(Instant::now());
            }
            Err(e) => {
                self.failures += 1;
                self.next = Instant::now() + Duration::from_secs(BACKOFF_MAX_S);
                log(&format!("Tico runner: screen: cannot start {} ({e})", self.name));
            }
        }
    }

    /// Stop the one process this started (never anything found by name).
    async fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.start_kill();
            let _ = tokio::time::timeout(Duration::from_secs(5), child.wait()).await;
        }
        self.failures = 0;
        self.next = Instant::now();
    }
}

fn display_socket() -> PathBuf {
    PathBuf::from(format!("/tmp/.X11-unix/X{}", DISPLAY.trim_start_matches(':')))
}

/// x11vnc without its rc file, external commands, remote control (over X properties, which any X client can set)
/// or name lookups. Access is the socket's directory.
const VNC_ARGS: &[&str] = &["-display", DISPLAY, "-norc", "-nocmds", "-noremote", "-safer", "-nolookup", "-shared", "-forever", "-nopw", "-quiet"];

fn children() -> Vec<Proc> {
    let size = format!("{WIDTH}x{HEIGHT}x24");
    let view: Vec<&str> = VNC_ARGS.iter().copied().chain(["-viewonly"]).collect();
    vec![
        Proc::new("Xvfb", &[DISPLAY, "-screen", "0", &size, "-nolisten", "tcp"]),
        Proc::new(window_manager().unwrap_or(WINDOW_MANAGERS[0]), &[]),
        Proc::vnc(Endpoint::Control, VNC_ARGS),
        Proc::vnc(Endpoint::View, &view),
    ]
}

/// A new directory only this runner's user can enter: `/tmp/tico-screen-<random>`, 0700, never one that existed.
fn private_dir() -> std::io::Result<PathBuf> {
    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("tico-screen-{}", uuid::Uuid::new_v4().simple()));
    std::fs::DirBuilder::new().mode(0o700).create(&dir)?;
    Ok(dir)
}

static STOP: Notify = Notify::const_new();
static DONE: Notify = Notify::const_new();
static STARTED: AtomicBool = AtomicBool::new(false);

/// Follow the local lock for as long as the runner runs: start and restart the display while on (Linux), stop
/// it and every bridge when turned off, and open the hub's sessions.
pub fn start(config_path: PathBuf, client: Client) {
    STARTED.store(true, Ordering::SeqCst);
    tokio::spawn(sessions(client.clone()));
    tokio::spawn(async move {
        let s = shared();
        let mut procs = children();
        let mut said = false;
        let mut asked: Option<Instant> = None;
        loop {
            let (on, _) = lock(&config_path);
            if !on {
                asked = None;
            } else if asked.is_none_or(|at| at.elapsed() >= HUB_EVERY) {
                // A blip keeps what the hub last said; a hub without `runners/desired` takes no screen.
                match client.get("runners/desired").await {
                    Ok(answer) => s.hub.store(answer["features"]["screen_v1"] == true, Ordering::SeqCst),
                    Err(e) if e.status == 404 || e.status == 405 => s.hub.store(false, Ordering::SeqCst),
                    Err(_) => {}
                }
                asked = Some(Instant::now());
            }
            let missing = if on { missing_tools() } else { vec![] };
            *s.missing.lock().unwrap() = missing.clone();
            let usable = on && std::env::consts::OS == "linux" && missing.is_empty();
            if on != s.on.swap(on, Ordering::SeqCst) {
                log(&format!("Tico runner: screen turned {} on this computer", if on { "on" } else { "off" }));
            }
            if usable {
                said = false;
                tick(&mut procs).await;
            } else {
                if on && !said {
                    said = true;
                    log(&format!("Tico runner: screen is on but unavailable: {}", text_of(&readiness().unwrap_or_default()["reason"])));
                }
                stop_all(&mut procs).await;
                procs = children(); // the window manager is looked up again when next turned on
            }
            s.switch.send_replace(s.up.load(Ordering::SeqCst));
            tokio::select! {
                _ = tokio::time::sleep(LOCK_EVERY) => {}
                _ = STOP.notified() => break,
            }
        }
        stop_all(&mut procs).await;
        s.switch.send_replace(false);
        DONE.notify_one();
    });
}

async fn tick(procs: &mut [Proc]) {
    let s = shared();
    let dir = s.dir.lock().unwrap().clone();
    let dir = match dir {
        Some(d) => d,
        None => match private_dir() {
            Ok(d) => {
                *s.dir.lock().unwrap() = Some(d.clone());
                d
            }
            Err(e) => {
                *s.failure.lock().unwrap() = Some(format!("cannot make the screen's directory ({e})"));
                return;
            }
        },
    };
    let (xvfb, rest) = procs.split_first_mut().unwrap();
    if !xvfb.running() {
        s.up.store(false, Ordering::SeqCst);
        for p in rest.iter_mut() {
            p.stop().await; // they draw on a display that is gone
        }
        xvfb.start(&dir);
        if xvfb.child.is_none() {
            note_xvfb(xvfb);
            return;
        }
        // Up once its socket is there; Xvfb removes a stale lock from a display whose server is gone.
        let deadline = Instant::now() + Duration::from_secs(10);
        while !display_socket().exists() && Instant::now() < deadline && xvfb.running() {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        // A socket left by another X server on :99 is there at once; this Xvfb then exits within moments.
        tokio::time::sleep(Duration::from_millis(500)).await;
        if !xvfb.running() || !display_socket().exists() {
            note_xvfb(xvfb);
            return;
        }
        log(&format!("Tico runner: screen display {DISPLAY} is up ({WIDTH}x{HEIGHT})"));
    }
    *s.failure.lock().unwrap() = None;
    s.up.store(true, Ordering::SeqCst);
    let mut started = false;
    for p in rest.iter_mut() {
        if !p.running() {
            p.start(&dir);
            started = true;
        }
    }
    // A new x11vnc serves its socket within moments; until both do, no session opens and readiness says why.
    let deadline = Instant::now() + Duration::from_secs(if started { 5 } else { 0 });
    loop {
        let (control, view) = (rest[1].serving(&dir), rest[2].serving(&dir));
        s.control_up.store(control, Ordering::SeqCst);
        s.view_up.store(view, Ordering::SeqCst);
        if (control && view) || Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

fn note_xvfb(xvfb: &Proc) {
    if xvfb.failures >= XVFB_GIVE_UP {
        *shared().failure.lock().unwrap() = Some(format!("Xvfb {DISPLAY} did not start"));
    }
}

async fn stop_all(procs: &mut [Proc]) {
    let s = shared();
    s.up.store(false, Ordering::SeqCst);
    s.control_up.store(false, Ordering::SeqCst);
    s.view_up.store(false, Ordering::SeqCst);
    for p in procs.iter_mut().rev() {
        p.stop().await;
    }
    if let Some(dir) = s.dir.lock().unwrap().take() {
        let _ = std::fs::remove_dir_all(dir); // the one this runner made: its sockets and the children's HOME
    }
}

/// Stop the display and bridges this runner started, before the process exits.
pub async fn shutdown() {
    if STARTED.load(Ordering::SeqCst) {
        let done = DONE.notified();
        STOP.notify_one();
        let _ = tokio::time::timeout(Duration::from_secs(10), done).await;
    }
}

// ------------------------------------------------------------------------------------------ sessions

/// While the display is up: the hub's pending sessions, every POLL_EVERY and at once on `screen_open`.
async fn sessions(client: Client) {
    let s = shared();
    let mut said: Option<String> = None;
    loop {
        tokio::select! {
            _ = tokio::time::sleep(POLL_EVERY) => {}
            _ = s.wake.notified() => {}
        }
        if !s.up.load(Ordering::SeqCst) || !s.hub.load(Ordering::SeqCst) {
            continue;
        }
        let rows = match client.get("runners/me/screen/sessions").await {
            Ok(v) => {
                said = None;
                v["sessions"].as_array().cloned().unwrap_or_default()
            }
            Err(e) => {
                let text = crate::runner::describe(&e);
                if said.as_ref() != Some(&text) {
                    log(&format!("Tico runner: screen session poll failed ({text}); will retry"));
                    said = Some(text);
                }
                continue;
            }
        };
        for row in rows {
            let id = text_of(&row["session_id"]);
            if id.is_empty() || !id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
                continue;
            }
            if !s.bridging.lock().unwrap().insert(id.clone()) {
                continue;
            }
            let client = client.clone();
            let endpoint = endpoint_for(&row);
            tokio::spawn(async move {
                if let Err(e) = bridge(&client, &id, endpoint).await {
                    log(&format!("Tico runner: screen session {id} ended: {e}"));
                }
                shared().bridging.lock().unwrap().remove(&id);
            });
        }
    }
}

/// The hub's websocket for one session: `wss://<hub>/api/v2/runners/me/screen/<id>/ws`.
pub fn ws_url(hub: &str, session_id: &str) -> Result<String, String> {
    let rest = if let Some(r) = hub.strip_prefix("https://") {
        format!("wss://{r}")
    } else if let Some(r) = hub.strip_prefix("http://") {
        format!("ws://{r}")
    } else {
        return Err(format!("not an http(s) hub URL: {hub}"));
    };
    Ok(format!("{}/api/v2/runners/me/screen/{session_id}/ws", rest.trim_end_matches('/')))
}

/// Pipe one hub session to the local VNC port until either side closes, the screen goes off or the cap passes.
async fn bridge(client: &Client, session_id: &str, endpoint: Endpoint) -> Result<(), String> {
    use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};
    // Only to the x11vnc this runner started, while it runs: fail closed otherwise.
    let s = shared();
    let up = match endpoint {
        Endpoint::Control => &s.control_up,
        Endpoint::View => &s.view_up,
    };
    let dir = s.dir.lock().unwrap().clone();
    let Some(dir) = dir.filter(|_| up.load(Ordering::SeqCst)) else { return Err(format!("{endpoint:?} VNC is not running")) };
    let vnc = tokio::net::UnixStream::connect(dir.join(endpoint.socket())).await.map_err(|e| format!("{endpoint:?} VNC: {e}"))?;
    let token = bearer(&client.token).map_err(|e| e.detail)?;
    let mut request = ws_url(&client.url, session_id)?.into_client_request().map_err(|e| e.to_string())?;
    let headers = request.headers_mut();
    headers.insert("Authorization", format!("Bearer {token}").parse().map_err(|_| "bad token".to_string())?);
    headers.insert("User-Agent", format!("Tico-Client/{CLIENT_VERSION}").parse().unwrap());
    let (ws, _) = tokio::time::timeout(Duration::from_secs(15), tokio_tungstenite::connect_async(request))
        .await
        .map_err(|_| "the hub did not answer".to_string())?
        .map_err(|e| format!("websocket: {e}"))?;
    let (mut to_hub, mut from_hub) = ws.split();
    let (mut vnc_in, mut vnc_out) = vnc.into_split();
    let mut on = shared().switch.subscribe();
    let cap = tokio::time::sleep(SESSION_CAP);
    tokio::pin!(cap);
    let mut buf = vec![0u8; 64 * 1024];
    let result = loop {
        tokio::select! {
            read = vnc_in.read(&mut buf) => match read {
                Ok(0) => break Ok(()),
                Ok(n) => {
                    if let Err(e) = to_hub.send(Message::Binary(buf[..n].to_vec().into())).await {
                        break Err(format!("websocket: {e}"));
                    }
                }
                Err(e) => break Err(format!("VNC: {e}")),
            },
            frame = from_hub.next() => match frame {
                Some(Ok(Message::Binary(data))) => {
                    if let Err(e) = vnc_out.write_all(&data).await {
                        break Err(format!("VNC: {e}"));
                    }
                }
                Some(Ok(Message::Close(_))) | None => break Ok(()),
                Some(Ok(_)) => {} // pings are answered by tungstenite; text is not part of the protocol
                Some(Err(e)) => break Err(format!("websocket: {e}")),
            },
            changed = on.changed() => {
                if changed.is_err() || !*on.borrow() {
                    break Ok(());
                }
            }
            _ = &mut cap => break Ok(()),
        }
    };
    let _ = to_hub.send(Message::Close(None)).await;
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_lock_is_off_unless_turned_on_and_the_environment_wins() {
        assert_eq!(lock_from(None, None), (false, "runner config"));
        assert_eq!(lock_from(Some(&json!(true)), None), (true, "runner config"));
        assert!(!lock_from(Some(&json!("off")), None).0);
        assert_eq!(lock_from(Some(&json!(true)), Some("0")), (false, "TICO_SCREEN"));
        assert_eq!(lock_from(None, Some("1")), (true, "TICO_SCREEN"));
        assert_eq!(lock_from(Some(&json!(true)), Some(" ")), (true, "runner config"));
    }

    #[test]
    fn the_capability_is_offered_only_when_on_and_usable() {
        assert_eq!(report(false, "linux", &[], None, true), None);
        let up = report(true, "linux", &[], None, true);
        assert!(offers(up.as_ref()));
        assert_eq!(up.unwrap(), json!({"available": true, "width": 1440, "height": 900}));
        let mac = report(true, "macos", &[], None, true);
        assert!(!offers(mac.as_ref()));
        assert_eq!(mac.unwrap()["reason"], "Linux only for now");
        assert!(!offers(report(true, "linux", &["x11vnc"], None, true).as_ref()));
        assert!(!offers(report(true, "linux", &[], Some("Xvfb :99 did not start"), true).as_ref()));
        // Either x11vnc down (or one not ours on its endpoint): no capability, and readiness says so.
        assert_eq!(report(true, "linux", &[], None, false).unwrap()["reason"], "VNC is not running");
    }

    #[test]
    fn only_an_explicit_control_session_reaches_the_input_endpoint() {
        assert_eq!(endpoint_for(&json!({"session_id": "a", "control": true})), Endpoint::Control);
        assert_eq!(endpoint_for(&json!({"session_id": "a", "control": false})), Endpoint::View);
        assert_eq!(endpoint_for(&json!({"session_id": "a", "control": "true"})), Endpoint::View);
        assert_eq!(endpoint_for(&json!({"session_id": "a"})), Endpoint::View);
        assert_eq!(ws_url("https://hub.acme.example", "s1").unwrap(), "wss://hub.acme.example/api/v2/runners/me/screen/s1/ws");
        assert_eq!(ws_url("http://127.0.0.1:8000/", "s1").unwrap(), "ws://127.0.0.1:8000/api/v2/runners/me/screen/s1/ws");
    }
}
