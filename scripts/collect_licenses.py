import importlib.metadata as metadata,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];target=ROOT/'THIRD_PARTY'/'runtime';target.mkdir(exist_ok=True)
for name in ['numpy','sounddevice','soundfile','pillow','pystray','cffi','pycparser','six','typing-extensions']:
    dist=metadata.distribution(name)
    for file in dist.files or []:
        if 'license' not in str(file).lower() and 'copying' not in str(file).lower():continue
        source=Path(dist.locate_file(file))
        if source.is_file():shutil.copy2(source,target/(name+'--'+str(file).replace('/','--').replace('\\','--')))
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():shutil.copy2(python_license,target/'Python-LICENSE.txt')
