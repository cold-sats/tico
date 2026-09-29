//! What this build of the app points at. One source builds every company's app: the hub URL, the
//! name and the environment come in at build time (`scripts/app.sh` sets `TICO_*` for cargo) and
//! `HUB_URL` in the process environment overrides the URL for a developer run.

use url::Url;

#[derive(Clone, Debug)]
pub struct Config {
    pub hub: Url,
    pub app_name: String,
    /// Set on a per-environment build only: the environment this app belongs to.
    #[allow(dead_code)]
    pub environment: Option<String>,
    /// A local server has no browser sign-in: the file holding that server's owner token.
    pub local_token_file: Option<String>,
}

impl Config {
    pub fn load() -> Config {
        let raw = std::env::var("HUB_URL")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .or_else(|| option_env!("TICO_HUB_URL").map(str::to_string))
            .unwrap_or_else(|| "http://localhost:8765/".to_string());
        let mut hub = Url::parse(&raw).unwrap_or_else(|_| Url::parse("http://localhost:8765/").unwrap());
        if !hub.path().ends_with('/') {
            let path = format!("{}/", hub.path());
            hub.set_path(&path);
        }
        Config {
            hub,
            app_name: option_env!("TICO_APP_NAME").unwrap_or("Tico").to_string(),
            environment: option_env!("TICO_ENV_SLUG").map(str::to_string).filter(|s| !s.is_empty()),
            local_token_file: option_env!("TICO_LOCAL_TOKEN_FILE").map(str::to_string).filter(|s| !s.is_empty()),
        }
    }

    /// A build that points at localhost talks to a server on this machine; a build that points at
    /// a public hostname is a copy from a shared server, which must never tell anyone to run
    /// server commands.
    pub fn is_local(&self) -> bool {
        matches!(self.hub.host_str(), Some("localhost") | Some("127.0.0.1"))
    }

    pub fn host(&self) -> String {
        self.hub.host_str().unwrap_or("").to_string()
    }

    pub fn api(&self, path: &str) -> Url {
        self.hub.join(&format!("api/{}", path.trim_start_matches('/'))).unwrap()
    }

    /// The page to open. A local server has no browser sign-in, so the app reads the owner token
    /// from the environment directory and trades it for a session cookie: the server sets the
    /// cookie and redirects to `next`. Read on every load, so a rotated token is picked up without
    /// rebuilding the app, and never kept in the bundle.
    pub fn start_url(&self) -> Url {
        if !self.is_local() {
            return self.hub.clone();
        }
        let Some(file) = &self.local_token_file else { return self.hub.clone() };
        let Ok(contents) = std::fs::read_to_string(file) else { return self.hub.clone() };
        let token = contents.trim();
        if token.is_empty() {
            return self.hub.clone();
        }
        let mut url = self.hub.join("api/v2/local-signin").unwrap();
        url.query_pairs_mut().append_pair("token", token).append_pair("next", "/");
        url
    }
}
