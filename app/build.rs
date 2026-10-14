fn main() {
    // The build-time identity (scripts/app.sh): a change must recompile config.rs.
    for key in ["TICO_HUB_URL", "TICO_APP_NAME", "TICO_ENV_SLUG", "TICO_LOCAL_TOKEN_FILE"] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    // Info.plist beside tauri.conf.json is merged into the bundle by tauri-build itself.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["bridge", "connect_server", "server_address"]),
    ))
    .expect("the app manifest could not be built");
}
