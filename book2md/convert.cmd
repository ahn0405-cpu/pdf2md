@echo off
REM Windows 용. 지침 §7 의 명령 이름 그대로.
REM   convert diagnose "기본서.pdf"
python -m book2md %*
