@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
CALL "%dp0%java.cmd" -jar "%dp0%..\share\java\jd-gui\jd-gui.jar" %*
