use serde::{Deserialize, Serialize};
use std::{
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};
use tauri::{async_runtime::Mutex, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum UpdateTrack {
    Stable,
    Nightly,
}

impl UpdateTrack {
    fn endpoint(self) -> &'static str {
        match self {
            Self::Stable => {
                "https://github.com/dan-wiseman94/BadShop/releases/latest/download/latest.json"
            }
            Self::Nightly => {
                "https://github.com/dan-wiseman94/BadShop/releases/download/nightly/latest.json"
            }
        }
    }

    fn accepts(self, current_nightly: bool, remote_nightly: bool, newer: bool) -> bool {
        match self {
            Self::Stable => !remote_nightly && (current_nightly || newer),
            Self::Nightly => remote_nightly && (!current_nightly || newer),
        }
    }
}

#[derive(Default)]
pub struct Updates {
    pending: Mutex<Option<(Update, Option<Vec<u8>>)>>,
    pub restarting: AtomicBool,
    cancellation: super::update_policy::Cancellation,
}

#[tauri::command]
pub fn update_cancel(state: State<'_, Updates>) {
    state.cancellation.cancel();
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
    track: UpdateTrack,
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
    let generation = state.cancellation.generation();
    let connection = app
        .state::<super::Core>()
        .0
        .current_connection()
        .ok_or("Core is reconnecting")?;
    let handle = app.clone();
    let update = super::update_policy::run(
        connection.port,
        &connection.token,
        &state.cancellation,
        generation,
        async {
            app.updater_builder()
                .pubkey(key.trim())
                .version_comparator(move |current, remote| {
                    track.accepts(
                        current.pre.as_str().starts_with("nightly."),
                        remote.version.pre.as_str().starts_with("nightly."),
                        remote.version > current,
                    )
                })
                .endpoints(vec![track.endpoint().parse().unwrap()])
                .map_err(|e| e.to_string())?
                .timeout(Duration::from_secs(30))
                .on_before_exit(move || {
                    handle.state::<super::Core>().0.stop();
                })
                .build()
                .map_err(|e| e.to_string())?
                .check()
                .await
                .map_err(|e| e.to_string())
        },
    )
    .await?;
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
    let generation = state.cancellation.generation();
    let connection = app
        .state::<super::Core>()
        .0
        .current_connection()
        .ok_or("Core is reconnecting")?;
    *bytes = Some(
        super::update_policy::run(
            connection.port,
            &connection.token,
            &state.cancellation,
            generation,
            async {
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
                    .map_err(|e| e.to_string())
            },
        )
        .await?,
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

#[cfg(test)]
mod tests {
    use super::UpdateTrack;

    #[test]
    fn tracks_allow_explicit_switches_but_never_offer_the_other_feed() {
        assert!(UpdateTrack::Nightly.accepts(false, true, false));
        assert!(UpdateTrack::Stable.accepts(true, false, false));
        assert!(!UpdateTrack::Stable.accepts(false, true, true));
        assert!(!UpdateTrack::Nightly.accepts(true, false, true));
        assert!(!UpdateTrack::Nightly.accepts(true, true, false));
        assert!(!UpdateTrack::Stable.accepts(false, false, false));
        assert!(UpdateTrack::Nightly.accepts(true, true, true));
        assert!(UpdateTrack::Stable.accepts(false, false, true));
        assert_ne!(
            UpdateTrack::Nightly.endpoint(),
            UpdateTrack::Stable.endpoint()
        );
        assert!(serde_json::from_str::<UpdateTrack>("\"unknown\"").is_err());
    }
}
