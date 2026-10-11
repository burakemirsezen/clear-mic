@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH exit /b 1
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cd /d "%~dp0.."
cl /nologo /O2 /MT /EHsc /std:c++17 native\device_setup.cpp /Fo:vendor\device_setup.obj /Fe:vendor\ClearMicDeviceSetup.exe /link setupapi.lib newdev.lib cfgmgr32.lib ole32.lib propsys.lib uuid.lib advapi32.lib bcrypt.lib /Brepro
exit /b %errorlevel%
