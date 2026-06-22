//! Launches the Python FastAPI sidecar and ties its lifetime to the app.
//!
//! - **Dev** (`cargo`/`tauri dev`): runs the project's venv interpreter against `sidecar.app:app`,
//!   with the DB in the project root for convenience.
//! - **Release** (bundled): runs the PyInstaller-built `phorrom-sidecar` binary that Tauri places
//!   next to the app executable (declared as `externalBin`), with the DB under the OS app-data dir
//!   so it's writable even when the app is installed in a read-only location.
//!
//! Both serve on 127.0.0.1:8008 (the port the frontend defaults to). If neither can be located,
//! we skip launching and the UI still loads (the user can run a sidecar manually).

use std::path::PathBuf;
use std::process::{Child, Command};

use tauri::{AppHandle, Manager};

const PORT: &str = "8008";

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

fn dev_python(root: &PathBuf) -> Option<PathBuf> {
    [
        root.join("sidecar").join(".venv").join("Scripts").join("python.exe"),
        root.join("sidecar").join(".venv").join("bin").join("python"),
    ]
    .into_iter()
    .find(|p| p.exists())
}

/// The bundled sidecar binary that Tauri copies next to the main executable.
fn bundled_sidecar() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let name = if cfg!(windows) { "phorrom-sidecar.exe" } else { "phorrom-sidecar" };
    let path = dir.join(name);
    path.exists().then_some(path)
}

fn no_window(cmd: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
}

/// Best-effort spawn of the sidecar. Returns the child handle if it started.
pub fn spawn(app: &AppHandle) -> Option<Child> {
    let db_path = app
        .path()
        .app_data_dir()
        .ok()
        .map(|d| {
            let _ = std::fs::create_dir_all(&d);
            d.join("phorrom.sqlite")
        });

    let mut cmd = if cfg!(debug_assertions) {
        // Dev: venv python + project root.
        let root = project_root();
        let py = match dev_python(&root) {
            Some(p) => p,
            None => {
                log::warn!("dev sidecar venv not found under {:?}; not launching", root);
                return None;
            }
        };
        let mut c = Command::new(py);
        c.args(["-m", "uvicorn", "sidecar.app:app", "--host", "127.0.0.1", "--port", PORT])
            .current_dir(&root)
            .env("PHORROM_DB_PATH", root.join("phorrom.sqlite"));
        c
    } else {
        // Release: bundled PyInstaller binary next to the app, DB under app-data.
        let bin = match bundled_sidecar() {
            Some(p) => p,
            None => {
                log::error!("bundled sidecar binary not found next to the app");
                return None;
            }
        };
        let mut c = Command::new(bin);
        c.env("PHORROM_PORT", PORT);
        if let Some(p) = &db_path {
            c.env("PHORROM_DB_PATH", p);
        }
        c
    };

    crate::secrets::inject_secrets(&mut cmd); // pass keychain-stored provider keys to the sidecar
    no_window(&mut cmd);
    match cmd.spawn() {
        Ok(child) => {
            log::info!("sidecar launched on http://127.0.0.1:{PORT}");
            Some(child)
        }
        Err(e) => {
            log::error!("failed to launch sidecar: {e}");
            None
        }
    }
}
