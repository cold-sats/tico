//! The Pi coding-agent host: one `pi --mode json -p` per turn, for the models with no CLI
//! of their own, through OpenRouter. The session id is the thread id and the sessions live in the workspace:
//!
//!     pi --mode json -p --provider openrouter --model deepseek/deepseek-v4.1-flash --thinking low
//!        --tools read,bash,edit,write,grep,find,ls --session-id <uuid> --session-dir <dir> --approve
//!
//! Pi has no MCP and no permission prompts (the bot uses the hub CLI over bash); `steer` is refused.
//! OPENROUTER_API_KEY reaches the process from the bot's granted credential.

use std::path::PathBuf;

use serde_json::{json, Value};

use super::oneshot::{base_env, int_of, OneShot, Thread, Turn, Wire};
use super::Settings;
use crate::env::Env;
use crate::util::{text_of, truthy};

pub const PROVIDER: &str = "openrouter";
/// Catalog id -> OpenRouter model id (clients/openrouter.py MODELS, shared with the server's decision model).
pub const MODELS: &[(&str, &str)] = &[
    ("deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash"),
    ("deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
    ("kimi-k3", "moonshotai/kimi-k3"),
    ("kimi-k2.7-code", "moonshotai/kimi-k2.7-code"),
    ("llama-4-maverick", "meta-llama/llama-4-maverick"),
    ("mistral-medium-3.5", "mistralai/mistral-medium-3-5"),
    ("devstral-2512", "mistralai/devstral-2512"),
];
const DEFAULT_MODEL: &str = "deepseek-v4.1-flash";
const TOOLS: &str = "read,bash,edit,write,grep,find,ls";

/// The catalog ids, sorted (readiness `models`).
pub fn model_names() -> Vec<String> {
    let mut names: Vec<String> = MODELS.iter().map(|(k, _)| k.to_string()).collect();
    names.sort();
    names
}

/// The OpenRouter id for a catalog id; one that is already OpenRouter's (or unknown) passes through.
pub fn model_for(model: Option<&str>) -> String {
    let m = model.unwrap_or_default().trim();
    let m = if m.is_empty() || m == "default" { DEFAULT_MODEL } else { m };
    MODELS.iter().find(|(k, _)| *k == m).map_or(m, |(_, v)| v).to_string()
}

pub fn effort_for(effort: Option<&str>) -> &'static str {
    match effort.unwrap_or_default().trim().to_lowercase().as_str() {
        "high" => "high",
        "xhigh" | "max" => "max",
        _ => "low",
    }
}

fn first(u: &Value, keys: &[&str]) -> i64 {
    keys.iter().map(|k| int_of(&u[*k])).find(|v| *v != 0).unwrap_or(0)
}

const INPUT: &[&str] = &["input", "input_tokens", "inputTokens", "prompt_tokens", "promptTokens"];
const OUTPUT: &[&str] = &["output", "output_tokens", "outputTokens", "completion_tokens", "completionTokens"];

/// (input, output, total) from a Pi/OpenRouter usage object.
pub fn usage_tokens(usage: &Value) -> (i64, i64, i64) {
    let (inp, out) = (first(usage, INPUT), first(usage, OUTPUT));
    let total = first(usage, &["total", "total_tokens", "totalTokens"]);
    (inp, out, if total != 0 { total } else { inp + out })
}

/// {input, cached, output} for one assistant message: Pi keeps cache reads and writes apart from `input`; the
/// meter counts them all as input, the reads also as cached.
pub fn usage_increment(usage: &Value) -> Value {
    let read = first(usage, &["cacheRead", "cache_read", "cachedTokens"]);
    let inp = first(usage, INPUT) + read + first(usage, &["cacheWrite", "cache_write"]);
    json!({"input": inp, "cached": read, "output": first(usage, OUTPUT)})
}

/// The run's granted key; outside a turn (no bot environment) also the machine's, as local diagnostics read it.
pub fn openrouter_key(env: &Env, local: bool) -> String {
    let process = if local { std::env::var("OPENROUTER_API_KEY").ok() } else { None };
    if let Some(v) = [env.get("OPENROUTER_API_KEY").cloned(), process].into_iter().flatten().find(|v| !v.trim().is_empty()) {
        return v.trim().to_string();
    }
    if !local {
        return String::new();
    }
    let root = PathBuf::from(env.get("HUB_WORKSPACE").cloned().unwrap_or_default());
    crate::signin::read_env(&root.join("secrets").join("_shared.env"))
        .get("OPENROUTER_API_KEY")
        .map(|v| v.trim_matches(|c| c == '\'' || c == '"').to_string())
        .unwrap_or_default()
}

/// The pi runtime's sign-in: an OPENROUTER_API_KEY grant for every bot that runs on it.
pub fn sign_in(assignments: &[Value]) -> (&'static str, String) {
    let mut missing: Vec<String> = assignments
        .iter()
        .filter(|r| r["config"]["runtime"] == "pi")
        .map(|r| text_of(&r["bot"]))
        .filter(|bot| !crate::hosts::gemini::has_grant(bot, "OPENROUTER_API_KEY"))
        .collect();
    missing.sort();
    if missing.is_empty() {
        ("ready", "OpenRouter API key configured".into())
    } else {
        ("missing", format!("OpenRouter API key grant required ({})", missing.join(", ")))
    }
}

/// `<workspace>/runtime/pi-sessions/<bot>`, made on first use (the bot user's, when isolated).
pub fn session_dir(bot: &str, settings: &Settings) -> PathBuf {
    let root = settings.env.get("HUB_WORKSPACE").filter(|w| !w.is_empty()).cloned().unwrap_or_else(|| if settings.cwd.is_empty() { ".".into() } else { settings.cwd.clone() });
    let path = PathBuf::from(root).join("runtime").join("pi-sessions").join(if bot.is_empty() { "pi" } else { bot });
    let _ = crate::isolation::mkdir(&path, 0o777);
    path
}

/// An assistant message's text: a plain string, or its text blocks joined.
fn assistant_text(message: &Value) -> String {
    match message {
        Value::String(s) if !s.trim().is_empty() => s.clone(),
        Value::Object(m) => {
            if !matches!(m.get("role"), None | Some(Value::Null)) && m.get("role") != Some(&json!("assistant")) {
                return String::new();
            }
            match m.get("content") {
                Some(Value::String(s)) => s.clone(),
                Some(Value::Array(blocks)) => blocks
                    .iter()
                    .filter_map(|b| match b {
                        Value::String(s) => Some(s.clone()),
                        Value::Object(b) if b.get("type").is_none_or(|t| t.is_null() || t == "text") && truthy(b.get("text")) => Some(text_of(&b["text"])),
                        _ => None,
                    })
                    .collect(),
                _ => String::new(),
            }
        }
        _ => String::new(),
    }
}

pub struct Pi;

impl Wire for Pi {
    const NAME: &'static str = "pi";
    const PROGRAM: &'static str = "pi";

    fn argv(cmd: &[String], thread_id: &str, t: &Thread, effort: Option<&str>) -> Vec<String> {
        let s = &t.settings;
        let mut argv = cmd.to_vec();
        argv.extend(
            [
                "--mode", "json", "-p", "--provider", PROVIDER, "--model", &model_for(s.model.as_deref()),
                "--thinking", effort_for(effort.or(s.effort.as_deref())), "--tools", TOOLS, "--session-id", thread_id,
                "--session-dir", &session_dir(&t.bot, s).display().to_string(), "--approve",
            ]
            .map(String::from),
        );
        argv
    }

    fn env(settings: &Settings) -> Env {
        let mut env = base_env(settings);
        let key = openrouter_key(&env, settings.env.is_empty());
        if !key.is_empty() {
            env.insert("OPENROUTER_API_KEY".into(), key);
        }
        env
    }

    fn on_event(msg: &Value, turn: &mut Turn) {
        let Some(m) = msg.as_object() else { return };
        match m.get("type").and_then(|t| t.as_str()).unwrap_or_default() {
            "session" if truthy(m.get("id")) => turn.session = true,
            "message_update" => {
                let ev = &msg["assistantMessageEvent"];
                if ev["type"] == "text_delta" && truthy(ev.get("delta")) {
                    turn.emit("delta", json!({"text": ev["delta"], "delta_kind": "text"}));
                }
                if truthy(m.get("usage")) {
                    let (inp, out, total) = usage_tokens(&msg["usage"]);
                    if total != 0 {
                        turn.emit("tokens", json!({"input": inp, "output": out, "total": total}));
                    }
                }
            }
            "message_end" => {
                let done = &msg["message"];
                if done["role"] == "assistant" && done["usage"].is_object() {
                    // One assistant message ends once, so this is where its tokens are counted.
                    let (inp, out, total) = usage_tokens(&done["usage"]);
                    turn.emit("tokens", json!({"input": inp, "output": out, "total": total, "usage": usage_increment(&done["usage"])}));
                }
                let text = assistant_text(done);
                if !text.is_empty() {
                    turn.reply = text.clone();
                    turn.emit("message", json!({"text": text, "final": false}));
                }
            }
            "turn_end" => {
                let text = assistant_text(&msg["message"]);
                if !text.is_empty() {
                    turn.reply = text;
                }
            }
            "error" => {
                let err = [m.get("error"), m.get("message")].into_iter().flatten().find(|v| truthy(Some(v))).cloned().unwrap_or(json!("pi error"));
                turn.error = match &err {
                    Value::Object(e) => e.get("message").filter(|v| truthy(Some(v))).map(text_of).unwrap_or_else(|| err.to_string()),
                    other => text_of(other),
                };
            }
            "agent_end" => turn.ended = true,
            kind @ ("tool_execution_start" | "tool_execution_end") => {
                let name = m.get("toolName").filter(|v| truthy(Some(v))).cloned().unwrap_or(json!(""));
                turn.emit("tool", json!({"name": name, "tool": name, "phase": kind}));
            }
            _ => {}
        }
    }

    fn succeeded(rc: i32, turn: &Turn) -> bool {
        rc == 0 || (turn.ended && turn.error.is_empty())
    }
}

pub type PiHost = OneShot<Pi>;

impl PiHost {
    pub fn start_thread(&self, settings: &Settings) -> String {
        self.record(&uuid::Uuid::new_v4().to_string(), settings, false)
    }

    pub fn resume_thread(&self, thread_id: &str, settings: &Settings) -> String {
        self.record(thread_id, settings, true)
    }
}

#[cfg(test)]
mod tests {
    use super::super::oneshot::testing::{fake, turn_events};
    use super::*;
    use tokio::sync::mpsc;

    #[tokio::test]
    async fn every_pi_fixture_gives_the_python_hosts_events_and_its_command_line() {
        let dir = std::env::temp_dir().join(format!("fake-pi-{}", uuid::Uuid::new_v4().simple()));
        std::fs::create_dir_all(&dir).unwrap();
        let cmd = fake(&dir, "pi");
        for (path, expected) in crate::hosts::fixtures::cases("pi") {
            let (tx, mut rx) = mpsc::unbounded_channel();
            let host = PiHost::new("acme", vec![cmd.clone()], tx);
            host.start();
            let mut s = Settings { cwd: dir.display().to_string(), model: Some("kimi-k3".into()), slug: "acme".into(), ..Default::default() };
            for (k, v) in [("PATH", "/usr/bin:/bin".to_string()), ("HUB_WORKSPACE", dir.display().to_string()), ("OPENROUTER_API_KEY", " or-key ".into()), ("ARGS_LOG", dir.join("args.log").display().to_string()), ("FIXTURE", path.display().to_string())] {
                s.env.insert(k.into(), v);
            }
            let rc = if path.file_stem().is_some_and(|n| n == "error") { "1" } else { "0" };
            s.env.insert("RC".into(), rc.into());
            let thread = host.start_thread(&s);
            host.start_turn(&thread, "hello", Some("xhigh")).unwrap();
            assert_eq!(turn_events(&mut rx).await, expected, "{}", path.display());
            host.stop().await;
            let args = std::fs::read_to_string(dir.join("args.log")).unwrap();
            let sessions = dir.join("runtime/pi-sessions/acme");
            assert_eq!(
                args.lines().last().unwrap(),
                format!("--mode json -p --provider openrouter --model moonshotai/kimi-k3 --thinking max --tools {TOOLS} --session-id {thread} --session-dir {} --approve", sessions.display())
            );
            assert!(sessions.is_dir());
        }
        assert_eq!(std::fs::read_to_string(dir.join("args.log.prompt")).unwrap(), "hello");
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn models_efforts_usage_and_keys_follow_the_python_host() {
        assert_eq!(model_for(None), "deepseek/deepseek-v4.1-flash");
        assert_eq!(model_for(Some("default")), "deepseek/deepseek-v4.1-flash");
        assert_eq!(model_for(Some("qwen/qwen3-coder")), "qwen/qwen3-coder");
        assert_eq!((effort_for(Some("Medium")), effort_for(Some("high")), effort_for(Some("max")), effort_for(None)), ("low", "high", "max", "low"));
        assert_eq!(usage_tokens(&json!({"promptTokens": "7", "output": 0, "completion_tokens": 3})), (7, 3, 10));
        assert_eq!(usage_increment(&json!({"input": 5, "cacheRead": 4, "cacheWrite": 1, "output": 2})), json!({"input": 10, "cached": 4, "output": 2}));
        let mut env = Env::new();
        assert_eq!(openrouter_key(&env, false), "");
        env.insert("OPENROUTER_API_KEY".into(), " k ".into());
        assert_eq!(openrouter_key(&env, false), "k");
        assert_eq!(model_names()[0], "deepseek-v4-pro");
    }
}
