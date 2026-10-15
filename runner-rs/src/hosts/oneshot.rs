//! The process side of the hosts that run one harness process per turn and read its JSON lines (Pi, Cursor):
//! the prompt goes in on
//! stdin, stderr to an unlinked file read back for the error text, one turn at a time, interrupt and stop by
//! signal. What a harness's lines mean is its `Wire`.

use std::collections::{HashMap, HashSet};
use std::io::{Read, Seek, SeekFrom};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Child;

use super::{event, failed, is_limit, Events, HostError, Settings};
use crate::env::Env;
use crate::util::log;

const STOP_TIMEOUT: Duration = Duration::from_secs(10);
const STDERR_TAIL: usize = 2000;

#[derive(Clone)]
pub struct Thread {
    pub bot: String,
    pub settings: Settings,
    /// The harness has this session (Pi's `session` event; a resumed thread).
    pub started: bool,
}

/// What one turn's lines have said so far.
#[derive(Default)]
pub struct Turn {
    pub reply: String,
    pub error: String,
    /// The harness said the turn is over (Pi `agent_end`, Cursor `result`).
    pub ended: bool,
    /// The harness confirmed its session (the thread is `started` from now on).
    pub session: bool,
    /// Events to emit, as (kind, fields).
    pub out: Vec<(&'static str, Value)>,
}

impl Turn {
    pub fn emit(&mut self, kind: &'static str, fields: Value) {
        self.out.push((kind, fields));
    }
}

pub trait Wire: Send + Sync + 'static {
    /// The host's name in its messages ("pi host is not running").
    const NAME: &'static str;
    /// The program, in "could not start {program}" and "{program} exited {rc}".
    const PROGRAM: &'static str;
    fn argv(cmd: &[String], thread_id: &str, t: &Thread, effort: Option<&str>) -> Vec<String>;
    fn env(settings: &Settings) -> Env;
    fn on_event(msg: &Value, turn: &mut Turn);
    fn succeeded(rc: i32, turn: &Turn) -> bool;
}

/// Python's `int(value or 0)` for a usage count; anything else is 0.
pub fn int_of(v: &Value) -> i64 {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)).unwrap_or(0),
        Value::String(s) => s.trim().parse().unwrap_or(0),
        Value::Bool(b) => *b as i64,
        _ => 0,
    }
}

/// The bot's environment, or the runner's own outside a turn, with HOME filled in.
pub fn base_env(settings: &Settings) -> Env {
    let mut env = if settings.env.is_empty() { crate::env::process_environment() } else { settings.env.clone() };
    if env.get("HOME").is_none_or(|h| h.is_empty()) {
        if let Ok(home) = std::env::var("HOME") {
            env.insert("HOME".into(), home);
        }
    }
    env
}

#[derive(Default)]
struct Inner {
    up: bool,
    threads: HashMap<String, Thread>,
    turn: Option<(String, String)>,
    stopper: Option<super::Stopper>,
    interrupted: HashSet<String>,
    done_turns: HashSet<String>,
    reader: Option<tokio::task::JoinHandle<()>>,
}

struct Shared<W> {
    bot: String,
    cmd: Vec<String>,
    tx: Events,
    inner: Mutex<Inner>,
    _wire: std::marker::PhantomData<W>,
}

pub struct OneShot<W: Wire>(Arc<Shared<W>>);

impl<W: Wire> Clone for OneShot<W> {
    fn clone(&self) -> Self {
        OneShot(self.0.clone())
    }
}

impl<W: Wire> OneShot<W> {
    pub fn new(bot: &str, cmd: Vec<String>, tx: Events) -> Self {
        OneShot(Arc::new(Shared { bot: bot.into(), cmd, tx, inner: Mutex::new(Inner::default()), _wire: Default::default() }))
    }

    pub fn cmd(&self) -> &[String] {
        &self.0.cmd
    }

    fn inner(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.0.inner.lock().unwrap_or_else(|p| p.into_inner())
    }

    fn emit(&self, ev: Value) {
        let _ = self.0.tx.send(ev);
    }

    pub fn start(&self) {
        self.inner().up = true;
    }

    pub async fn stop(&self) {
        let reader = {
            let mut inner = self.inner();
            inner.up = false;
            if let Some(s) = inner.stopper.take() {
                if let Some((_, turn)) = inner.turn.clone() {
                    inner.interrupted.insert(turn);
                }
                s.terminate(STOP_TIMEOUT);
            }
            inner.reader.take()
        };
        if let Some(r) = reader {
            let _ = tokio::time::timeout(STOP_TIMEOUT + Duration::from_secs(1), r).await;
        }
    }

    pub fn alive(&self) -> bool {
        self.inner().up
    }

    pub fn record(&self, thread_id: &str, settings: &Settings, started: bool) -> String {
        let t = Thread { bot: settings.slug.clone(), settings: settings.clone(), started };
        self.inner().threads.insert(thread_id.into(), t);
        thread_id.into()
    }

    fn launch(&self, argv: &[String], settings: &Settings) -> std::io::Result<(Child, std::fs::File)> {
        let path = std::env::temp_dir().join(format!("tico-{}-stderr-{}", W::NAME, uuid::Uuid::new_v4().simple()));
        let stderr = std::fs::OpenOptions::new().read(true).write(true).create_new(true).open(&path)?;
        let _ = std::fs::remove_file(&path);
        let mut command = crate::isolation::command(&argv[0]);
        command
            .args(&argv[1..])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(stderr.try_clone()?))
            .current_dir(&settings.cwd)
            .env_clear()
            .envs(W::env(settings));
        Ok((command.spawn()?, stderr))
    }

    pub fn start_turn(&self, thread_id: &str, text: &str, effort: Option<&str>) -> Result<String, HostError> {
        let turn = uuid::Uuid::new_v4().to_string();
        let (child, stderr) = {
            let mut inner = self.inner();
            if !inner.up {
                return Err(failed(format!("{} host is not running", W::NAME)));
            }
            if inner.turn.is_some() {
                return Err(failed(format!("{} host already has a turn running", W::NAME)));
            }
            let mut t = inner.threads.get(thread_id).cloned().ok_or_else(|| failed(format!("unknown {} thread {thread_id}", W::NAME)))?;
            if t.bot.is_empty() {
                t.bot = self.0.bot.clone();
            }
            let argv = W::argv(&self.0.cmd, thread_id, &t, effort);
            let launched = self.launch(&argv, &t.settings).map_err(|e| failed(format!("could not start {}: {e}", W::PROGRAM)))?;
            inner.turn = Some((thread_id.into(), turn.clone()));
            launched
        };
        log(&format!("{}[{}]: turn started pid {}", W::NAME, self.0.bot, child.id().map_or("?".into(), |p| p.to_string())));
        self.emit(event("status", Some(thread_id), None, json!({"state": "active"})));
        let host = self.clone();
        let (tid, t2, text) = (thread_id.to_string(), turn.clone(), text.to_string());
        let reader = tokio::spawn(async move { host.read_loop(child, stderr, tid, t2, text).await });
        self.inner().reader = Some(reader);
        Ok(turn)
    }

    async fn read_loop(&self, mut child: Child, mut stderr: std::fs::File, tid: String, turn: String, text: String) {
        let stdout = child.stdout.take();
        if let Some(mut stdin) = child.stdin.take() {
            tokio::spawn(async move {
                let _ = stdin.write_all(text.as_bytes()).await;
                let _ = stdin.shutdown().await;
            });
        }
        let (stopper, exited) = super::own(child);
        {
            let mut inner = self.inner();
            if !inner.up || inner.interrupted.contains(&turn) {
                stopper.terminate(STOP_TIMEOUT);
            }
            inner.stopper = Some(stopper);
        }
        let mut state = Turn::default();
        if let Some(stdout) = stdout {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let Ok(msg) = serde_json::from_str::<Value>(line.trim()) else { continue };
                W::on_event(&msg, &mut state);
                if std::mem::take(&mut state.session) {
                    if let Some(t) = self.inner().threads.get_mut(&tid) {
                        t.started = true;
                    }
                }
                for (kind, fields) in state.out.drain(..) {
                    self.emit(event(kind, Some(&tid), Some(&turn), fields));
                }
            }
        }
        let rc = match exited.await {
            Ok(status) => super::return_code(&status),
            Err(_) => -1,
        };
        self.finish(&tid, &turn, rc, &stderr_tail(&mut stderr), state);
    }

    fn finish(&self, tid: &str, turn: &str, rc: i32, stderr: &str, state: Turn) {
        let interrupted = {
            let mut inner = self.inner();
            if inner.turn.as_ref().is_some_and(|(_, t)| t == turn) {
                inner.turn = None;
                inner.stopper = None;
            }
            if !inner.done_turns.insert(turn.into()) {
                return;
            }
            inner.interrupted.contains(turn)
        };
        if interrupted {
            self.emit(event("turn_completed", Some(tid), Some(turn), json!({"status": "interrupted"})));
        } else if W::succeeded(rc, &state) {
            if !state.reply.is_empty() {
                self.emit(event("message", Some(tid), Some(turn), json!({"text": state.reply, "final": true})));
            }
            self.emit(event("turn_completed", Some(tid), Some(turn), json!({"status": "completed"})));
        } else {
            let error = [state.error.as_str(), stderr].into_iter().find(|t| !t.is_empty()).map(String::from).unwrap_or_else(|| format!("{} exited {rc}", W::PROGRAM));
            self.emit(event("turn_failed", Some(tid), Some(turn), json!({"error": error, "limit": is_limit(&error)})));
        }
        self.emit(event("status", Some(tid), None, json!({"state": "idle"})));
    }

    pub fn interrupt(&self, turn_id: &str) {
        let mut inner = self.inner();
        if inner.turn.as_ref().is_none_or(|(_, t)| t != turn_id) || inner.stopper.is_none() {
            return;
        }
        inner.interrupted.insert(turn_id.into());
        if let Some(s) = &inner.stopper {
            s.terminate(STOP_TIMEOUT);
        }
    }

    pub fn active_turn(&self, thread_id: &str) -> Option<String> {
        self.inner().turn.as_ref().filter(|(t, _)| t == thread_id).map(|(_, turn)| turn.clone())
    }
}

fn stderr_tail(file: &mut std::fs::File) -> String {
    let mut bytes = vec![];
    if file.seek(SeekFrom::Start(0)).is_ok() {
        let _ = file.read_to_end(&mut bytes);
    }
    let text = String::from_utf8_lossy(&bytes);
    let t = text.trim();
    let skip = t.chars().count().saturating_sub(STDERR_TAIL);
    t.chars().skip(skip).collect()
}

#[cfg(test)]
pub mod testing {
    //! A fake harness that plays a fixture once its stdin closes, for the Pi and Cursor host tests.
    use std::path::Path;
    use std::time::Duration;

    use serde_json::Value;
    use tokio::sync::mpsc;

    /// `name` in `dir`: logs its argv to $ARGS_LOG and stdin to $ARGS_LOG.prompt, then prints $FIXTURE (or, for
    /// `create-chat`, a chat id) and exits $RC (0 by default).
    pub fn fake(dir: &Path, name: &str) -> String {
        use std::os::unix::fs::PermissionsExt;
        let path = dir.join(name);
        std::fs::write(
            &path,
            "#!/bin/sh\necho \"$@\" >> \"$ARGS_LOG\"\nif [ \"$1\" = create-chat ]; then echo 0b5c2f1e-3a4d-4e6f-8a9b-0c1d2e3f4a5b; exit 0; fi\ncat > \"$ARGS_LOG.prompt\"\ncat \"$FIXTURE\"\nexit ${RC:-0}\n",
        )
        .unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
        path.display().to_string()
    }

    /// One turn's events, without their thread and turn ids, up to the closing `status idle`.
    pub async fn turn_events(rx: &mut mpsc::UnboundedReceiver<Value>) -> Vec<Value> {
        let mut got = vec![];
        while let Ok(Some(mut ev)) = tokio::time::timeout(Duration::from_secs(10), rx.recv()).await {
            let idle = ev["kind"] == "status" && ev["state"] == "idle";
            ev.as_object_mut().unwrap().retain(|k, _| k != "thread_id" && k != "turn_id");
            got.push(ev);
            if idle {
                break;
            }
        }
        got
    }
}
