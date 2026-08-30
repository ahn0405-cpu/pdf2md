@echo off
REM Windows 용 실행기. 지침 §7 의 명령 이름 그대로 쓴다.
REM   convert diagnose "C:\Users\...\25년 윤곽"
REM
REM 콘솔 코드페이지를 UTF-8 로 바꾸고 파이썬도 UTF-8 모드로 돌린다.
REM 안 그러면 리포트의 한글·기호에서 출력이 멈춘다.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -m book2md %*
