// 防止 Windows release 下额外弹出控制台窗口
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    legal_workbench_lib::run()
}
