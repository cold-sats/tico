//! What the shell asks the hub itself: the status line and what needs a person. The web view and
//! this client have separate cookie stores; remote builds copy only the cookies that belong to the
//! hub into each request, so the tray shares the signed-in Cloudflare Access session without
//! persisting or exposing it elsewhere.

use serde_json::Value;
use tauri::{AppHandle, Manager, Runtime};
use url::Url;

use crate::config::Config;

#[derive(Clone, Debug, Default)]
pub struct HubStatus {
    pub reachable: bool,
    pub alive: bool,
    pub cloud: bool,
    pub running: usize,
    pub needs: usize,
    pub tick_age: Option<i64>,
}

impl HubStatus {
    pub fn headline(&self) -> String {
        if !self.reachable {
            return "Hub server unreachable".into();
        }
        match (self.cloud, self.alive) {
            (true, true) => "Cloud backend connected".into(),
            (true, false) => "Cloud backend unavailable".into(),
            (false, true) => format!("Dispatcher running · tick {}s ago", self.tick_age.unwrap_or(0)),
            (false, false) => "Dispatcher STOPPED".into(),
        }
    }
}

pub struct Client {
    config: Config,
    http: reqwest::Client,
}

impl Client {
    pub fn new(config: Config) -> Client {
        let http = reqwest::Client::builder().timeout(std::time::Duration::from_secs(30)).build().unwrap();
        Client { config, http }
    }

    fn cookie_header<R: Runtime>(&self, app: &AppHandle<R>, url: &Url) -> Option<String> {
        if self.config.is_local() {
            return None;
        }
        let webview = app.get_webview_window("main")?;
        let cookies = webview.cookies_for_url(url.clone()).ok()?;
        let header = cookies.iter().map(|c| format!("{}={}", c.name(), c.value())).collect::<Vec<_>>().join("; ");
        (!header.is_empty()).then_some(header)
    }

    async fn get<R: Runtime>(&self, app: &AppHandle<R>, url: Url) -> Option<Value> {
        let mut request = self.http.get(url.clone());
        if let Some(cookie) = self.cookie_header(app, &url) {
            request = request.header("Cookie", cookie);
        }
        let response = request.send().await.ok()?;
        if !response.status().is_success() {
            return None;
        }
        response.json().await.ok()
    }

    pub async fn status<R: Runtime>(&self, app: &AppHandle<R>) -> HubStatus {
        let mut status = HubStatus::default();
        if let Some(st) = self.get(app, self.config.api("status")).await {
            status.reachable = true;
            status.cloud = st.get("cloud").and_then(Value::as_bool).unwrap_or(false);
            status.alive = status.cloud || st.get("dispatcher_alive").and_then(Value::as_bool).unwrap_or(false);
            status.running = st.get("active").and_then(Value::as_array).map(Vec::len).unwrap_or(0);
            status.tick_age = st.get("tick_age_s").and_then(Value::as_i64);
        }
        // The tray shows only the number: `count=1` answers with it instead of the full list
        // (over 100 KB every 30 s). An older hub ignores the query and sends the items.
        let needs = if status.cloud { self.config.api("v2/needs-you?count=1") } else { self.config.api("issues?needs_human=1") };
        if let Some(value) = self.get(app, needs).await {
            status.needs = if status.cloud {
                value.get("count").and_then(Value::as_u64).map(|n| n as usize)
                    .or_else(|| value.get("items").and_then(Value::as_array).map(Vec::len)).unwrap_or(0)
            } else {
                value.as_array().map(Vec::len).unwrap_or(0)
            };
        }
        status
    }
}
