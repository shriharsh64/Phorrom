mod sidecar;

use std::process::Child;
use std::sync::Mutex;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      // Launch the Python sidecar and keep its handle so we can stop it on exit.
      let child = sidecar::spawn(app.handle());
      app.manage(Mutex::new(child));
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app_handle, event| {
      // On exit, terminate the sidecar so it doesn't outlive the app.
      if let tauri::RunEvent::ExitRequested { .. } = event {
        if let Some(state) = app_handle.try_state::<Mutex<Option<Child>>>() {
          if let Ok(mut guard) = state.lock() {
            if let Some(child) = guard.as_mut() {
              let _ = child.kill();
            }
          }
        }
      }
    });
}
