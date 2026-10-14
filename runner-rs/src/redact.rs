//! Keep the secrets a turn was granted out of what the runner writes down (`runner/redact.py`).
//!
//! One redactor per turn holds its granted values and the common ways each turns up (URL-encoded, base64
//! with and without padding, the password half of `user:password`) and replaces them with `••••`, longest
//! match first, in one pass. A turn with nothing worth hiding has no redactor.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex, OnceLock, RwLock};

use aho_corasick::{AhoCorasick, AhoCorasickBuilder, MatchKind};
use base64::Engine;
use serde_json::Value;

pub const MASK: &str = "••••";
pub const MIN_LENGTH: usize = 8;
const COMMON: &[&str] = &[
    "localhost", "127.0.0.1", "production", "development", "password", "username", "enabled", "disabled", "undefined",
    "identity", "anonymous", "internal", "external", "default", "standard", "true", "false",
];
const TEXT_LIMIT: u64 = 2_000_000;

/// `urllib.parse.quote(value, safe="")`.
pub fn quote(value: &str) -> String {
    let mut out = String::new();
    for b in value.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

fn variants(value: &str) -> BTreeSet<String> {
    let mut forms = BTreeSet::new();
    forms.insert(value.to_string());
    forms.insert(quote(value));
    forms.insert(crate::client::quote_plus(value));
    for text in [
        base64::engine::general_purpose::STANDARD.encode(value.as_bytes()),
        base64::engine::general_purpose::URL_SAFE.encode(value.as_bytes()),
    ] {
        forms.insert(text.trim_end_matches('=').to_string());
        forms.insert(text);
    }
    forms
}

fn worth(value: &str) -> bool {
    if value.chars().count() < MIN_LENGTH || COMMON.contains(&value.to_lowercase().as_str()) {
        return false;
    }
    value.chars().collect::<BTreeSet<_>>().len() >= 3
}

fn values(secrets: &[String]) -> BTreeSet<String> {
    let mut found = BTreeSet::new();
    for value in secrets {
        let value = value.trim();
        if !worth(value) {
            continue;
        }
        found.insert(value.to_string());
        if let Some((_, tail)) = value.split_once(':') {
            if !value.contains('\n') && worth(tail) {
                found.insert(tail.to_string());
            }
        }
    }
    found
}

struct Built {
    values: Vec<String>,
    matcher: Option<AhoCorasick>,
}

fn build(secrets: &[String]) -> Built {
    let mut vals: Vec<String> = values(secrets).into_iter().collect();
    vals.sort_by(|a, b| b.len().cmp(&a.len()));
    let mut forms = BTreeSet::new();
    for v in &vals {
        forms.extend(variants(v));
    }
    forms.remove("");
    let matcher = if forms.is_empty() {
        None
    } else {
        AhoCorasickBuilder::new().match_kind(MatchKind::LeftmostLongest).build(forms.iter()).ok()
    };
    Built { values: vals, matcher }
}

pub struct Redactor {
    inner: RwLock<Built>,
}

impl Redactor {
    pub fn new(secrets: &[String]) -> Redactor {
        Redactor { inner: RwLock::new(build(secrets)) }
    }

    pub fn is_empty(&self) -> bool {
        self.inner.read().unwrap().matcher.is_none()
    }

    pub fn values(&self) -> Vec<String> {
        self.inner.read().unwrap().values.clone()
    }

    pub fn add(&self, secrets: &[String]) {
        let mut inner = self.inner.write().unwrap();
        let fresh: Vec<String> = values(secrets).into_iter().filter(|v| !inner.values.contains(v)).collect();
        if fresh.is_empty() {
            return;
        }
        let mut all = inner.values.clone();
        all.extend(fresh);
        *inner = build(&all);
    }

    pub fn scrub_text(&self, text: &str) -> String {
        match &self.inner.read().unwrap().matcher {
            Some(m) => m.replace_all(text, &vec![MASK; m.patterns_len()]),
            None => text.to_string(),
        }
    }

    /// The same structure with every string scrubbed; keys are left as they are.
    pub fn scrub_json(&self, v: &Value) -> Value {
        match v {
            Value::String(s) => Value::String(self.scrub_text(s)),
            Value::Array(items) => Value::Array(items.iter().map(|i| self.scrub_json(i)).collect()),
            Value::Object(map) => Value::Object(map.iter().map(|(k, i)| (k.clone(), self.scrub_json(i))).collect()),
            other => other.clone(),
        }
    }

    /// Whether these bytes carry a secret in any of its forms (read as latin-1, like the Python check).
    pub fn holds(&self, data: &[u8]) -> bool {
        match &self.inner.read().unwrap().matcher {
            Some(m) => {
                let text: String = data.iter().map(|&b| b as char).collect();
                // Latin-1 widening keeps ASCII as is; the forms are UTF-8 strings, so search both.
                m.is_match(&text) || m.is_match(String::from_utf8_lossy(data).as_ref())
            }
            None => false,
        }
    }

    /// Scrub what a turn changed in the checkout at `root`: rewrite changed text files holding a secret,
    /// report binary or oversized ones, and whether a commit made since `since` carries one.
    pub fn scrub_tree(&self, root: &Path, since: &str) -> Tree {
        let mut result = Tree::default();
        if self.is_empty() || !root.join(".git").exists() {
            return result;
        }
        let changed = git(root, &["status", "--porcelain", "-z", "--untracked-files=all"]).unwrap_or_default();
        let text = String::from_utf8_lossy(&changed).to_string();
        for entry in text.split('\0') {
            if entry.len() > 3 && &entry[..2] != " D" && &entry[..2] != "D " {
                let name = entry[3..].rsplit(" -> ").next().unwrap_or_default();
                let path = root.join(name);
                let meta = std::fs::symlink_metadata(&path);
                match meta {
                    Ok(m) if m.is_file() && m.len() > TEXT_LIMIT => result.too_large.push(path),
                    Ok(m) if m.is_file() => match std::fs::read(&path) {
                        Ok(data) => {
                            if !self.holds(&data) {
                                continue;
                            }
                            if data.iter().take(8000).any(|&b| b == 0) {
                                result.left_out.push(path);
                                continue;
                            }
                            let scrubbed = self.scrub_text(&String::from_utf8_lossy(&data));
                            let tmp = path.with_file_name(format!(".tico-scrub-{}", uuid::Uuid::new_v4().simple()));
                            let ok = std::fs::write(&tmp, scrubbed.as_bytes())
                                .and_then(|_| std::fs::set_permissions(&tmp, m.permissions()))
                                .and_then(|_| std::fs::rename(&tmp, &path));
                            if ok.is_err() {
                                let _ = std::fs::remove_file(&tmp);
                                result.left_out.push(path);
                            } else {
                                result.rewritten.push(path);
                            }
                        }
                        Err(_) => result.left_out.push(path),
                    },
                    _ => {}
                }
            }
        }
        if !since.is_empty() {
            let range = format!("{since}..HEAD");
            if let Some(patch) = git(root, &["log", "-p", "--no-ext-diff", "--no-textconv", "--format=", &range]) {
                result.committed = !patch.is_empty() && self.holds(&patch);
            }
        }
        result
    }
}

#[derive(Default, Debug)]
pub struct Tree {
    pub rewritten: Vec<PathBuf>,
    pub left_out: Vec<PathBuf>,
    pub too_large: Vec<PathBuf>,
    pub committed: bool,
}

/// git with the clean environment `runner/safe_git.py` uses: no global or system config.
pub fn git(root: &Path, args: &[&str]) -> Option<Vec<u8>> {
    let out = Command::new("git")
        .arg("-c")
        .arg(format!("safe.directory={}", root.display()))
        .arg("-C")
        .arg(root)
        .args(args)
        .env_clear()
        .envs(crate::env::process_environment())
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_SYSTEM", "/dev/null")
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_OPTIONAL_LOCKS", "0")
        .stdin(std::process::Stdio::null())
        .output()
        .ok()?;
    out.status.success().then_some(out.stdout)
}

/// The checkout's current commit, or "" when it has none.
pub fn head(root: &Path) -> String {
    git(root, &["rev-parse", "--verify", "-q", "HEAD"]).map(|o| String::from_utf8_lossy(&o).trim().to_string()).unwrap_or_default()
}

/// The turn's redactor, or None when it holds nothing worth hiding: the granted values, any variable whose
/// name says it is a secret, and the GitHub tokens handed to the turn.
pub fn for_turn(env: &[(String, String)], vault_values: &[String]) -> Option<Arc<Redactor>> {
    let mut secrets: Vec<String> = vault_values.to_vec();
    for (k, v) in env {
        let upper = k.to_uppercase();
        if ["TOKEN", "SECRET", "PASSWORD", "API_KEY"].iter().any(|s| upper.contains(s)) {
            secrets.push(v.clone());
        }
        if k == "TICO_GITHUB_TOKENS" {
            if let Ok(Value::Array(groups)) = serde_json::from_str::<Value>(v) {
                for g in groups {
                    if let Some(t) = g.get("token").and_then(|t| t.as_str()) {
                        secrets.push(t.to_string());
                    }
                }
            }
        }
    }
    let r = Redactor::new(&secrets);
    (!r.is_empty()).then(|| Arc::new(r))
}

fn active() -> &'static Mutex<Vec<(String, Arc<Redactor>)>> {
    static ACTIVE: OnceLock<Mutex<Vec<(String, Arc<Redactor>)>>> = OnceLock::new();
    ACTIVE.get_or_init(|| Mutex::new(Vec::new()))
}

pub fn register(aid: &str, r: Arc<Redactor>) {
    active().lock().unwrap().push((aid.to_string(), r));
}

pub fn release(aid: &str) {
    active().lock().unwrap().retain(|(a, _)| a != aid);
}

/// A log line with every running turn's secrets taken out.
pub fn scrub_log(line: &str) -> String {
    let list: Vec<Arc<Redactor>> = active().lock().map(|l| l.iter().map(|(_, r)| r.clone()).collect()).unwrap_or_default();
    let mut out = line.to_string();
    for r in list {
        out = r.scrub_text(&out);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_secret_is_masked_in_every_form_and_short_or_common_values_are_not() {
        let r = Redactor::new(&["s3cr3t-value/x".into(), "short".into(), "password".into(), "user:hunter2hunter2".into()]);
        let b64 = base64::engine::general_purpose::STANDARD.encode("s3cr3t-value/x");
        let text = format!("a s3cr3t-value/x b {} c {} d hunter2hunter2 e short password", quote("s3cr3t-value/x"), b64);
        assert_eq!(r.scrub_text(&text), "a •••• b •••• c •••• d •••• e short password");
        assert!(Redactor::new(&["aaaaaaaaaaaa".into()]).is_empty(), "fewer than three distinct characters");
    }

    #[test]
    fn the_python_redactor_agrees() {
        let secrets = ["granted-file-secret-fixture", "Zm9vYmFyYmF6cXV4", "a:b c+d/e=fghij"];
        let sample = "x granted-file-secret-fixture y Z3JhbnRlZC1maWxlLXNlY3JldC1maXh0dXJl z a%3Ab%20c%2Bd%2Fe%3Dfghij w b c+d/e=fghij";
        let r = Redactor::new(&secrets.iter().map(|s| s.to_string()).collect::<Vec<_>>());
        let script = "import sys,json\nsys.path.insert(0,sys.argv[1])\nfrom runner.redact import Redactor\nprint(Redactor(json.loads(sys.argv[2])).scrub_text(sys.argv[3]))";
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let out = Command::new("python3")
            .args(["-c", script])
            .arg(repo)
            .arg(serde_json::to_string(&secrets).unwrap())
            .arg(sample)
            .output()
            .unwrap();
        assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
        assert_eq!(r.scrub_text(sample), String::from_utf8_lossy(&out.stdout).trim_end_matches('\n'));
    }
}
