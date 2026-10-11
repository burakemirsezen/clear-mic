"""Retain the full, unmodified vendor package and verify every driver input."""
import hashlib,json,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];lock=json.loads((ROOT/'vbcable.lock.json').read_text());target=ROOT/'vendor'/'vbcable';target.mkdir(parents=True,exist_ok=True)
archive=target/'VBCABLE_Driver_Pack45.zip'
if not archive.exists():
    with urllib.request.urlopen(lock['url'],timeout=30) as response:archive.write_bytes(response.read())
if hashlib.sha256(archive.read_bytes()).hexdigest()!=lock['package_sha256']:raise ValueError('VB-CABLE package checksum mismatch')
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        file=(target/item.filename).resolve()
        if not file.is_relative_to(target.resolve()):raise ValueError('Unsafe archive path')
        if item.is_dir():file.mkdir(parents=True,exist_ok=True)
        else:file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(z.read(item))
for name,digest in lock['files'].items():
    if hashlib.sha256((target/name).read_bytes()).hexdigest()!=digest:raise ValueError('Driver checksum mismatch: '+name)
print('Official VB-CABLE package verified; all vendor files retained unchanged.')
