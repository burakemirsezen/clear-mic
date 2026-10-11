import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from clear_mic.tray import image
im=image().resize((256,256));im.save(ROOT/'assets'/'clear-mic.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
