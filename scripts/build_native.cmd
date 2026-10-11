@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH (
  echo Install Visual Studio C++ x64 build tools first.
  exit /b 1
)
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cd /d "%~dp0..\vendor\rnnoise-src"
cl /nologo /c /O2 /MT /arch:AVX2 /fp:precise /DRNNOISE_BUILD /DDLL_EXPORT /DWIN32 /D__SSE_4_1__ /Iinclude /Isrc src\denoise.c src\rnn.c src\pitch.c src\kiss_fft.c src\celt_lpc.c src\nnet.c src\nnet_default.c src\parse_lpcnet_weights.c src\rnnoise_data.c src\rnnoise_tables.c
if errorlevel 1 exit /b 1
cl /nologo /LD /O2 /MT /EHsc /std:c++17 /Iinclude "..\..\native\speech.cpp" denoise.obj rnn.obj pitch.obj kiss_fft.obj celt_lpc.obj nnet.obj nnet_default.obj parse_lpcnet_weights.obj rnnoise_data.obj rnnoise_tables.obj "..\..\build\webrtc\Release\cm_agc2.lib" /link /OUT:"..\clearmic_native.dll" /Brepro
exit /b %errorlevel%
