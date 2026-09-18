#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
// 法岩律师本地工作台 · 统一安装包 64 位自解压引导器
// 自身 exe 尾部挂载 7z 载荷（payload.7z + 24 字节尾标），运行后：
// 1) 释放内嵌的 64 位 7za；2) 切出载荷并解压到临时目录；3) 调用 deploy.cmd 静默安装；
// 4) 全程原生窗口进度提示；5) 完成后清理临时文件。
use std::fs::{self, File};
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::windows::ffi::OsStrExt;
use std::path::PathBuf;
use std::ptr::{null, null_mut};
use std::sync::mpsc::{channel, Sender};
use std::thread;

use windows_sys::core::PCWSTR;
use windows_sys::Win32::Foundation::{
    CloseHandle, HANDLE, HANDLE_FLAG_INHERIT, HWND, LPARAM, LRESULT, RECT, SetHandleInformation,
    WPARAM,
};
use windows_sys::Win32::Storage::FileSystem::{GetTempPathW, ReadFile};
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::{
    CreateProcessW, GetExitCodeProcess, WaitForSingleObject, CREATE_NO_WINDOW, DETACHED_PROCESS,
    PROCESS_INFORMATION, STARTF_USESTDHANDLES, STARTUPINFOW,
};
use windows_sys::Win32::UI::Controls::{
    InitCommonControlsEx, PBM_SETPOS, PBM_SETRANGE, PROGRESS_CLASSW, INITCOMMONCONTROLSEX,
    ICC_PROGRESS_CLASS,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetDlgItem, GetMessageW, GetSystemMetrics,
    GetWindowRect, KillTimer, LoadCursorW, MessageBoxW, PostQuitMessage, RegisterClassExW,
    SendMessageW, SetTimer, SetWindowTextW, SetWindowPos, ShowWindow, TranslateMessage,
    CW_USEDEFAULT, IDC_APPSTARTING, MB_ICONERROR, MB_OK, MSG, SM_CXSCREEN, SM_CYSCREEN, SW_SHOW,
    SWP_NOZORDER, SWP_NOSIZE, WM_APP, WM_CREATE, WM_DESTROY, WM_SETFONT, WM_TIMER, WNDCLASSEXW,
    WS_CHILD, WS_OVERLAPPEDWINDOW, WS_THICKFRAME, WS_VISIBLE,
};
use windows_sys::Win32::Graphics::Gdi::{CreateFontW, COLOR_WINDOW};
use windows_sys::Win32::System::SystemServices::SS_LEFT;

const INFINITE_MS: u32 = 0xFFFF_FFFF;

const MAGIC: &[u8; 16] = b"LWSFXv01-PAYLOAD";
const TRAILER_LEN: u64 = 24; // magic(16) + payload_len u64(8)

const WM_PROGRESS: u32 = WM_APP + 1;
const WM_STATUS: u32 = WM_APP + 2;
const WM_DONE: u32 = WM_APP + 3;

const IDC_PROGRESS: usize = 1002;
const IDC_STATUS: usize = 1003;
const IDT_REFRESH: usize = 1;

const SEVENZA_EXE: &[u8] = include_bytes!("../7za.exe");
const SEVENZA_DLL: &[u8] = include_bytes!("../7za.dll");

fn wide(s: &str) -> Vec<u16> {
    std::ffi::OsStr::new(s)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}
fn pcw(s: &[u16]) -> PCWSTR {
    s.as_ptr()
}

struct Payload {
    exe_path: PathBuf,
    payload_len: u64,
}

fn read_trailer() -> Result<Payload, String> {
    let exe = std::env::current_exe().map_err(|e| format!("无法定位安装包：{e}"))?;
    let mut f = File::open(&exe).map_err(|e| format!("无法读取安装包：{e}"))?;
    let len = f.metadata().map_err(|e| e.to_string())?.len();
    if len < TRAILER_LEN {
        return Err("安装包已损坏（缺少尾标）".into());
    }
    f.seek(SeekFrom::Start(len - TRAILER_LEN))
        .map_err(|e| e.to_string())?;
    let mut trailer = [0u8; TRAILER_LEN as usize];
    f.read_exact(&mut trailer).map_err(|e| e.to_string())?;
    if &trailer[..16] != MAGIC {
        return Err("安装包已损坏（尾标校验失败）".into());
    }
    let mut b = [0u8; 8];
    b.copy_from_slice(&trailer[16..24]);
    let payload_len = u64::from_le_bytes(b);
    if payload_len == 0 || payload_len + TRAILER_LEN > len {
        return Err("安装包已损坏（载荷长度异常）".into());
    }
    Ok(Payload {
        exe_path: exe,
        payload_len,
    })
}

fn temp_dir() -> Result<PathBuf, String> {
    let mut buf = vec![0u16; 260];
    let n = unsafe { GetTempPathW(buf.len() as u32, buf.as_mut_ptr()) };
    if n == 0 {
        return Err("无法获取临时目录".into());
    }
    let mut base = PathBuf::from(String::from_utf16_lossy(&buf[..n as usize]));
    let pid = std::process::id();
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    base.push(format!("lw-install-{pid}-{t}"));
    fs::create_dir_all(&base).map_err(|e| format!("无法创建临时目录：{e}"))?;
    Ok(base)
}

fn write_embedded(dir: &PathBuf, name: &str, data: &[u8]) -> Result<(), String> {
    let p = dir.join(name);
    fs::write(&p, data).map_err(|e| format!("写入 {name} 失败：{e}"))
}

fn dump_payload(pl: &Payload, dst: &PathBuf, tx: &Sender<u32>) -> Result<(), String> {
    let mut src = File::open(&pl.exe_path).map_err(|e| e.to_string())?;
    let total = fs::metadata(&pl.exe_path).map_err(|e| e.to_string())?.len();
    let start = total - TRAILER_LEN - pl.payload_len;
    src.seek(SeekFrom::Start(start)).map_err(|e| e.to_string())?;
    let mut out = File::create(dst).map_err(|e| e.to_string())?;
    let mut buf = vec![0u8; 8 * 1024 * 1024];
    let mut remain = pl.payload_len;
    let mut done: u64 = 0;
    let mut last_pct = 0u32;
    while remain > 0 {
        let want = std::cmp::min(remain as usize, buf.len());
        let n = src.read(&mut buf[..want]).map_err(|e| e.to_string())?;
        if n == 0 {
            return Err("安装包读取中断".into());
        }
        out.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        remain -= n as u64;
        done += n as u64;
        let pct = (done as f64 / pl.payload_len as f64 * 100.0) as u32;
        if pct >= last_pct + 5 {
            last_pct = pct;
            let _ = tx.send(pct);
        }
    }
    out.sync_all().ok();
    Ok(())
}

struct HiddenProc {
    pi: PROCESS_INFORMATION,
    rd: HANDLE,
}

fn spawn_hidden(cmdline: &str, cwd: &PathBuf, capture_stdout: bool) -> Result<HiddenProc, String> {
    let mut sa = windows_sys::Win32::Security::SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<windows_sys::Win32::Security::SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: null_mut(),
        bInheritHandle: 1,
    };
    let mut rd: HANDLE = null_mut();
    let mut wr: HANDLE = null_mut();
    if capture_stdout {
        let ok = unsafe { CreatePipe(&mut rd, &mut wr, &mut sa, 0) };
        if ok == 0 {
            return Err("创建管道失败".into());
        }
        unsafe { SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0) };
    }
    let mut si: STARTUPINFOW = unsafe { std::mem::zeroed() };
    si.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
    if capture_stdout {
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdOutput = wr;
        si.hStdError = wr;
    }
    let mut pi: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    let mut cmd: Vec<u16> = String::from(cmdline)
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    let dirw: Vec<u16> = cwd
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let ok = unsafe {
        CreateProcessW(
            null(),
            cmd.as_mut_ptr(),
            null(),
            null(),
            if capture_stdout { 1 } else { 0 },
            CREATE_NO_WINDOW,
            null(),
            dirw.as_ptr(),
            &si,
            &mut pi,
        )
    };
    if capture_stdout {
        unsafe { CloseHandle(wr) };
    }
    if ok == 0 {
        if capture_stdout {
            unsafe { CloseHandle(rd) };
        }
        return Err(format!("无法启动进程：{cmdline}"));
    }
    Ok(HiddenProc { pi, rd })
}

impl HiddenProc {
    fn wait_with_progress(&self, tx: &Sender<u32>) -> Result<u32, String> {
        if !self.rd.is_null() {
            let mut pct = 0u32;
            let mut leftover = String::new();
            let mut buf = [0u8; 16 * 1024];
            loop {
                let mut nread: u32 = 0;
                let ok = unsafe {
                    ReadFile(
                        self.rd,
                        buf.as_mut_ptr() as _,
                        buf.len() as u32,
                        &mut nread,
                        null_mut(),
                    )
                };
                if ok == 0 || nread == 0 {
                    break;
                }
                let chunk = String::from_utf8_lossy(&buf[..nread as usize]);
                leftover.push_str(&chunk);
                let mut tail: Vec<char> = leftover.chars().rev().take(40).collect();
                tail.reverse();
                let s: String = tail.into_iter().collect();
                if let Some(pos) = s.rfind('%') {
                    let before: String = s[..pos]
                        .chars()
                        .rev()
                        .take(3)
                        .collect::<String>()
                        .chars()
                        .rev()
                        .collect();
                    let digits: String = before.chars().filter(|c| c.is_ascii_digit()).collect();
                    if let Ok(v) = digits.parse::<u32>() {
                        let v = v.min(100);
                        if v != pct {
                            pct = v;
                            let _ = tx.send(v);
                        }
                    }
                }
                if leftover.len() > 4096 {
                    let keep = leftover.len() - 1024;
                    leftover.drain(..keep);
                }
            }
        }
        unsafe {
            WaitForSingleObject(
                self.pi.hProcess,
                INFINITE_MS,
            );
            let mut code: u32 = 0;
            GetExitCodeProcess(self.pi.hProcess, &mut code);
            CloseHandle(self.pi.hThread);
            CloseHandle(self.pi.hProcess);
            if !self.rd.is_null() {
                CloseHandle(self.rd);
            }
            Ok(code)
        }
    }
}

fn worker(tx: Sender<u32>, stx: Sender<String>, done: Sender<Result<(), String>>) {
    let result = (|| -> Result<(), String> {
        let pl = read_trailer()?;
        let tmp = temp_dir()?;
        let root = tmp.join("root");
        fs::create_dir_all(&root).map_err(|e| e.to_string())?;

        let _ = stx.send("正在准备安装环境…".into());
        write_embedded(&tmp, "7za.exe", SEVENZA_EXE)?;
        write_embedded(&tmp, "7za.dll", SEVENZA_DLL)?;

        let _ = stx.send("正在释放安装资源（约 3GB，请耐心等待）…".into());
        let archive = tmp.join("payload.7z");
        dump_payload(&pl, &archive, &tx)?;

        let _ = stx.send("正在解压程序文件与本地 AI 引擎…".into());
        let sevenza = tmp.join("7za.exe");
        let cmd = format!(
            "\"{}\" x \"{}\" -o\"{}\" -y -bsp1 -bse1",
            sevenza.display(),
            archive.display(),
            root.display()
        );
        let hp = spawn_hidden(&cmd, &tmp, true)?;
        let code = hp.wait_with_progress(&tx)?;
        if code != 0 {
            return Err(format!("解压失败（错误码 {code}），请检查磁盘空间后重试。"));
        }
        let _ = fs::remove_file(&archive);

        let _ = stx.send("正在安装桌面程序并部署本地 AI 引擎…".into());
        let deploy = root.join("deploy.cmd");
        if !deploy.exists() {
            return Err("安装资源不完整：缺少 deploy.cmd".into());
        }
        let cmd2 = format!("cmd /c \"{}\"", deploy.display());
        let hp2 = spawn_hidden(&cmd2, &root, false)?;
        let code2 = hp2.wait_with_progress(&tx)?;
        if code2 != 0 {
            return Err(format!("安装步骤失败（错误码 {code2}）。"));
        }

        let _ = stx.send("正在清理临时文件…".into());
        let _ = fs::remove_file(tmp.join("7za.exe"));
        let _ = fs::remove_file(tmp.join("7za.dll"));
        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&tmp);
        Ok(())
    })();
    let _ = done.send(result);
}

/// 安装成功后由引导器直接以独立进程方式拉起桌面程序，
/// 避免从隐藏的 cmd/PowerShell 树启动时随安装脚本退出而被回收。
unsafe fn launch_installed_app() {
    let marker = std::env::temp_dir().join("lw-install-loc.txt");
    let loc = match fs::read_to_string(&marker) {
        Ok(s) => s.trim().to_string(),
        Err(_) => return,
    };
    let _ = fs::remove_file(&marker);
    let exe = std::path::Path::new(&loc).join("legal-workbench.exe");
    if !exe.exists() {
        return;
    }
    let exe_str = exe.display().to_string();
    let mut cmdline: Vec<u16> = std::ffi::OsStr::new(&format!("\"{exe_str}\""))
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut cwd: Vec<u16> = std::ffi::OsStr::new(&loc)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut si: STARTUPINFOW = std::mem::zeroed();
    si.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
    let mut pi: PROCESS_INFORMATION = std::mem::zeroed();
    let ok = CreateProcessW(
        null(),
        cmdline.as_mut_ptr(),
        null(),
        null(),
        0,
        DETACHED_PROCESS,
        null(),
        cwd.as_mut_ptr(),
        &si,
        &mut pi,
    );
    if ok != 0 {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
}

fn create_label(
    parent: HWND,
    text: &str,
    id: usize,
    bold: bool,
    size: i32,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
) -> HWND {
    let cls = wide("STATIC");
    let cap = wide(text);
    let face = wide("Microsoft YaHei UI");
    let font = unsafe {
        CreateFontW(
            size, 0, 0, 0,
            if bold { 700 } else { 400 },
            0, 0, 0, 1, 0, 0, 0, 0, pcw(&face),
        )
    };
    let hw = unsafe {
        CreateWindowExW(
            0,
            pcw(&cls),
            pcw(&cap),
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            x, y, w, h,
            parent, id as _, null_mut(), null(),
        )
    };
    unsafe {
        SendMessageW(hw, WM_SETFONT, font as _, 1)
    };
    hw
}

fn drain_channels(hwnd: HWND, prx: &std::sync::mpsc::Receiver<u32>, srx: &std::sync::mpsc::Receiver<String>, drx: &std::sync::mpsc::Receiver<Result<(), String>>) -> bool {
    while let Ok(p) = prx.try_recv() {
        unsafe {
            let pb = GetDlgItem(hwnd, IDC_PROGRESS as _);
            SendMessageW(pb, PBM_SETPOS, p as _, 0);
        }
    }
    while let Ok(s) = srx.try_recv() {
        unsafe {
            let st = GetDlgItem(hwnd, IDC_STATUS as _);
            let w = wide(&s);
            SetWindowTextW(st, pcw(&w));
        }
    }
    if let Ok(r) = drx.try_recv() {
        match r {
            Ok(()) => unsafe {
                launch_installed_app();
                PostQuitMessage(0);
            },
            Err(e) => {
                let m = wide(&format!("安装失败：{e}"));
                unsafe {
                    MessageBoxW(
                        hwnd,
                        pcw(&m),
                        pcw(&wide("法岩律师本地工作台 · 安装")),
                        MB_OK | MB_ICONERROR,
                    );
                    PostQuitMessage(1);
                }
            }
        }
        return false;
    }
    true
}

fn main() {
    let hinst = unsafe { GetModuleHandleW(null()) };

    let mut icc: INITCOMMONCONTROLSEX = unsafe { std::mem::zeroed() };
    icc.dwSize = std::mem::size_of::<INITCOMMONCONTROLSEX>() as u32;
    icc.dwICC = ICC_PROGRESS_CLASS;
    unsafe { InitCommonControlsEx(&icc) };

    let cls = wide("LwSfxInstallerWindow");
    let mut wc: WNDCLASSEXW = unsafe { std::mem::zeroed() };
    wc.cbSize = std::mem::size_of::<WNDCLASSEXW>() as u32;
    wc.lpfnWndProc = Some(wndproc);
    wc.hInstance = hinst;
    wc.hCursor = unsafe { LoadCursorW(null_mut(), IDC_APPSTARTING) };
    wc.hbrBackground = (COLOR_WINDOW + 1) as _;
    wc.lpszClassName = pcw(&cls);
    unsafe { RegisterClassExW(&wc) };

    let title = wide("法岩律师本地工作台 · 安装");
    let hwnd = unsafe {
        CreateWindowExW(
            0,
            pcw(&cls),
            pcw(&title),
            WS_OVERLAPPEDWINDOW & !WS_THICKFRAME
                & !windows_sys::Win32::UI::WindowsAndMessaging::WS_MAXIMIZEBOX,
            CW_USEDEFAULT, CW_USEDEFAULT, 560, 250,
            null_mut(), null_mut(), hinst, null(),
        )
    };

    unsafe {
        let mut r: RECT = std::mem::zeroed();
        GetWindowRect(hwnd, &mut r);
        let w = r.right - r.left;
        let h = r.bottom - r.top;
        let sw = GetSystemMetrics(SM_CXSCREEN);
        let sh = GetSystemMetrics(SM_CYSCREEN);
        SetWindowPos(
            hwnd, null_mut(),
            (sw - w) / 2, (sh - h) / 2, 0, 0,
            SWP_NOSIZE | SWP_NOZORDER,
        );
        ShowWindow(hwnd, SW_SHOW);
        SetTimer(hwnd, IDT_REFRESH, 200, None);
    }

    let (ptx, prx) = channel::<u32>();
    let (stx, srx) = channel::<String>();
    let (dtx, drx) = channel::<Result<(), String>>();
    thread::spawn(move || worker(ptx, stx, dtx));

    let mut msg: MSG = unsafe { std::mem::zeroed() };
    loop {
        if !drain_channels(hwnd, &prx, &srx, &drx) {
            break;
        }
        let got = unsafe { GetMessageW(&mut msg, null_mut(), 0, 0) };
        if got <= 0 {
            break;
        }
        unsafe {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if msg.message == windows_sys::Win32::UI::WindowsAndMessaging::WM_TIMER {
            if !drain_channels(hwnd, &prx, &srx, &drx) {
                break;
            }
        }
    }
    unsafe { KillTimer(hwnd, IDT_REFRESH) };
}

unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    match msg {
        WM_CREATE => {
            create_label(hwnd, "法岩律师本地工作台 v1.0.0", 1001, true, 20, 28, 22, 500, 32);
            create_label(
                hwnd,
                "正在准备内置本地 AI 环境，全程离线，数据仅保存在本机。",
                1004, false, 13, 28, 58, 500, 22,
            );
            
            CreateWindowExW(
                0,
                PROGRESS_CLASSW,
                null(),
                WS_CHILD | WS_VISIBLE,
                28, 100, 488, 18,
                hwnd, IDC_PROGRESS as _, null_mut(), null(),
            );
            let pb = GetDlgItem(hwnd, IDC_PROGRESS as _);
            SendMessageW(pb, PBM_SETRANGE, 0, (100u32 << 16) as _);
            create_label(hwnd, "正在初始化…", IDC_STATUS, false, 12, 28, 128, 500, 20);
            create_label(
                hwnd,
                "安装期间如出现安全软件提示，请选择允许（全部组件均在本机运行）。",
                1005, false, 12, 28, 162, 500, 20,
            );
            0
        }
        WM_TIMER => 0,
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wp, lp),
    }
}
