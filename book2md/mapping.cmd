@echo off
REM Windows 용 매핑 실행기.
REM   mapping build "C:\...\민소출력\기본서" "C:\...\민소출력\사례집" -o mapping.yaml
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -m book2md mapping %*
