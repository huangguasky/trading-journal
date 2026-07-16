use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex,
};
use tauri::Manager;

struct EngineProcess {
    child: Mutex<Option<Child>>,
    problem: Arc<Mutex<Option<String>>>,
    stderr: Arc<Mutex<Vec<String>>>,
    generation: Arc<AtomicU64>,
    port: Mutex<u16>,
}

fn start_development_engine() -> Result<Child, String> {
    let mut root = std::env::current_dir().map_err(|error| error.to_string())?;
    while !root.join("pyproject.toml").exists() {
        if !root.pop() {
            return Err("could not find the project root".into());
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
    cmd.spawn()
        .map_err(|error| format!("failed to start the development engine: {error}"))
}

fn start_bundled_engine(
    app: &tauri::AppHandle,
    stderr_lines: Arc<Mutex<Vec<String>>>,
    port: u16,
) -> Result<Child, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|error| format!("failed to create the engine data directory: {error}"))?;
    let executable = bundled_engine_executable(app)?;
    let mut command = Command::new(&executable);
    command
        .env("TJ_DATA_DIR", data_dir)
        .env("TJ_PORT", port.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start the bundled engine: {error}"))?;

    if let Some(stderr) = child.stderr.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let line = line.trim().to_string();
                if !line.is_empty() {
                    if let Ok(mut lines) = stderr_lines.lock() {
                        lines.push(line);
                        if lines.len() > 8 {
                            lines.remove(0);
                        }
                    }
                }
            }
        });
    }

    Ok(child)
}

fn bundled_engine_executable(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let mut executable = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to locate application resources: {error}"))?
        .join("binaries")
        .join("engine-sidecar-runtime")
        .join("engine-sidecar");
    if cfg!(windows) {
        executable.set_extension("exe");
    }
    if !executable.is_file() {
        return Err(format!(
            "bundled engine executable is missing: {}",
            executable.display()
        ));
    }
    Ok(executable)
}

fn set_engine_problem(
    problem: &Mutex<Option<String>>,
    generation: &AtomicU64,
    active_generation: u64,
    message: String,
) {
    if generation.load(Ordering::Acquire) != active_generation {
        return;
    }
    if let Ok(mut current) = problem.lock() {
        *current = Some(message);
    }
}

fn start_engine(
    app: &tauri::AppHandle,
    stderr: Arc<Mutex<Vec<String>>>,
    port: u16,
) -> Result<Child, String> {
    if cfg!(debug_assertions) {
        start_development_engine()
    } else {
        start_bundled_engine(app, stderr, port)
    }
}

fn available_engine_port() -> Result<u16, String> {
    if cfg!(debug_assertions) {
        return Ok(8765);
    }
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to reserve a local engine port: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("failed to read the local engine port: {error}"))
}

#[tauri::command]
fn restart_engine(
    app: tauri::AppHandle,
    state: tauri::State<'_, EngineProcess>,
) -> Result<(), String> {
    let mut child = state
        .child
        .lock()
        .map_err(|_| "engine process state is unavailable".to_string())?;
    let active_generation = state.generation.fetch_add(1, Ordering::AcqRel) + 1;
    if let Some(process) = child.take() {
        stop_engine(process);
    }
    if let Ok(mut problem) = state.problem.lock() {
        *problem = None;
    }
    if let Ok(mut stderr) = state.stderr.lock() {
        stderr.clear();
    }
    let port = available_engine_port()?;
    *state
        .port
        .lock()
        .map_err(|_| "engine port state is unavailable".to_string())? = port;
    match start_engine(&app, Arc::clone(&state.stderr), port) {
        Ok(process) => {
            *child = Some(process);
            Ok(())
        }
        Err(error) => {
            set_engine_problem(
                &state.problem,
                &state.generation,
                active_generation,
                error.clone(),
            );
            Err(error)
        }
    }
}

#[tauri::command]
fn engine_problem(state: tauri::State<'_, EngineProcess>) -> Option<String> {
    if let Ok(mut child) = state.child.lock() {
        if let Some(process) = child.as_mut() {
            if let Ok(Some(status)) = process.try_wait() {
                if !status.success() {
                    let detail = state
                        .stderr
                        .lock()
                        .ok()
                        .filter(|lines| !lines.is_empty())
                        .map(|lines| lines.join("\n"))
                        .unwrap_or_else(|| format!("engine exited with status {status}"));
                    set_engine_problem(
                        &state.problem,
                        &state.generation,
                        state.generation.load(Ordering::Acquire),
                        detail,
                    );
                }
            }
        }
    }
    state
        .problem
        .lock()
        .ok()
        .and_then(|problem| problem.clone())
}

fn stop_engine(mut child: Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[tauri::command]
fn engine_endpoint(state: tauri::State<'_, EngineProcess>) -> Result<String, String> {
    state
        .port
        .lock()
        .map(|port| format!("http://127.0.0.1:{port}"))
        .map_err(|_| "engine port state is unavailable".to_string())
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
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from("conda"))
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            restart_engine,
            engine_problem,
            engine_endpoint
        ])
        .setup(|app| {
            let problem = Arc::new(Mutex::new(None));
            let stderr = Arc::new(Mutex::new(Vec::new()));
            let generation = Arc::new(AtomicU64::new(0));
            let port = available_engine_port()?;
            let child = start_engine(app.handle(), Arc::clone(&stderr), port)
                .map_err(|error| format!("failed to start the Python engine: {error}"))?;
            app.manage(EngineProcess {
                child: Mutex::new(Some(child)),
                problem,
                stderr,
                generation,
                port: Mutex::new(port),
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.try_state::<EngineProcess>() {
                    state.generation.fetch_add(1, Ordering::AcqRel);
                    if let Ok(mut child) = state.child.lock() {
                        if let Some(process) = child.take() {
                            stop_engine(process);
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Trading Journal");
}
