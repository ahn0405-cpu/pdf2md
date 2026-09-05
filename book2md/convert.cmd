@echo off
REM Windows 용 실행기. 지침 §7 의 명령 이름 그대로 쓴다.
REM   convert --book 민소법 all "C:\Users\...\25년 윤곽" --out "...\민소출력"
REM
REM --book 을 빠뜨리면 사람이 확인한 정정이 빠진 채 변환된다. 무엇을 읽었는지
REM 명령이 첫 줄에 찍으니 확인할 것.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -m book2md %*
