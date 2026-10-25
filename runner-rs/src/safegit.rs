//! Git the runner itself runs in a bot's checkout (`runner/safe_git.py`): no supervisor secrets, no repository
//! hooks or fsmonitor program, no global or system config beyond the machine's credential and proxy settings.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use crate::env::Env;

/// An empty, read-only hooks directory, made once per process.
fn hooks() -> &'static Path {
    static DIR: OnceLock<PathBuf> = OnceLock::new();
    DIR.get_or_init(|| {
        let dir = std::env::temp_dir().join(format!("tico-empty-hooks-{}-{}", std::process::id(), uuid::Uuid::new_v4().simple()));
        let _ = std::fs::create_dir_all(&dir);
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o555));
        dir
    })
}

pub fn hooks_dir() -> &'static Path {
    hooks()
}

/// What every runner git command starts with (safe_git.PREFIX), for git outside a checkout.
pub fn prefix() -> Vec<String> {
    vec!["--no-optional-locks".into(), "-c".into(), format!("core.hooksPath={}", hooks().display()), "-c".into(), "core.fsmonitor=false".into()]
}

/// `git` with what every runner git command starts with (safe_git.PREFIX plus `safe.directory`), then `-C path`.
pub fn args(path: &Path) -> Vec<String> {
    vec![
        "--no-optional-locks".into(),
        "-c".into(),
        format!("core.hooksPath={}", hooks().display()),
        "-c".into(),
        "core.fsmonitor=false".into(),
        "-c".into(),
        format!("safe.directory={}", path.display()),
        "-C".into(),
        path.display().to_string(),
    ]
}

/// Process settings only, with Git's global and system config emptied (safe_git.clean_environment).
pub fn clean_environment(source: &Env) -> Env {
    let mut env: Env = source.iter().filter(|(k, _)| crate::env::SETTINGS.contains(&k.as_str()) || k.starts_with("LC_")).map(|(k, v)| (k.clone(), v.clone())).collect();
    env.insert("GIT_CONFIG_GLOBAL".into(), "/dev/null".into());
    env.insert("GIT_CONFIG_SYSTEM".into(), "/dev/null".into());
    env.insert("GIT_CONFIG_NOSYSTEM".into(), "1".into());
    env.insert("GIT_TERMINAL_PROMPT".into(), "0".into());
    env.insert("GIT_OPTIONAL_LOCKS".into(), "0".into());
    env
}

/// The clean environment plus the computer's own credential, URL-rewrite, SSH, proxy and identity settings from
/// system and global config, read without includes and outside every checkout (safe_git.machine_environment).
pub fn machine_environment(source: &Env) -> Env {
    let mut env = clean_environment(source);
    let mut trusted: Env = source.iter().filter(|(k, _)| crate::env::SETTINGS.contains(&k.as_str()) || k.starts_with("LC_")).map(|(k, v)| (k.clone(), v.clone())).collect();
    for key in ["GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"] {
        if let Some(v) = source.get(key) {
            trusted.insert(key.into(), v.clone());
        }
    }
    // The turn's `gh` shim is this binary: not the machine's GitHub sign-in, so out of PATH here.
    let me = std::env::current_exe().ok().and_then(|p| p.canonicalize().ok());
    let shim = |dir: &Path| me.is_some() && dir.join("gh").canonicalize().ok() == me;
    let dirs: Vec<PathBuf> = std::env::split_paths(&env.get("PATH").cloned().unwrap_or_default()).filter(|d| !shim(d)).collect();
    if let Ok(path) = std::env::join_paths(&dirs) {
        env.insert("PATH".into(), path.to_string_lossy().into_owned());
        trusted.insert("PATH".into(), path.to_string_lossy().into_owned());
    }
    let pattern = r"^(credential\..*|url\..*\.(insteadof|pushinsteadof)|core\.sshcommand|http\.(.*\.)?(proxy|sslcainfo)|user\.(name|email))$";
    let mut entries: Vec<(String, String)> = vec![];
    for scope in ["--system", "--global"] {
        let hooks = format!("core.hooksPath={}", hooks().display());
        let out = std::process::Command::new("git")
            .args(["--no-optional-locks", "-c", &hooks, "-c", "core.fsmonitor=false", "config", scope, "--no-includes", "--null", "--get-regexp", pattern])
            .current_dir("/")
            .env_clear()
            .envs(&trusted)
            .stdin(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .output();
        let Ok(out) = out else { continue };
        for entry in String::from_utf8_lossy(&out.stdout).split('\0') {
            if let Some((k, v)) = entry.split_once('\n') {
                entries.push((k.to_string(), v.to_string()));
            }
        }
    }
    let gh = dirs.iter().map(|d| d.join("gh")).find(|p| p.is_file());
    if let Some(gh) = gh {
        if !entries.iter().any(|(k, _)| k.eq_ignore_ascii_case("credential.https://github.com.helper")) {
            entries.push(("credential.https://github.com.helper".into(), format!("!{} auth git-credential", crate::gitcred::shell_quote(&gh.display().to_string()))));
        }
    }
    entries.insert(0, ("credential.helper".into(), String::new()));
    env.insert("GIT_CONFIG_COUNT".into(), entries.len().to_string());
    for (i, (k, v)) in entries.iter().enumerate() {
        env.insert(format!("GIT_CONFIG_KEY_{i}"), k.clone());
        env.insert(format!("GIT_CONFIG_VALUE_{i}"), v.clone());
    }
    let ssh = entries.iter().rev().find(|(k, _)| k.eq_ignore_ascii_case("core.sshcommand")).map(|(_, v)| v.clone()).unwrap_or_else(|| "ssh".into());
    env.insert("GIT_SSH_COMMAND".into(), ssh);
    env
}

/// The environment for runner git in a turn's checkout (safe_git.environment): a clean environment, then only
/// the turn's per-repository GitHub helper settings (its scoped GH_TOKEN, the helper, the socket), never its
/// vault grants or the supervisor's own secrets. A turn without helper settings gets the machine's.
pub fn environment(turn: &Env) -> Env {
    let mut env = if turn.contains_key("GIT_CONFIG_COUNT") { clean_environment(turn) } else { machine_environment(turn) };
    for (k, v) in turn {
        let keep = ["GH_TOKEN", "GITHUB_TOKEN", "GIT_CONFIG_COUNT", "GIT_SSH_COMMAND", "HUB_TOKEN", crate::gitcred::SOCKET_ENV].contains(&k.as_str())
            || k.starts_with("TICO_GITHUB_")
            || k.starts_with("GIT_CONFIG_KEY_")
            || k.starts_with("GIT_CONFIG_VALUE_");
        if keep {
            env.insert(k.clone(), v.clone());
        }
    }
    env.insert("GIT_TERMINAL_PROMPT".into(), "0".into());
    env.insert("GIT_OPTIONAL_LOCKS".into(), "0".into());
    env
}

/// A Gateway turn's own git: the model's, run as its leased user in a checkout the bot user and the shared group
/// can write. Like the runner's git it runs no repository-named program (hooks, fsmonitor), and it reads no config
/// a bot can write, nor `safe.directory = *`: its global config is `global`, a file the supervisor writes, owned by
/// the leased user `owner` so its cleanup removes it with the rest of its files. It trusts exactly `paths`.
/// Proxy, CA and default branch come only from a system config root owns and no group can write (trusted_system);
/// the shared HOME's ~/.gitconfig and ~/.config/git/config are any sibling bot's to write, and a proxy or CA bundle
/// from there would see the turn's GitHub token. The proxy and CA variables the supervisor set reach git unchanged.
/// The identity is the turn's GIT_COMMITTER_*/GIT_AUTHOR_* (as committing_environment), else the system's, else Tico's.
pub fn for_turn_user(env: &mut Env, paths: &[PathBuf], global: &Path, owner: Option<(u32, u32)>) -> std::io::Result<()> {
    let mut entries: Vec<(String, String)> = vec![];
    if let Some(system) = trusted_system(env) {
        let hooks = format!("core.hooksPath={}", hooks().display());
        let out = std::process::Command::new("git")
            .args(["--no-optional-locks", "-c", &hooks, "-c", "core.fsmonitor=false", "config", "--file"]).arg(&system)
            .args(["--no-includes", "--null", "--get-regexp", r"^(user\.(name|email)|init\.defaultbranch|http\.(.*\.)?(proxy|sslcainfo))$"])
            .current_dir("/").env_clear().env("PATH", env.get("PATH").map(String::as_str).unwrap_or("/usr/bin:/bin"))
            .env("GIT_CONFIG_NOSYSTEM", "1").env("GIT_CONFIG_GLOBAL", "/dev/null")
            .stdin(std::process::Stdio::null()).stderr(std::process::Stdio::null()).output();
        if let Ok(out) = out {
            for entry in String::from_utf8_lossy(&out.stdout).split('\0') {
                let Some((key, value)) = entry.split_once('\n') else { continue };
                if !value.contains('\n') { entries.push((key.to_string(), value.to_string())); }
            }
        }
    }
    let identity = committing_environment(env);
    for (key, var) in [("user.name", "GIT_COMMITTER_NAME"), ("user.email", "GIT_COMMITTER_EMAIL")] {
        let author = var.replace("COMMITTER", "AUTHOR");
        let set = [var, author.as_str()].iter().any(|v| env.get(*v).is_some_and(|x| !x.is_empty()));
        if set || !entries.iter().any(|(k, _)| k == key) {
            entries.retain(|(k, _)| k != key);
            entries.push((key.into(), identity[var].clone()));
        }
    }
    let quote = |v: &str| v.replace('\\', "\\\\").replace('"', "\\\"");
    let mut lines = String::new();
    for (key, value) in &entries {
        let Some((section, name)) = key.rsplit_once('.') else { continue };
        let section = match section.split_once('.') {
            Some((head, sub)) => format!("{head} \"{}\"", quote(sub)),
            None => section.to_string(),
        };
        lines.push_str(&format!("[{section}]\n\t{name} = \"{}\"\n", quote(value)));
    }
    let _ = std::fs::remove_file(global);
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut file = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o644).custom_flags(libc::O_NOFOLLOW).open(global)?;
        file.write_all(lines.as_bytes())?;
        if let Some((uid, gid)) = owner {
            use std::os::fd::AsRawFd;
            if unsafe { libc::fchown(file.as_raw_fd(), uid, gid) } != 0 { return Err(std::io::Error::last_os_error()); }
        }
    }
    env.insert("GIT_CONFIG_GLOBAL".into(), global.display().to_string());
    env.insert("GIT_CONFIG_SYSTEM".into(), "/dev/null".into());
    env.insert("GIT_CONFIG_NOSYSTEM".into(), "1".into());
    crate::gitcred::add_config(env, "core.hooksPath", "/dev/null");
    crate::gitcred::add_config(env, "core.fsmonitor", "false");
    crate::gitcred::trust_directories(env, paths);
    Ok(())
}

/// The system git config, if no bot can have written it: a regular file, not a link, that root owns and no group
/// or other user can write, in a directory likewise. Git's own `$GIT_CONFIG_SYSTEM`, else the image's /etc/gitconfig.
fn trusted_system(env: &Env) -> Option<PathBuf> {
    if env.get("GIT_CONFIG_NOSYSTEM").is_some_and(|v| !v.is_empty() && v != "0" && v != "false") { return None; }
    let path = PathBuf::from(env.get("GIT_CONFIG_SYSTEM").filter(|v| !v.is_empty()).map(String::as_str).unwrap_or("/etc/gitconfig"));
    use std::os::unix::fs::MetadataExt;
    let safe = |m: &std::fs::Metadata| m.uid() == 0 && m.mode() & 0o022 == 0;
    let file = std::fs::symlink_metadata(&path).ok()?;
    let parent = std::fs::symlink_metadata(path.parent()?).ok()?;
    (file.is_file() && safe(&file) && parent.is_dir() && safe(&parent)).then_some(path)
}

const IDENTITY: [&str; 4] = ["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"];

/// `environment()` for a rebase, merge or commit the runner makes (safe_git.committing_environment): the bot's
/// identity when the turn set one, else Tico's. A clean environment has none, and git then refuses ("unable to
/// auto-detect email address"), leaving the bot's unpushed commits stuck behind its remote.
pub fn committing_environment(turn: &Env) -> Env {
    let mut env = environment(turn);
    for key in IDENTITY {
        if let Some(v) = turn.get(key).filter(|v| !v.is_empty()) {
            env.insert(key.into(), v.clone());
        }
    }
    let pick = |env: &Env, key: &str, other: &str, fallback: &str| {
        env.get(key).filter(|v| !v.is_empty()).or_else(|| env.get(other).filter(|v| !v.is_empty())).cloned().unwrap_or_else(|| fallback.into())
    };
    let name = pick(&env, "GIT_COMMITTER_NAME", "GIT_AUTHOR_NAME", "Tico");
    let email = pick(&env, "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_EMAIL", "runner@bots.tico.invalid");
    env.entry("GIT_COMMITTER_NAME".into()).or_insert_with(|| name.clone());
    env.entry("GIT_COMMITTER_EMAIL".into()).or_insert_with(|| email.clone());
    env.entry("GIT_AUTHOR_NAME".into()).or_insert(name);
    env.entry("GIT_AUTHOR_EMAIL".into()).or_insert(email);
    env
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_turn_users_git_runs_no_repository_program_and_reads_no_wider_trust() {
        let dir = std::env::temp_dir().join(format!("tico-turn-git-{}", uuid::Uuid::new_v4().simple()));
        let (repo, home) = (dir.join("repo"), dir.join("home"));
        std::fs::create_dir_all(&home).unwrap();
        std::fs::write(home.join(".gitconfig"), "[safe]\n\tdirectory = *\n[user]\n\tname = Fixture\n\temail = fixture@example.invalid\n").unwrap();
        let mut env = Env::new();
        env.insert("HOME".into(), home.display().to_string());
        env.insert("PATH".into(), std::env::var("PATH").unwrap_or_default());
        let git = |env: &Env, args: &[&str]| std::process::Command::new("git").args(args).env_clear().envs(env).output().unwrap();
        assert!(git(&env, &["init", "-q", &repo.display().to_string()]).status.success());
        let mark = dir.join("ran");
        let hook = repo.join(".git/hooks/pre-commit");
        std::fs::write(&hook, format!("#!/bin/sh\ntouch '{}'\n", mark.display())).unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&hook, std::fs::Permissions::from_mode(0o755)).unwrap();
        let global = dir.join("turn.gitconfig");
        for_turn_user(&mut env, &[repo.clone()], &global, None).unwrap();
        let written = std::fs::read_to_string(&global).unwrap();
        assert!(!written.contains("Fixture") && !written.contains("safe"), "{written}");
        assert_eq!((env["GIT_CONFIG_NOSYSTEM"].as_str(), env["GIT_CONFIG_GLOBAL"].as_str()), ("1", global.to_str().unwrap()));
        let listed = git(&env, &["-C", &repo.display().to_string(), "config", "--get-all", "safe.directory"]);
        assert_eq!(String::from_utf8_lossy(&listed.stdout).trim(), repo.display().to_string());
        assert!(git(&env, &["-C", &repo.display().to_string(), "commit", "-q", "--allow-empty", "-m", "turn"]).status.success());
        assert!(!mark.exists(), "the repository's hook ran");
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_sibling_writable_gitconfig_gives_the_turn_user_no_proxy_or_ca() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("tico-turn-proxy-{}", uuid::Uuid::new_v4().simple()));
        let home = dir.join("home");
        std::fs::create_dir_all(home.join(".config/git")).unwrap();
        // Any bot can write the shared HOME (1770), so these are a sibling's: a proxy it runs and a CA bundle it made.
        let hostile = "[http]\n\tproxy = http://127.0.0.1:9\n\tsslCAInfo = /home/runner/sibling-ca.pem\n[http \"https://github.com/\"]\n\tproxy = http://127.0.0.1:9\n[user]\n\tname = Sibling\n";
        let system = dir.join("gitconfig");
        for file in [home.join(".gitconfig"), home.join(".config/git/config"), system.clone()] {
            std::fs::write(&file, hostile).unwrap();
            std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o664)).unwrap();
        }
        let mut env = Env::new();
        env.insert("HOME".into(), home.display().to_string());
        env.insert("XDG_CONFIG_HOME".into(), home.join(".config").display().to_string());
        env.insert("GIT_CONFIG_SYSTEM".into(), system.display().to_string()); // not root's, so not trusted either
        env.insert("PATH".into(), std::env::var("PATH").unwrap_or_default());
        env.insert("GIT_AUTHOR_NAME".into(), "Ops Bot".into());
        env.insert("GIT_AUTHOR_EMAIL".into(), "ops@bots.invalid".into());
        let global = dir.join("turn.gitconfig");
        for_turn_user(&mut env, &[dir.join("repo")], &global, None).unwrap();
        let written = std::fs::read_to_string(&global).unwrap();
        assert!(!written.to_lowercase().contains("proxy") && !written.to_lowercase().contains("sslcainfo") && !written.contains("Sibling"), "{written}");
        assert!(written.contains("Ops Bot") && written.contains("ops@bots.invalid"), "{written}");
        let listed = std::process::Command::new("git").args(["config", "--get-regexp", "^http\\."]).current_dir(&dir).env_clear().envs(&env).output().unwrap();
        assert_eq!(String::from_utf8_lossy(&listed.stdout), "", "the turn user's git sees a sibling's http settings");
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn runner_commits_carry_the_bots_identity_else_ticos() {
        let mut turn = Env::new();
        let bare = committing_environment(&turn);
        assert_eq!((bare["GIT_AUTHOR_NAME"].as_str(), bare["GIT_COMMITTER_EMAIL"].as_str()), ("Tico", "runner@bots.tico.invalid"));
        turn.insert("GIT_AUTHOR_NAME".into(), "Coo".into());
        turn.insert("GIT_AUTHOR_EMAIL".into(), "coo@bots.tico.invalid".into());
        let bot = committing_environment(&turn);
        assert_eq!((bot["GIT_COMMITTER_NAME"].as_str(), bot["GIT_COMMITTER_EMAIL"].as_str()), ("Coo", "coo@bots.tico.invalid"));
    }

    #[test]
    fn runner_git_keeps_the_turns_helper_and_drops_everything_else() {
        let mut turn = Env::new();
        for (k, v) in [
            ("PATH", "/usr/bin:/bin"),
            ("HOME", "/home/bot"),
            ("GH_TOKEN", "ghs_scoped"),
            ("GIT_CONFIG_COUNT", "1"),
            ("GIT_CONFIG_KEY_0", "credential.helper"),
            ("GIT_CONFIG_VALUE_0", "x"),
            ("OP_SERVICE_ACCOUNT_TOKEN", "machine-secret"),
            ("ACME_API_KEY", "granted"),
        ] {
            turn.insert(k.into(), v.into());
        }
        let env = environment(&turn);
        assert_eq!(env.get("GH_TOKEN").map(String::as_str), Some("ghs_scoped"));
        assert_eq!(env.get("GIT_CONFIG_GLOBAL").map(String::as_str), Some("/dev/null"));
        assert!(!env.contains_key("OP_SERVICE_ACCOUNT_TOKEN") && !env.contains_key("ACME_API_KEY"));
        let argv = args(Path::new("/x"));
        assert!(argv.contains(&"core.fsmonitor=false".to_string()) && argv.iter().any(|a| a.starts_with("core.hooksPath=")));
    }
}
