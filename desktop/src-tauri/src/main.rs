use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

struct EngineProcess(Mutex<Option<Child>>);

fn start_engine() -> Option<Child> {
    let mut root = std::env::current_dir().ok()?;
    while !root.join("pyproject.toml").exists() {
        if !root.pop() {
            return None;
        }
    }
    let mut cmd = Command::new("python");
    cmd.arg("-m")
        .arg("engine.app")
        .current_dir(root)
        .env("PYTHONPATH", ".")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    cmd.spawn().ok()
}

fn main() {
    tauri::Builder::default()
        .manage(EngineProcess(Mutex::new(start_engine())))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.try_state::<EngineProcess>() {
                    if let Ok(mut child) = state.0.lock() {
                        if let Some(process) = child.as_mut() {
                            let _ = process.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Trading Journal");
}
