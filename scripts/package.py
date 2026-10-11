import shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from clear_mic import __version__
subprocess.run([sys.executable,str(ROOT/'scripts'/'fetch_webrtc.py')],check=True,cwd=ROOT)
subprocess.run([str(ROOT/'scripts'/'build_webrtc.cmd')],check=True,cwd=ROOT)
subprocess.run([str(ROOT/'scripts'/'build_native.cmd')],check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts'/'fetch_vbcable.py')],check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts'/'verify_driver.py')],check=True,cwd=ROOT)
subprocess.run([str(ROOT/'scripts'/'build_device_setup.cmd')],check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts'/'make_icon.py')],check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts'/'collect_licenses.py')],check=True,cwd=ROOT)
native=[]
for dll in ('clearmic_native.dll','cm_agc2.dll','cm_aec3.dll','cm_reference.dll'):native+=['--add-binary',str(ROOT/'vendor'/dll)+';vendor']
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console','--name','ClearMicAudio',*native,'--add-data',str(ROOT/'THIRD_PARTY')+';THIRD_PARTY','--collect-all','sounddevice','--collect-all','_sounddevice_data','--collect-all','soundfile','--collect-all','_soundfile_data',str(ROOT/'backend.py')],check=True,cwd=ROOT)
subprocess.run(['node',str(ROOT/'scripts'/'package_desktop.cjs')],check=True,cwd=ROOT)
folder=ROOT/'dist'/'ClearMic-win32-x64'
for name in ('README.md','RESEARCH.md','LICENSE'):shutil.copy2(ROOT/name,folder/name)
release=ROOT/'release';release.mkdir(exist_ok=True)
name=f'ClearMic-{__version__}-windows-x64'
shutil.make_archive(str(release/name),'zip',ROOT/'dist',folder.name)
print('Packaged '+name+'.zip')
