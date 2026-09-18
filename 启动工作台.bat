@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d %~dp0
title 律师本地工作台（预览版）
echo [1/2] 检查并安装本地依赖（仅本机，首次运行需要联网下载，之后可离线）...
python -m pip install -r requirements.txt -q
echo [2/2] 启动工作台（仅监听 127.0.0.1，数据全部保存在本目录 data 下）...
python -m server.launch
pause
