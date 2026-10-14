//! `tico-runner`: the Tico local runner, the chat path of `python -m runner` (step 1 of
//! _rust-runner-plan.md). Same registration file, state directory, lock and outbox, so a computer can switch
//! between the two engines and back.

// A turn's failure carries its whole report, and the caches key on tuples: both read better as they are.
#![allow(clippy::result_large_err, clippy::type_complexity)]

mod client;
mod config;
mod credential_imports;
mod env;
mod events;
mod drive;
mod execute;
mod fallback;
mod gitcred;
mod harness_tools;
mod goals;
mod hosts;
mod lanes;
mod lock;
mod login;
mod profiles;
mod prompt;
mod readiness;
mod readiness_extra;
mod redact;
mod relays;
mod runner;
mod safegit;
mod signin;
mod state;
mod subscription_refresh;
mod util;

use std::path::PathBuf;
use std::sync::Arc;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "tico-runner", about = "Run this computer's Tico bots: the Rust runner", version = runner::RUNNER_VERSION)]
struct Cli {
    /// The registration file `python -m runner enroll` wrote.
    #[arg(long, global = true)]
    config: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Claim and run this computer's turns until stopped.
    Run,
    /// Print this registration's assignments and eligible bots.
    Status,
    /// Subscription profiles: one provider login per directory.
    Profile {
        #[command(subcommand)]
        action: ProfileAction,
    },
    /// Git's credential helper for one turn (git runs it; not for people).
    GitCredential {
        #[arg(long)]
        socket: Option<String>,
        #[arg(long)]
        bot: Option<String>,
        /// git's verb: only `get` answers.
        action: Option<String>,
    },
}

#[derive(Subcommand)]
enum ProfileAction {
    /// Make a profile (the first one added is the default).
    Add {
        name: String,
        /// Use the operator's own logins.
        #[arg(long)]
        share_operator: bool,
    },
    /// Print the profiles, the default and each bot's.
    List,
    /// Sign a profile in to one runtime, interactively.
    Login { name: String, runtime: String },
    /// Run a bot on a profile here.
    Assign { bot: String, name: String },
}

/// `profile add|list|assign|login` (runner/__main__.py profile_command): local to this computer, no network.
fn profile_main(action: ProfileAction, config: &mut config::Config) -> i32 {
    let result = match action {
        ProfileAction::Add { name, share_operator } => profiles::command(config, "add", Some(&name), share_operator, None),
        ProfileAction::List => profiles::command(config, "list", None, false, None),
        ProfileAction::Assign { bot, name } => profiles::command(config, "assign", Some(&name), false, Some(&bot)),
        ProfileAction::Login { name, runtime } => {
            if !profiles::RUNTIMES.contains(&runtime.as_str()) {
                fail(&format!("argument runtime: invalid choice: '{runtime}' (choose from {})", profiles::RUNTIMES.join(", ")));
            }
            let entry = config.data.get("profiles").and_then(|p| p.get(&name)).filter(|e| util::truthy(Some(e))).cloned();
            let Some(entry) = entry else { fail("No such profile on this registration; add it with `profile add`") };
            let profile = profiles::Profile::new(&name, &util::text_of(&entry["dir"]), util::truthy(entry.get("share_operator")));
            if profile.share_operator {
                fail(&format!("Profile {name} shares the operator's own logins; sign in normally"));
            }
            let home = profile.home(&runtime).unwrap_or_default();
            if runtime == "gemini" {
                let secrets = config.projects_dir().join("secrets");
                println!("Gemini CLI authenticates with an API key, not an interactive login: put GEMINI_API_KEY in {}/_shared.env or <bot>.env. This profile's Gemini sessions live in {}.", secrets.display(), home.display());
                return 0;
            }
            let command = profiles::login_command(&runtime).unwrap_or(&[]);
            if command.is_empty() || env::which(command[0], &std::env::var("PATH").unwrap_or_default()).is_none() {
                fail(&format!("{} is not on PATH", command.first().unwrap_or(&runtime.as_str())));
            }
            println!("Signing in to {runtime} for profile {name} in {}", home.display());
            // Interactive on purpose: the CLI owns the browser flow and prints its own instructions.
            let status = std::process::Command::new(command[0])
                .args(&command[1..])
                .env_clear()
                .envs(profile.environment(&runtime, &std::env::vars().collect()))
                .status();
            return status.ok().and_then(|s| s.code()).unwrap_or(1);
        }
    };
    match result {
        Ok(text) => {
            println!("{text}");
            0
        }
        Err(e) => fail(&e),
    }
}

fn fail(message: &str) -> ! {
    eprintln!("usage: tico-runner [--config CONFIG] {{run,status,profile}}\ntico-runner: error: {message}");
    std::process::exit(2)
}

fn main() {
    // A turn's `gh` is this binary under that name (gitcred::shim_dir).
    let argv: Vec<String> = std::env::args().collect();
    if argv.first().and_then(|a| std::path::Path::new(a).file_name()).is_some_and(|n| n == "gh") {
        std::process::exit(gitcred::gh_main(argv[1..].to_vec()));
    }
    let cli = Cli::parse();
    if let Command::GitCredential { socket, action, .. } = &cli.command {
        if action.as_deref().is_some_and(|a| a != "get") {
            std::process::exit(0);
        }
        std::process::exit(gitcred::git_credential_main(socket.clone()));
    }
    util::start_clock();
    let path = cli.config.unwrap_or_else(|| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".config/tico/runner.json"));
    let mut config = config::Config::load(&path).unwrap_or_else(|e| fail(&e));
    if let Command::Profile { action } = cli.command {
        std::process::exit(profile_main(action, &mut config));
    }
    if let Command::Run = cli.command {
        // Puts the tools bin on PATH, so it runs before any thread reads the environment.
        harness_tools::init(&config);
    }
    let rt = tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build().expect("tokio runtime");
    std::process::exit(rt.block_on(async move { start(cli.command, config).await }));
}

async fn start(command: Command, config: config::Config) -> i32 {
    let client = client::Client::new(&config.url(), &config.token(), 10, 1).unwrap_or_else(|e| fail(&e));
    if let Command::Status = command {
        let read = async { Ok::<_, client::ApiError>((client.get("runners/assignments").await?, client.get("runners/eligible").await?)) };
        return match read.await {
            Ok((assignments, eligible)) => {
                let out = serde_json::json!({"runner_id": config.runner_id(), "assignments": assignments, "eligible": eligible});
                println!("{}", serde_json::to_string_pretty(&out).unwrap_or_default());
                0
            }
            Err(e) => {
                eprintln!("tico-runner: {}", runner::describe(&e));
                1
            }
        };
    }
    let state_dir = config.state_dir();
    if let Err(e) = std::fs::create_dir_all(&state_dir) {
        fail(&format!("cannot create {}: {e}", state_dir.display()));
    }
    let _lock = lock::acquire(&state_dir.join("runner.lock")).unwrap_or_else(|e| fail(&e));
    let state = state::State::open(&state_dir).unwrap_or_else(|e| fail(&e));
    if let Some(line) = runner::local_refusal() {
        util::log(&format!("Tico runner: {line}; this runner does not do that yet"));
        util::log("Tico runner: not starting: run this computer on the Python runner (python -m runner run)");
        return 3;
    }
    let mut service = runner::Runner::new(config, client.clone(), state);
    match service.refusals().await {
        Ok(lines) if !lines.is_empty() => {
            for line in &lines {
                util::log(&format!("Tico runner: {line}; this runner does not do that yet"));
            }
            util::log("Tico runner: not starting: run this computer on the Python runner (python -m runner run) until those bots move or the Rust runner supports them");
            return 3;
        }
        Ok(_) => {}
        // An unreachable hub is not a reason to stay down: the loop retries, and readiness names any gap.
        Err(e) => util::log(&format!("Tico runner: could not read this computer's bots ({}); starting anyway", runner::describe(&e))),
    }
    match gitcred::CredentialSocket::serve(client.clone(), service.tokens.clone()) {
        Ok(socket) => service.socket = Some(socket),
        Err(e) => util::log(&format!("Tico runner: credential socket unavailable ({e}); turns use per-turn GitHub tokens")),
    }
    let service = Arc::new(service);
    let stopper = service.clone();
    tokio::spawn(async move {
        use tokio::signal::unix::{signal, SignalKind};
        let mut term = signal(SignalKind::terminate()).expect("SIGTERM handler");
        let mut int = signal(SignalKind::interrupt()).expect("SIGINT handler");
        tokio::select! { _ = term.recv() => {}, _ = int.recv() => {} }
        stopper.stop.store(true, std::sync::atomic::Ordering::SeqCst);
        stopper.events.wake.notify_one();
    });
    util::log(&format!("Tico runner {} (rust) started for {}", runner::RUNNER_VERSION, service.config.runner_id()));
    service.run().await;
    0
}
