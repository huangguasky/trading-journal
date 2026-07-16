use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::{process::CommandChild, ShellExt};

enum EngineChild {
    Development(Child),
    Bundled(CommandChild),
}

impl EngineChild {
    fn kill(self) {
        match self {
            Self::Development(mut child) => {
                let _ = child.kill();
            }
            Self::Bundled(child) => {
                let _ = child.kill();
            }
        }
    }
}

struct EngineProcess(Mutex<Option<EngineChild>>);

fn start_development_engine() -> Option<EngineChild> {
    let mut root = std::env::current_dir().ok()?;
    while !root.join("pyproject.toml").exists() {
        if !root.pop() {
            return None;
        }
    }
    let mut cmd = Command::new(conda_executable());
    cmd.arg("run")
        .arg("-n")
        .arg("tj")
        .arg("--no-capture-output")
        .arg("python")
        .arg("-m")
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
    cmd.spawn().ok().map(EngineChild::Development)
}

fn start_bundled_engine(app: &tauri::AppHandle) -> Option<EngineChild> {
    let data_dir = app.path().app_data_dir().ok()?;
    std::fs::create_dir_all(&data_dir).ok()?;
    let command = app
        .shell()
        .sidecar("engine-sidecar")
        .ok()?
        .env("TJ_DATA_DIR", data_dir);
    let (_events, child) = command.spawn().ok()?;
    Some(EngineChild::Bundled(child))
}

fn conda_executable() -> PathBuf {
    if let Some(executable) = std::env::var_os("CONDA_EXE").map(PathBuf::from) {
        if executable.is_file() {
            return executable;
        }
    }

    let mut candidates = vec![
        PathBuf::from("/opt/miniconda3/bin/conda"),
        PathBuf::from("/opt/miniconda3/condabin/conda"),
        PathBuf::from("/opt/anaconda3/bin/conda"),
        PathBuf::from("/usr/local/anaconda3/bin/conda"),
    ];
    if let Some(home) = std::env::var_os("HOME").map(PathBuf::from) {
        candidates.push(home.join("miniconda3/bin/conda"));
        candidates.push(home.join("anaconda3/bin/conda"));
    }
    candidates.into_iter().find(|path| path.is_file()).unwrap_or_else(|| PathBuf::from("conda"))
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let child = if cfg!(debug_assertions) {
                start_development_engine()
            } else {
                start_bundled_engine(app.handle())
            };
            if child.is_none() {
                return Err("failed to start the Python engine".into());
            }
            app.manage(EngineProcess(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.try_state::<EngineProcess>() {
                    if let Ok(mut child) = state.0.lock() {
                        if let Some(process) = child.take() {
                            process.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Trading Journal");
}
