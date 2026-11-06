@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH exit /b 1
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
set "CMAKE=%VSPATH%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
cd /d "%~dp0.."
"%CMAKE%" -S vendor\localvqe-source\ggml -B build\neural -G "Visual Studio 17 2022" -A x64 -DLOCALVQE_BUILD_SHARED=ON -DGGML_OPENMP=OFF
if errorlevel 1 exit /b 1
"%CMAKE%" --build build\neural --config Release --target localvqe_shared --parallel 4 > build\neural-build.log 2>&1
if errorlevel 1 exit /b 1
copy /y build\neural\bin\Release\*.dll vendor\neural\ >nul
if errorlevel 1 exit /b 1
cl /nologo /LD /O2 /MD /EHsc /std:c++17 /arch:AVX2 /Ivendor\localvqe-source\ggml native\neural_bridge.cpp build\neural\Release\localvqe.lib /link /OUT:vendor\neural\cm_neural.dll /Brepro
exit /b %errorlevel%
