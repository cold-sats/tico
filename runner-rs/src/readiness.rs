//! What the heartbeat says about this computer (`runtime_readiness`, `preflight` and `readiness` in
//! runner/service.py). Only the checks the chat path needs: runtime install, version, sign-in and models for
//! Claude and Codex, and per bot its repository, AGENT.md and bot.yaml. The server gates claims on these rows.

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{json, Map, Value};

use crate::config::Config;
use crate::env::which;
use crate::util::text_of;

pub const RUNTIMES: &[&str] = &["codex", "grok", "claude", "gemini", "pi", "cursor"];
/// The runtimes this runner can drive; the rest report as not installed so no bot of theirs is sent here.
pub const DRIVEN: &[&str] = &["claude", "codex"];
pub const CLAUDE_MODELS: &[&str] = &["claude-fable-5-1", "claude-opus-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"];
pub const NO_RUNTIME: &str = "No AI provider is chosen: the owner picks providers and a default model in Settings > AI providers";
const CLAUDE_AUTH_TIMEOUT_S: u64 = 30;

/// One command's exit status and output, or None when it did not run or ran past its time.
pub async fn run(argv: &[&str], timeout_s: u64) -> Option<(bool, String, String)> {
    let mut cmd = tokio::process::Command::new(argv[0]);
    cmd.args(&argv[1..]).stdin(std::process::Stdio::null()).kill_on_drop(true);
    let out = tokio::time::timeout(Duration::from_secs(timeout_s), cmd.output()).await.ok()?.ok()?;
    Some((out.status.success(), String::from_utf8_lossy(&out.stdout).into(), String::from_utf8_lossy(&out.stderr).into()))
}

fn executable(runtime: &str) -> Option<PathBuf> {
    which(runtime, &std::env::var("PATH").unwrap_or_default())
}

fn command(name: &str, help: &str, args: &str) -> Value {
    json!({"name": name, "args": args, "help": help, "kind": "harness"})
}

/// The harness commands a bot's chat offers (runner/goals.py capabilities). Goals are never claimed here:
/// this runner does not run goal turns.
async fn commands(runtime: &str, exe: &Path, version: &str) -> Vec<Value> {
    if runtime == "claude" {
        let re = regex::Regex::new(r"(\d+)\.(\d+)\.(\d+)").unwrap();
        let new_enough = re.captures(version).is_some_and(|c| {
            let n = |i: usize| c[i].parse::<u64>().unwrap_or(0);
            (n(1), n(2), n(3)) >= (2, 1, 212)
        });
        if new_enough {
            return vec![
                command("compact", "Compact this conversation", "[instructions]"),
                command("clear", "Clear the harness conversation", ""),
                command("model", "Change the harness model", "[model]"),
            ];
        }
        return vec![];
    }
    let dir = std::env::temp_dir().join(format!("tico-goal-schema-{}", uuid::Uuid::new_v4().simple()));
    let mut found = vec![];
    let exe = exe.to_string_lossy().to_string();
    let out = dir.to_string_lossy().to_string();
    if let Some((true, _, _)) = run(&[&exe, "app-server", "generate-json-schema", "--experimental", "--out", &out], 10).await {
        if dir.join("v2/ThreadCompactStartParams.json").exists() {
            found.push(command("compact", "Compact this conversation", ""));
        }
        if dir.join("v2/ReviewStartParams.json").exists() {
            found.push(command("review", "Review changes", "[instructions]"));
        }
    }
    let _ = std::fs::remove_dir_all(&dir);
    found
}

pub fn codex_models() -> Vec<String> {
    let home = std::env::var("CODEX_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".codex"));
    let Ok(text) = std::fs::read_to_string(home.join("models_cache.json")) else { return vec![] };
    let value: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
    let mut slugs: Vec<String> = value["models"]
        .as_array()
        .map(|rows| rows.iter().filter_map(|r| r["slug"].as_str()).filter(|s| !s.is_empty()).map(String::from).collect())
        .unwrap_or_default();
    slugs.sort();
    slugs.dedup();
    slugs
}

/// One runtime's row: installed, signed in, version, models, controls, detail, goals, commands.
pub async fn runtime_readiness(runtime: &str) -> Map<String, Value> {
    let exe = if DRIVEN.contains(&runtime) { executable(runtime) } else { None };
    let (mut authenticated, mut detail) = ("unknown", "Authentication cannot be checked without starting the runtime".to_string());
    let mut version = String::new();
    match &exe {
        None if !DRIVEN.contains(&runtime) => {
            authenticated = "missing";
            detail = format!("This runner does not run {runtime} yet");
        }
        None => {
            authenticated = "missing";
            detail = "Runtime executable is not on PATH".into();
        }
        Some(path) => {
            let p = path.to_string_lossy().to_string();
            if runtime == "codex" {
                match run(&[&p, "login", "status"], 8).await {
                    Some((ok, out, err)) => {
                        let output = format!("{out}\n{err}").trim().to_lowercase();
                        if ok && output.contains("logged in") {
                            authenticated = "ready";
                            detail = if output.contains("api key") { "Signed in with an API key" } else { "Signed in with ChatGPT" }.into();
                        } else {
                            authenticated = "missing";
                            detail = "Codex login required".into();
                        }
                    }
                    None => {
                        authenticated = "failed";
                        detail = "Codex sign-in check timed out".into();
                    }
                }
            } else {
                let status = run(&[&p, "auth", "status", "--json"], CLAUDE_AUTH_TIMEOUT_S).await;
                let parsed: Option<Value> = status.as_ref().and_then(|(_, out, _)| serde_json::from_str::<Value>(out).ok()).filter(|v| v.is_object());
                // A token in the environment signs the CLI in on a headless box even when `auth status` says otherwise.
                let token = ["CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"].into_iter().find(|n| std::env::var(n).is_ok_and(|v| !v.is_empty()));
                if let Some(s) = parsed.as_ref().filter(|s| s["loggedIn"] == true) {
                    authenticated = "ready";
                    let method = text_of(&s["authMethod"]);
                    detail = format!("Signed in with {}", if method.is_empty() { "Claude".into() } else { method });
                } else if let Some(name) = token {
                    authenticated = "ready";
                    detail = format!("Signed in with {name}");
                } else if status.is_none() {
                    authenticated = "failed";
                    detail = "Claude sign-in check timed out".into();
                } else if parsed.is_none() {
                    authenticated = "failed";
                    detail = "Claude sign-in could not be checked".into();
                } else {
                    authenticated = "missing";
                    detail = "Claude login required".into();
                }
            }
            if let Some((true, out, err)) = run(&[&p, "--version"], 5).await {
                let text = if out.trim().is_empty() { err } else { out };
                version = text.trim().lines().next().unwrap_or_default().chars().take(100).collect();
            }
        }
    }
    let models: Vec<String> = match runtime {
        "codex" => codex_models(),
        "claude" => CLAUDE_MODELS.iter().map(|s| s.to_string()).collect(),
        _ => vec![],
    };
    let commands = match &exe {
        Some(path) => commands(runtime, path, &version).await,
        None => vec![],
    };
    let mut row = Map::new();
    row.insert("installed".into(), json!(exe.is_some()));
    row.insert("authenticated".into(), json!(authenticated));
    row.insert("version".into(), json!(version));
    row.insert("models".into(), json!(models));
    row.insert("controls".into(), if exe.is_some() { json!(["interrupt", "new-session"]) } else { json!([]) });
    row.insert("detail".into(), json!(detail));
    row.insert("goals".into(), json!(false));
    row.insert("commands".into(), json!(commands));
    row
}

pub async fn runtime_report() -> Map<String, Value> {
    let mut report = Map::new();
    let mut names: Vec<&str> = RUNTIMES.to_vec();
    names.sort();
    for runtime in names {
        report.insert(runtime.into(), Value::Object(runtime_readiness(runtime).await));
    }
    report
}

/// A bot's checkout: the configured repos entry, else `bot-<slug>` or the older `emp-<slug>` under projects_dir.
pub fn local_path(config: &Config, bot: &str) -> PathBuf {
    if let Some(p) = config.repo_for(bot) {
        return p;
    }
    let root = config.projects_dir();
    for prefix in ["bot-", "emp-"] {
        if root.join(format!("{prefix}{bot}")).exists() {
            return root.join(format!("{prefix}{bot}"));
        }
    }
    root.join(format!("bot-{bot}"))
}

pub fn manifest_path(folder: &Path) -> PathBuf {
    for name in ["bot.yaml", "employee.yaml"] {
        if folder.join(name).is_file() {
            return folder.join(name);
        }
    }
    folder.join("bot.yaml")
}

/// The top-level scalar keys of a bot.yaml, read as text: this runner reads only `name`, `runtime` and `model`
/// and whether `watchers:` or `mcp:` blocks exist, so a full YAML parser is not worth its weight here.
pub fn manifest_keys(text: &str) -> Map<String, Value> {
    let mut keys = Map::new();
    for line in text.lines() {
        if line.starts_with([' ', '\t', '#', '-']) || line.trim().is_empty() {
            continue;
        }
        let Some((key, value)) = line.split_once(':') else { continue };
        let mut value = value.trim();
        if let Some(i) = value.find(" #") {
            value = value[..i].trim();
        }
        let value = value.trim_matches(|c| c == '"' || c == '\'');
        keys.insert(key.trim().to_string(), if value.is_empty() { Value::Null } else { json!(value) });
    }
    keys
}

async fn git(path: &Path, args: &[&str]) -> Option<(bool, String)> {
    let p = path.to_string_lossy().to_string();
    let mut argv = vec!["git", "-C", &p];
    argv.extend_from_slice(args);
    run(&argv, 5).await.map(|(ok, out, _)| (ok, out))
}

/// Each assigned bot's row: what blocks its turns here (`problems`) and what only warns.
pub async fn preflight(config: &Config, assignments: &[Value], runtimes: &Map<String, Value>) -> Vec<Map<String, Value>> {
    let mut rows = vec![];
    for entry in assignments {
        let bot = text_of(&entry["bot"]);
        let expected = &entry["config"];
        let runtime = text_of(&expected["runtime"]);
        let path = local_path(config, &bot);
        let mut problems: Vec<String> = vec![];
        let mut warnings: Vec<String> = vec![];
        let repository_present = path.join("AGENT.md").is_file();
        if !repository_present {
            problems.push("Missing bot repository or AGENT.md".into());
        } else if let Ok(text) = std::fs::read(path.join("AGENT.md")) {
            let lines = text.split(|b| *b == b'\n').count() - usize::from(text.ends_with(b"\n"));
            if lines > 150 {
                warnings.push(format!("AGENT.md is {lines} lines; keep current rules under 150 and move dated history to memory/decisions.md"));
            }
        }
        let status = runtimes.get(&runtime).cloned().unwrap_or(Value::Null);
        if runtime.is_empty() {
            problems.push(NO_RUNTIME.into());
        } else if !RUNTIMES.contains(&runtime.as_str()) {
            problems.push("Unsupported runtime".into());
        } else if !DRIVEN.contains(&runtime.as_str()) {
            problems.push(format!("This runner does not run {runtime} yet"));
        } else if status["installed"] != true {
            problems.push("Runtime executable is not on PATH".into());
        } else if status["authenticated"] == "missing" || status["authenticated"] == "failed" {
            let d = text_of(&status["detail"]);
            problems.push(if d.is_empty() { "Runtime sign-in is not ready".into() } else { d });
        }
        let mut configuration_valid = RUNTIMES.contains(&runtime.as_str());
        let manifest = manifest_path(&path);
        if repository_present && manifest.is_file() {
            configuration_valid = match std::fs::read_to_string(&manifest) {
                Ok(text) => {
                    let declared = manifest_keys(&text);
                    let cloud = expected["model_managed_by"] == "cloud";
                    let shared = text_of(&expected["shared_from"]);
                    let name = declared.get("name").map(text_of).filter(|n| !n.is_empty()).unwrap_or_else(|| bot.clone());
                    let same = |key: &str| {
                        cloud || declared.get(key).map(text_of).filter(|v| !v.is_empty()).is_none_or(|v| v == text_of(&expected[key]))
                    };
                    (name == bot || (!shared.is_empty() && name == shared)) && same("runtime") && same("model")
                }
                Err(_) => false,
            };
            if !configuration_valid {
                problems.push("Configuration differs from server".into());
            }
        }
        let mut revision = String::new();
        let mut published = Value::Null;
        if repository_present && path.join(".git").exists() {
            if let Some((true, out)) = git(&path, &["rev-parse", "--short=12", "HEAD"]).await {
                revision = out.trim().chars().take(100).collect();
            }
            if let Some((ok, _)) = git(&path, &["rev-parse", "--abbrev-ref", "@{u}"]).await {
                published = json!(ok);
            }
        }
        let mut row = Map::new();
        row.insert("bot".into(), json!(bot));
        row.insert("repository".into(), json!(path.to_string_lossy()));
        row.insert("runtime".into(), json!(runtime));
        row.insert("profile".into(), json!(""));
        row.insert("sign_in".into(), status.get("authenticated").cloned().unwrap_or(json!("unknown")));
        row.insert("model".into(), json!(text_of(&expected["model"])));
        row.insert("ready".into(), json!(problems.is_empty()));
        row.insert("repository_present".into(), json!(repository_present));
        row.insert("repository_revision".into(), json!(revision));
        row.insert("published".into(), published);
        row.insert("configuration_valid".into(), json!(configuration_valid));
        row.insert("problems".into(), json!(problems));
        row.insert("warnings".into(), json!(warnings));
        rows.push(row);
    }
    rows
}

/// The heartbeat's `readiness` document (backend/models.py RunnerReadiness).
pub fn document(runtimes: &Map<String, Value>, checks: &[Map<String, Value>], state_dir: &Path) -> Value {
    let mut bots = Map::new();
    for row in checks {
        let mut out = Map::new();
        for key in ["ready", "runtime", "model", "repository", "repository_present", "repository_revision", "configuration_valid", "problems", "profile", "sign_in"] {
            if let Some(v) = row.get(key) {
                out.insert(key.into(), v.clone());
            }
        }
        if out.get("sign_in") == Some(&json!("rejected")) {
            out.insert("sign_in".into(), json!("failed"));
        }
        let capability = &runtimes.get(&text_of(&row["runtime"])).cloned().unwrap_or(Value::Null);
        for key in ["goals", "commands"] {
            if let Some(v) = capability.get(key) {
                out.insert(key.into(), v.clone());
            }
        }
        if !row["published"].is_null() {
            out.insert("published".into(), row["published"].clone());
        }
        out.insert("warnings".into(), row.get("warnings").cloned().unwrap_or(json!([])));
        bots.insert(text_of(&row["bot"]), Value::Object(out));
    }
    let mut doc = json!({"schema_version": 1, "runtimes": runtimes, "bots": bots});
    if let Some((total, free)) = disk_usage(state_dir) {
        doc["disk"] = json!({"total_bytes": total, "free_bytes": free});
    }
    doc
}

pub fn disk_usage(path: &Path) -> Option<(u64, u64)> {
    use std::os::unix::ffi::OsStrExt;
    let c = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut s: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: a valid C string and a zeroed struct the call fills.
    if unsafe { libc::statvfs(c.as_ptr(), &mut s) } != 0 {
        return None;
    }
    let frsize = s.f_frsize as u64;
    Some((s.f_blocks as u64 * frsize, s.f_bavail as u64 * frsize))
}

/// AGENT.md of each bot this computer hosts, once and then only when the file changes
/// (`changed_agent_instructions`). Versions are (mtime ns, size); None for a missing file.
pub fn changed_agent_instructions(
    config: &Config,
    assignments: &[Value],
    published: &std::collections::HashMap<String, Option<(i128, u64)>>,
) -> (Map<String, Value>, Vec<(String, Option<(i128, u64)>)>) {
    let mine = config.runner_id();
    let (mut result, mut versions) = (Map::new(), vec![]);
    for entry in assignments {
        if mine.is_empty() || text_of(&entry["runner_id"]) != mine {
            continue;
        }
        let bot = text_of(&entry["bot"]);
        let path = local_path(config, &bot).join("AGENT.md");
        let meta = std::fs::symlink_metadata(&path).ok().filter(|m| m.is_file());
        let (version, content) = match meta {
            None => (None, String::new()),
            Some(m) => {
                if m.len() > 100_000 {
                    continue;
                }
                use std::os::unix::fs::MetadataExt;
                let version = Some((m.mtime() as i128 * 1_000_000_000 + m.mtime_nsec() as i128, m.len()));
                if published.get(&bot) == Some(&version) {
                    continue;
                }
                (version, String::from_utf8_lossy(&std::fs::read(&path).unwrap_or_default()).into_owned())
            }
        };
        if published.get(&bot) == Some(&version) {
            continue;
        }
        result.insert(bot.clone(), json!(content));
        versions.push((bot, version));
    }
    (result, versions)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manifest_keys_read_top_level_scalars_only() {
        let keys = manifest_keys("name: \"acme-ops\"  # the bot\nruntime: claude\nmodel:\naccess:\n  - service: board\n    name: x\nwatchers:\n  - a\n");
        assert_eq!(keys["name"], "acme-ops");
        assert_eq!(keys["runtime"], "claude");
        assert!(keys["model"].is_null() && keys.contains_key("watchers") && !keys.contains_key("service"));
    }
}
