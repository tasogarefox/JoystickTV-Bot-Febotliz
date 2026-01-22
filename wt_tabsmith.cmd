@echo off

set "BE=%~dp0backend"
set "FE=%~dp0frontend"

wt -w 0 ^
  nt -d "%BE%" powershell.exe -NoExit -Command "%BE%\run.cmd" ^
  ; nt -d "%FE%" powershell.exe -NoExit ^
  ; nt -d "%FE%" powershell.exe -NoExit -Command "%FE%\run.cmd"

cd /D "%BE%"
"%BE%\ps.cmd"
