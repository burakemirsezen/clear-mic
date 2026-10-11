import shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from clear_mic import __version__
subprocess.run([sys.executable,str(ROOT/'scripts'/'make_icon.py')],check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts'/'collect_licenses.py')],check=True,cwd=ROOT)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console','--name','ClearMicAudio','--add-binary',str(ROOT/'vendor'/'clearmic_native.dll')+';vendor','--add-data',str(ROOT/'THIRD_PARTY')+';THIRD_PARTY','--collect-all','sounddevice','--collect-all','_sounddevice_data','--collect-all','soundfile','--collect-all','_soundfile_data',str(ROOT/'backend.py')],check=True,cwd=ROOT)
subprocess.run(['node',str(ROOT/'scripts'/'package_desktop.cjs')],check=True,cwd=ROOT)
folder=ROOT/'dist'/'ClearMic-win32-x64';shutil.copy2(ROOT/'README.md',folder/'README.md');shutil.copy2(ROOT/'LICENSE',folder/'LICENSE')
release=ROOT/'release';release.mkdir(exist_ok=True)
name=f'ClearMic-{__version__}-windows-x64'
shutil.make_archive(str(release/name),'zip',ROOT/'dist',folder.name)
print('Packaged '+name+'.zip')
