import shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,str(ROOT/'scripts'/'make_icon.py')],check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts'/'collect_licenses.py')],check=True,cwd=ROOT)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','ClearMic','--icon',str(ROOT/'assets'/'clear-mic.ico'),'--add-binary',str(ROOT/'vendor'/'clearmic_native.dll')+';vendor','--add-data',str(ROOT/'assets')+';assets','--add-data',str(ROOT/'THIRD_PARTY')+';THIRD_PARTY','--collect-all','sounddevice','--collect-all','_sounddevice_data','--collect-all','soundfile','--collect-all','_soundfile_data','--hidden-import','clear_mic.self_test',str(ROOT/'main.py')],check=True,cwd=ROOT)
folder=ROOT/'dist'/'ClearMic';shutil.copy2(ROOT/'README.md',folder/'README.md');shutil.copy2(ROOT/'LICENSE',folder/'LICENSE')
release=ROOT/'release';release.mkdir(exist_ok=True)
shutil.make_archive(str(release/'ClearMic-1.0.0-windows-x64'),'zip',ROOT/'dist','ClearMic')
print('Packaged ClearMic-1.0.0-windows-x64.zip')
