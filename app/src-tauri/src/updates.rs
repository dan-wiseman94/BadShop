use serde::Serialize;
use std::{
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};
use tauri::{async_runtime::Mutex, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Default)]
pub struct Updates {
    pending: Mutex<Option<(Update, Option<Vec<u8>>)>>,
    pub restarting: AtomicBool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    current_version: String,
    version: Option<String>,
    notes: Option<String>,
    unavailable: Option<String>,
}

#[tauri::command]
pub async fn update_check(
    app: tauri::AppHandle,
    state: State<'_, Updates>,
) -> Result<UpdateInfo, String> {
    let mut pending = state
        .pending
        .try_lock()
        .map_err(|_| "An update operation is already running")?;
    let mut info = UpdateInfo {
        current_version: app.package_info().version.to_string(),
        version: None,
        notes: None,
        unavailable: None,
    };
    let key = option_env!("BADSHOP_UPDATER_PUBLIC_KEY").unwrap_or("");
    info.unavailable = if cfg!(debug_assertions) {
        Some(
            "Development builds do not self-update. Install a release build to receive updates."
                .into(),
        )
    } else if key.trim().is_empty() {
        Some(
            "This build has no update signing key configured. Install the latest release manually."
                .into(),
        )
    } else {
        None
    };
    #[cfg(target_os = "linux")]
    if !cfg!(debug_assertions) && app.env().appimage.is_none() {
        info.unavailable = Some("Update this installation using your package manager or install the latest download. In-app Linux updates require the AppImage.".into());
    }
    *pending = None;
    if info.unavailable.is_some() {
        return Ok(info);
    }
    let handle = app.clone();
    let update = app
        .updater_builder()
        .pubkey(key.trim())
        .endpoints(vec![
            "https://github.com/dan-wiseman94/BadShop/releases/latest/download/latest.json"
                .parse()
                .unwrap(),
        ])
        .map_err(|e| e.to_string())?
        .timeout(Duration::from_secs(30))
        .on_before_exit(move || {
            handle.state::<super::Core>().0.stop();
        })
        .build()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;
    if let Some(mut update) = update {
        // The frozen core makes these large downloads; the feed check stays bounded separately.
        update.timeout = Some(Duration::from_secs(15 * 60));
        info.version = Some(update.version.clone());
        info.notes = update.body.clone();
        *pending = Some((update, None));
    }
    Ok(info)
}

#[tauri::command]
pub async fn update_download(
    app: tauri::AppHandle,
    state: State<'_, Updates>,
) -> Result<(), String> {
    let mut pending = state
        .pending
        .try_lock()
        .map_err(|_| "An update operation is already running")?;
    let (update, bytes) = pending.as_mut().ok_or("Check for updates first")?;
    if bytes.is_some() {
        return Ok(());
    }
    let mut downloaded = 0;
    *bytes = Some(
        update
            .download(
                |chunk, total| {
                    downloaded += chunk;
                    let _ = app.emit(
                        "update-progress",
                        serde_json::json!({"downloaded": downloaded, "total": total}),
                    );
                },
                || {},
            )
            .await
            .map_err(|e| e.to_string())?,
    );
    Ok(())
}

#[tauri::command]
pub async fn update_install(
    app: tauri::AppHandle,
    state: State<'_, Updates>,
) -> Result<(), String> {
    let mut pending = state
        .pending
        .try_lock()
        .map_err(|_| "An update operation is already running")?;
    let (update, bytes) = pending.as_mut().ok_or("Check for updates first")?;
    if let Err(error) = update.install(bytes.as_ref().ok_or("Download the update first")?) {
        // Windows can reject launching the installer after its before-exit hook ran.
        #[cfg(windows)]
        if app.state::<super::Core>().0.current_connection().is_none() {
            app.unmanage::<super::Core>();
            super::start_core(&app).map_err(|e| format!("{error}; could not restart core: {e}"))?;
        }
        return Err(error.to_string());
    }
    app.state::<super::Core>().0.stop();
    state.restarting.store(true, Ordering::SeqCst);
    app.restart();
}
