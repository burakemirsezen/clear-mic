import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
env=os.environ.copy();env['CLEARMIC_DATA_DIR']=str(ROOT/'.state'/'desktop-validation-data');env['CLEARMIC_TEST_DIR']=str(ROOT/'.state'/'desktop-validation')
checksfile=Path(env['CLEARMIC_TEST_DIR'])/'checks.json';checksfile.unlink(missing_ok=True)
subprocess.run([str(ROOT/'dist'/'ClearMic-win32-x64'/'ClearMic.exe'),'--ui-test'],env=env,check=True,timeout=60)
checks=json.loads(checksfile.read_text())
if not checks['pass']:raise RuntimeError('Desktop verification failed: '+str(checks))
print('Desktop controls, presets, persistence and responsive layout verified.')
