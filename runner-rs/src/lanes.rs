//! Task lanes (task_lanes_v2): a task-keyed turn runs in its own lane beside the bot's other work, one turn at
//! a time per (bot, lane) on this computer (runner/state.py lane, runner/worktrees.py lane_lock). The claim names
//! the lanes busy here (`busy_lanes`); the heartbeat advertises the capabilities, each dropped for ten minutes
//! by a server that refuses it.

use std::collections::{BTreeSet, HashMap};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::util::text_of;

pub const MAIN_LANE: &str = "main";
pub const CAPABILITIES: &[&str] = &["task_lanes_v2", "session_roots_v1", "task_goals_v1"];
const DROP_FOR: Duration = Duration::from_secs(600);

/// The lane this turn runs in: the server's word when it sent one, else worked out the same way.
pub fn lane(attempt: &Value) -> String {
    let given = text_of(&attempt["lane"]);
    if !given.is_empty() {
        return given;
    }
    let key = crate::execute::session_key(attempt);
    if key.starts_with("task:") { key } else { MAIN_LANE.into() }
}

fn bare(bot: &str) -> &str {
    bot.strip_prefix("bot:").unwrap_or(bot)
}

type Locks = Mutex<HashMap<String, Arc<tokio::sync::Mutex<()>>>>;

fn locks() -> &'static Locks {
    static L: OnceLock<Locks> = OnceLock::new();
    L.get_or_init(Default::default)
}

/// One turn at a time per (bot, lane); a task's worktree maintenance takes its lane too.
pub fn lane_lock(bot: &str, lane: &str) -> Arc<tokio::sync::Mutex<()>> {
    locks().lock().unwrap().entry(format!("{}|{lane}", bare(bot))).or_default().clone()
}

#[derive(Clone, Debug)]
pub struct Running {
    pub bot: String,
    pub lane: String,
    #[allow(dead_code)] // the task worktree sweep reads it
    pub task: String,
    pub runtimes: BTreeSet<String>,
}

fn running() -> &'static Mutex<HashMap<String, Running>> {
    static R: OnceLock<Mutex<HashMap<String, Running>>> = OnceLock::new();
    R.get_or_init(Default::default)
}

/// Note a claimed attempt's lane and the runtimes it may use (its own and its fallback's).
pub fn track(attempt: &Value) {
    let config = &attempt["config"];
    let mut runtimes: BTreeSet<String> = [text_of(&config["runtime"])].into_iter().collect();
    if let Some(hop) = crate::fallback::configured(config) {
        runtimes.insert(hop.runtime);
    }
    runtimes.remove("");
    let row = Running { bot: text_of(&attempt["bot"]), lane: lane(attempt), task: text_of(&attempt["task"]["id"]), runtimes };
    running().lock().unwrap().insert(text_of(&attempt["id"]), row);
}

pub fn forget(aid: &str) {
    running().lock().unwrap().remove(aid);
}

#[allow(dead_code)] // the harness installer's mid-turn guard reads it
pub fn runtimes_in_use() -> BTreeSet<String> {
    running().lock().unwrap().values().flat_map(|r| r.runtimes.iter().cloned()).collect()
}

/// `bot|lane` for each live attempt, sorted and unique, as the claim's `busy_lanes`.
pub fn busy_lanes(live: &[String], bot_of: impl Fn(&str) -> Option<String>) -> Vec<String> {
    let rows = running().lock().unwrap();
    let set: BTreeSet<String> = live
        .iter()
        .filter_map(|aid| match rows.get(aid) {
            Some(r) => Some(format!("{}|{}", r.bot, r.lane)),
            None => bot_of(aid).map(|b| format!("{b}|{MAIN_LANE}")),
        })
        .collect();
    set.into_iter().collect()
}

fn dropped() -> &'static Mutex<HashMap<String, Instant>> {
    static D: OnceLock<Mutex<HashMap<String, Instant>>> = OnceLock::new();
    D.get_or_init(Default::default)
}

/// Whether a heartbeat or claim field is held back from a server that refused it in the last ten minutes.
pub fn held_back(name: &str) -> bool {
    dropped().lock().unwrap().get(name).is_some_and(|at| at.elapsed() < DROP_FOR)
}

pub fn hold_back(name: &str) {
    dropped().lock().unwrap().insert(name.into(), Instant::now());
}

/// The capabilities this heartbeat advertises.
pub fn capabilities() -> Vec<&'static str> {
    CAPABILITIES.iter().copied().filter(|c| !held_back(c)).collect()
}

/// What to leave out after a heartbeat's 422 (service.py maintain): the newest refused capability, else the
/// `profiles` report, else nothing (the refusal stands).
pub fn refused_field(detail: &str, body: &Value) -> Option<String> {
    let caps: Vec<String> = body["capabilities"].as_array().into_iter().flatten().map(text_of).collect();
    if detail.contains("capabilities") {
        for name in ["task_goals_v1", "session_roots_v1", "task_lanes_v2"] {
            if caps.iter().any(|c| c == name) {
                return Some(name.into());
            }
        }
    }
    let extra = detail.to_lowercase().contains("extra");
    if body.get("profiles").is_some() && (detail.contains("profiles") || (extra && detail.contains("weekly"))) {
        return Some("profiles".into());
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn task_turns_get_their_own_lane() {
        assert_eq!(lane(&json!({"bot": "ops", "config": {}, "task": {"id": "t1"}})), "task:t1");
        assert_eq!(lane(&json!({"bot": "ops", "config": {}, "lane": "task:t9"})), "task:t9");
        assert_eq!(lane(&json!({"bot": "ops", "config": {}, "conversation": {"id": "c"}})), "main");
        track(&json!({"id": "a1", "bot": "ops", "config": {"runtime": "codex", "fallback": {"harness": "claude", "model": "m"}}, "task": {"id": "t1"}}));
        track(&json!({"id": "a2", "bot": "ops", "config": {"runtime": "codex"}}));
        let live = vec!["a1".to_string(), "a2".to_string(), "a3".to_string()];
        assert_eq!(busy_lanes(&live, |a| (a == "a3").then(|| "sales".to_string())), vec!["ops|main", "ops|task:t1", "sales|main"]);
        assert!(runtimes_in_use().contains("claude"));
        forget("a1");
        forget("a2");
        assert_eq!(refused_field("body.capabilities: bad", &json!({"capabilities": ["task_lanes_v2", "task_goals_v1"]})).as_deref(), Some("task_goals_v1"));
    }
}
