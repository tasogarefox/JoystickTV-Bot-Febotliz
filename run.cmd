@echo off

set "BE=%~dp0backend"
cd /D "%BE%"

"%BE%\venv\Scripts\activate" && powershell -NoExit -Command "%BE%\run.cmd"
