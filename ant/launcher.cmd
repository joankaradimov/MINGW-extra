@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
IF NOT DEFINED JAVA_HOME FOR %%I IN ("%dp0%..\lib\jvm\@JVMDIR@") DO SET "JAVA_HOME=%%~fI"
SET "PATH=%dp0%;%PATH%"
CALL "%dp0%..\share\ant\bin\ant.bat" %*
