//! A bot's `bot.yaml` (older: `employee.yaml`), read as YAML into JSON values (clients/manifest.py and the
//! `yaml.safe_load` calls around it). One reader for readiness, watchers, MCP servers, declared tools and
//! the files a bot publishes.
//!
//! serde_norway reads YAML 1.2, PyYAML reads 1.1: `yes`/`no`/`on`/`off` stay strings here where Python reads
//! booleans. Every field this runner reads compares to `true`/`false` or text, so only a bot.yaml that writes
//! `enabled: no` for a watcher reads differently (here the watcher stays on).

use std::path::Path;

use serde_json::{Map, Value};

pub use crate::readiness::manifest_path;

fn convert(v: serde_norway::Value) -> Value {
    use serde_norway::Value as Y;
    match v {
        Y::Null => Value::Null,
        Y::Bool(b) => Value::Bool(b),
        Y::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::from(i)
            } else if let Some(u) = n.as_u64() {
                Value::from(u)
            } else {
                n.as_f64().and_then(serde_json::Number::from_f64).map(Value::Number).unwrap_or(Value::Null)
            }
        }
        Y::String(s) => Value::String(s),
        Y::Sequence(items) => Value::Array(items.into_iter().map(convert).collect()),
        Y::Mapping(m) => {
            let mut out = Map::new();
            for (k, v) in m {
                let key = match k {
                    Y::String(s) => s,
                    Y::Bool(b) => if b { "True" } else { "False" }.to_string(),
                    Y::Number(n) => n.to_string(),
                    Y::Null => "None".into(),
                    other => serde_json::to_string(&convert(other)).unwrap_or_default(),
                };
                out.insert(key, convert(v));
            }
            Value::Object(out)
        }
        Y::Tagged(t) => convert(t.value),
    }
}

/// The document as JSON: an empty file is `{}` (Python's `yaml.safe_load(...) or {}`).
pub fn parse(text: &str) -> Result<Value, String> {
    let doc: serde_norway::Value = serde_norway::from_str(text).map_err(|e| e.to_string())?;
    Ok(match convert(doc) {
        Value::Null => Value::Object(Map::new()),
        other => other,
    })
}

/// The folder's manifest, or None when it is missing or not YAML.
pub fn read(folder: &Path) -> Option<Value> {
    let text = std::fs::read_to_string(manifest_path(folder)).ok()?;
    parse(&text).ok()
}

/// The value under the new key, or the old key when the new one is absent (manifest.pick).
pub fn pick<'a>(manifest: &'a Value, new: &str, old: &str) -> Option<&'a Value> {
    let m = manifest.as_object()?;
    if m.contains_key(new) {
        m.get(new)
    } else {
        m.get(old)
    }
}

/// The declared tools: `tools:`, else the older `access:`.
pub fn tools_of(manifest: &Value) -> Value {
    pick(manifest, "tools", "access").cloned().unwrap_or(Value::Null)
}

/// Python's `str(value)` for a scalar: text as is, `True`/`False`, `None`, numbers as written.
pub fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(b) => if *b { "True" } else { "False" }.into(),
        Value::Null => "None".into(),
        Value::Number(n) => {
            if n.is_f64() {
                let f = n.as_f64().unwrap_or(0.0);
                if f.fract() == 0.0 && f.abs() < 1e16 { format!("{f:.1}") } else { f.to_string() }
            } else {
                n.to_string()
            }
        }
        other => crate::util::py_dumps(other),
    }
}

/// Python truthiness of `value or ""` followed by `str()`: "" for a falsy value.
pub fn text_or_empty(v: Option<&Value>) -> String {
    if crate::util::truthy(v) {
        py_str(v.unwrap())
    } else {
        String::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn yaml_reads_into_json_with_the_old_names_as_fallbacks() {
        let doc = parse("name: ops\nmodel: \"x\"  # c\nwatchers:\n  - name: a\n    every: 5m\n    enabled: false\naccess:\n  - {service: board, can: [read]}\n").unwrap();
        assert_eq!(doc["name"], "ops");
        assert_eq!(doc["watchers"][0]["enabled"], false);
        assert_eq!(tools_of(&doc), json!([{"service": "board", "can": ["read"]}]));
        assert_eq!(parse("").unwrap(), json!({}));
        assert!(parse("a: [1,").is_err());
        assert_eq!(parse("1: x\ntrue: y\n").unwrap(), json!({"1": "x", "True": "y"}));
        assert_eq!(py_str(&json!(1.0)), "1.0");
        assert_eq!(py_str(&json!(5)), "5");
    }
}
