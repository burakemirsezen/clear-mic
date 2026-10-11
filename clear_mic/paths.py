import os,sys
from pathlib import Path
ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
DATA=Path(os.environ.get('CLEARMIC_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'ClearMic')))
def initialize():
    for name in ('','logs','previews'):(DATA/name).mkdir(parents=True,exist_ok=True)
def command(*args):
    if getattr(sys,'frozen',False):return [sys.executable,*map(str,args)]
    return [sys.executable,str(ROOT/'main.py'),*map(str,args)]
