import hashlib,json,tarfile,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];VENDOR=ROOT/'vendor';VENDOR.mkdir(exist_ok=True)
lock=json.loads((ROOT/'rnnoise.lock.json').read_text())
def fetch(url,path,digest):
    if not path.exists():
        request=urllib.request.Request(url,headers={'User-Agent':'ClearMic-build'})
        with urllib.request.urlopen(request,timeout=60) as source,path.open('wb') as out:
            while block:=source.read(1024*1024):out.write(block)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError(f'Checksum mismatch: {path.name}')
source=VENDOR/'rnnoise-src';source.mkdir(exist_ok=True)
archive=VENDOR/'rnnoise.zip';fetch(f"https://codeload.github.com/xiph/rnnoise/zip/{lock['commit']}",archive,lock['source_sha256'])
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        parts=Path(item.filename).parts[1:]
        if not parts:continue
        destination=source.joinpath(*parts).resolve()
        if not destination.is_relative_to(source.resolve()):raise ValueError('Unsafe archive path')
        if item.is_dir():destination.mkdir(parents=True,exist_ok=True)
        else:destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(z.read(item))
model=VENDOR/f"rnnoise_data-{lock['model_sha256']}.tar.gz"
fetch(f'https://media.xiph.org/rnnoise/models/{model.name}',model,lock['model_sha256'])
with tarfile.open(model) as t:t.extractall(source,filter='data')
print('Pinned RNNoise source and model verified.')
