//! Launches the bundled Python FastAPI sidecar and ties its lifetime to the app.
//!
//! In development we run the project's venv interpreter against `sidecar.app:app` on the port
//! the frontend defaults to (127.0.0.1:8008). If the venv isn't found (e.g. a packaged build
//! without a bundled interpreter yet), we skip spawning and let the user run the sidecar
//! manually — the UI still loads and points at the same port.

use std::path::PathBuf;
use std::process::{Child, Command};

/// Project root = the parent of `src-tauri` (where this crate's manifest lives) in dev.
fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

/// First existing venv Python under the project (Windows or *nix layout).
fn python_path(root: &PathBuf) -> Option<PathBuf> {
    let candidates = [
        root.join("sidecar").join(".venv").join("Scripts").join("python.exe"),
        root.join("sidecar").join(".venv").join("bin").join("python"),
    ];
    candidates.into_iter().find(|p| p.exists())
}

/// Best-effort spawn of the sidecar. Returns the child handle if it started.
pub fn spawn() -> Option<Child> {
    let root = project_root();
    let py = match python_path(&root) {
        Some(p) => p,
        None => {
            log::warn!("sidecar venv not found under {:?}; not launching it", root);
            return None;
        }
    };

    let mut cmd = Command::new(py);
    cmd.args([
        "-m", "uvicorn", "sidecar.app:app",
        "--host", "127.0.0.1", "--port", "8008",
    ])
    .current_dir(&root)
    .env("PHORROM_DB_PATH", root.join("phorrom.sqlite"));

    // Don't pop a console window on Windows.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => {
            log::info!("sidecar launched on http://127.0.0.1:8008");
            Some(child)
        }
        Err(e) => {
            log::error!("failed to launch sidecar: {e}");
            None
        }
    }
}
