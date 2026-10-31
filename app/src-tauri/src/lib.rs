mod supervisor;
use std::path::PathBuf;
use std::sync::Arc;
use supervisor::{Connection, Launch, Supervisor};
use tauri::{Emitter, Manager, State};

struct Core(Arc<Supervisor>);

#[tauri::command]
async fn core_connection(core: State<'_, Core>) -> Result<Connection, String> {
    let supervisor = core.0.clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.connection())
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
fn core_restart(core: State<'_, Core>) -> Result<(), String> {
    core.0.restart()
}
#[tauri::command]
fn diagnostics(app: tauri::AppHandle) -> Result<String, String> {
    let log = app
        .path()
        .app_log_dir()
        .map_err(|e| e.to_string())?
        .join("shell.log");
    let text = std::fs::read_to_string(&log).unwrap_or_default();
    let mut lines = text.lines().rev().take(200).collect::<Vec<_>>();
    lines.reverse();
    let body = lines.join("\n");
    let secrets = regex::Regex::new(
        r#"(?i)(bearer\s+|(?:api[_-]?key|token|password|secret)[\s\"':=]+)[^\s\",;}]+"#,
    )
    .unwrap();
    Ok(format!(
        "badshop {}\nOS: {} {}\nLog: {}\n\n{}",
        env!("CARGO_PKG_VERSION"),
        std::env::consts::OS,
        std::env::consts::ARCH,
        log.display(),
        secrets.replace_all(&body, "${1}[REDACTED]")
    ))
}

fn launch(app: &tauri::AppHandle) -> Result<Launch, Box<dyn std::error::Error>> {
    let resource = app.path().resource_dir()?;
    let executable = if cfg!(windows) {
        "badshop-core.exe"
    } else {
        "badshop-core"
    };
    let bundled = resource
        .join("core-dist")
        .join("badshop-core")
        .join(executable);
    let log_path = app.path().app_log_dir()?.join("shell.log");
    if bundled.is_file() {
        return Ok(Launch {
            program: bundled,
            args: vec!["serve".into()],
            log_path,
        });
    }
    if cfg!(debug_assertions) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("core");
        let program = std::env::var_os("BADSHOP_UV")
            .map(PathBuf::from)
            .unwrap_or_else(|| "uv".into());
        return Ok(Launch {
            program,
            args: vec![
                "run".into(),
                "--project".into(),
                root.to_string_lossy().into(),
                "badshop-core".into(),
                "serve".into(),
            ],
            log_path,
        });
    }
    // Let the supervisor report a visible startup failure instead of aborting the window.
    Ok(Launch {
        program: bundled,
        args: vec!["serve".into()],
        log_path,
    })
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            core_connection,
            core_restart,
            diagnostics
        ])
        .setup(|app| {
            let config = launch(app.handle())?;
            let handle = app.handle().clone();
            let supervisor = Supervisor::start(config, move |status| {
                let _ = handle.emit("core-status", status);
            });
            app.manage(Core(Arc::new(supervisor)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("can't initialize badshop desktop")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::ExitRequested { .. }) {
                app.state::<Core>().0.stop();
            }
        });
}
