@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH exit /b 1
set "CMAKE=%VSPATH%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
if not exist "%CMAKE%" set "CMAKE=cmake"
cd /d "%~dp0.."
"%CMAKE%" -S native\webrtc-build -B build\webrtc -G "Visual Studio 17 2022" -A x64
if errorlevel 1 exit /b 1
"%CMAKE%" --build build\webrtc --config Release --parallel 4 > build\webrtc-build.log 2>&1
if errorlevel 1 exit /b 1
copy /y build\webrtc\Release\cm_agc2.dll vendor\cm_agc2.dll >nul
copy /y build\webrtc\Release\cm_aec3.dll vendor\cm_aec3.dll >nul
copy /y build\webrtc\Release\cm_reference.dll vendor\cm_reference.dll >nul
exit /b %errorlevel%
