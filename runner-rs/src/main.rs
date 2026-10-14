//! `tico-runner`: the Tico local runner, the chat path of `python -m runner` (step 1 of
//! _rust-runner-plan.md). Same registration file, state directory, lock and outbox, so a computer can switch
//! between the two engines and back.

mod client;
mod config;
mod declared_access;
mod env;
mod events;
mod execute;
mod files_publish;
mod gitcred;
mod hosts;
mod isolation;
mod lock;
mod mail_key;
mod manifest;
mod memory_history;
mod mcp;
mod op;
mod perbot;
mod prompt;
mod readiness;
mod redact;
mod runner;
mod safegit;
mod sidejobs;
mod signin;
mod state;
mod watchers;
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

fn fail(message: &str) -> ! {
    eprintln!("usage: tico-runner [--config CONFIG] {{run,status}}\ntico-runner: error: {message}");
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
    let config = config::Config::load(&path).unwrap_or_else(|e| fail(&e));
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
    // After a re-enrollment, the protected mail key follows this operator's previous registration once.
    mail_key::carry_protected(&config);
    let state_dir = config.state_dir();
    if let Err(e) = std::fs::create_dir_all(&state_dir) {
        fail(&format!("cannot create {}: {e}", state_dir.display()));
    }
    let _lock = lock::acquire(&state_dir.join("runner.lock")).unwrap_or_else(|e| fail(&e));
    let state = state::State::open(&state_dir).unwrap_or_else(|e| fail(&e));
    if isolation::enabled() {
        // Sign-ins a person ran as root (`docker exec`) go to the bot user, who runs the harnesses.
        let home = std::path::PathBuf::from(std::env::var("HOME").unwrap_or_default());
        isolation::adopt(&[".codex", ".claude", ".claude.json", ".gemini", ".config"].map(|p| home.join(p)));
    }
    mail_key::init(&config); // an inbox bot's turn asks the credential socket for its mailbox's token
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
    // No launchd here (TICO_SIDE_JOBS=1): the runner also supervises importers, close-calls and connectors.
    let side = sidejobs::start(&service.config);
    service.run().await;
    if let Some((task, stop)) = side {
        stop.notify_one();
        let _ = task.await;
    }
    0
}
