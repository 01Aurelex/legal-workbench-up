// 法岩律师本地工作台 · Tauri 原生外壳
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
//
// 职责：
// 1) 单实例运行（重复启动只聚焦已有窗口）；
// 2) 从安装目录 resources/sidecar/ 拉起内置 Python 后端（PyInstaller onedir，无控制台），
//    一次性本机令牌经环境变量注入（不落盘）；后端自管子进程（内置 AI 引擎随其退出而消亡）；
// 3) 先显示内置启动加载页，待 127.0.0.1:8765 就绪后再切入本地界面；
// 4) 退出时结束后端进程，不在任务管理器遗留；
// 5) 仅访问回环地址，不加载任何远程页面，release 不含 devtools。
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const BACKEND_PORT: u16 = 8765;

struct BackendChild(Mutex<Option<Child>>);

fn random_token() -> String {
    let mut buf = [0u8; 32];
    let seed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let mut x = seed ^ ((std::process::id() as u128) << 17) ^ 0x9e3779b97f4a7c15;
    for b in buf.iter_mut() {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        *b = (x & 0xff) as u8;
    }
    buf.iter().map(|b| format!("{:02x}", b)).collect()
}

fn wait_port(host: &str, port: u16, timeout_secs: u64) -> bool {
    let start = Instant::now();
    while start.elapsed() < Duration::from_secs(timeout_secs) {
        if TcpStream::connect((host, port)).is_ok() {
            std::thread::sleep(Duration::from_millis(400));
            if TcpStream::connect((host, port)).is_ok() {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

#[cfg(windows)]
fn spawn_backend(exe: &PathBuf, token: &str) -> std::io::Result<Child> {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    Command::new(exe)
        .current_dir(exe.parent().unwrap())
        .env("LW_AUTO_TOKEN", token)
        .env("LW_NO_BROWSER", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
}

#[cfg(not(windows))]
fn spawn_backend(exe: &PathBuf, token: &str) -> std::io::Result<Child> {
    Command::new(exe)
        .current_dir(exe.parent().unwrap())
        .env("LW_AUTO_TOKEN", token)
        .env("LW_NO_BROWSER", "1")
        .spawn()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .manage(BackendChild(Mutex::new(None)))
        .setup(|app| {
            let token = random_token();
            // 后端固定安装在 <安装目录>/resources/sidecar/legal-workbench.exe
            let backend_exe = app
                .path()
                .resource_dir()
                .expect("无法定位资源目录")
                .join("sidecar")
                .join("legal-workbench.exe");
            let child = spawn_backend(&backend_exe, &token)
                .unwrap_or_else(|e| panic!("内置后端启动失败 {:?}: {}", backend_exe, e));
            app.state::<BackendChild>().0.lock().unwrap().replace(child);

            // 立即显示启动加载页（前端包内静态页，无需后端）
            let win = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("loading.html".into()))
                .title("法岩律师本地工作台")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1080.0, 680.0)
                .center()
                .resizable(true)
                .decorations(true)
                .build()?;

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ok = wait_port("127.0.0.1", BACKEND_PORT, 90);
                let Some(w) = handle.get_webview_window("main") else { return };
                if ok {
                    let url = format!("http://127.0.0.1:{BACKEND_PORT}/?token={token}");
                    let js = format!("window.location.replace('{}');", url);
                    let _ = w.eval(&js);
                } else {
                    let _ = w.eval(
                        "window.showFail && window.showFail('内置服务启动超时，请检查安全软件拦截后重启软件');",
                    );
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Tauri 运行时初始化失败")
        .run(|app, event| match event {
            RunEvent::ExitRequested { .. } => {
                if let Some(state) = app.try_state::<BackendChild>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
            RunEvent::WindowEvent {
                event: tauri::WindowEvent::CloseRequested { .. },
                ..
            } => {
                if let Some(state) = app.try_state::<BackendChild>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
                app.exit(0);
            }
            _ => {}
        });
}
