fn main() {
    // The build-time identity (scripts/app.sh): a change must recompile config.rs.
    for key in ["TICO_HUB_URL", "TICO_APP_NAME", "TICO_ENV_SLUG", "TICO_LOCAL_TOKEN_FILE", "TICO_TRAY_LABEL"] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    if let Ok(label) = std::env::var("TICO_TRAY_LABEL") {
        assert!(label.len() <= 4 && label.bytes().all(|c| c.is_ascii_alphanumeric()),
            "TICO_TRAY_LABEL must be empty or 1-4 ASCII letters/digits");
    }
    // Info.plist beside tauri.conf.json is merged into the bundle by tauri-build itself.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["bridge", "connect_server", "server_address"]),
    ))
    .expect("the app manifest could not be built");
}
