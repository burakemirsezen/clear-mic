"""Fetch checksum-pinned WebRTC extractions and apply reproducible MSVC fixes."""
import hashlib,io,json,zipfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def patch(path,old,new):
    value=path.read_text(encoding='utf-8')
    if new in value:return
    if old not in value:raise RuntimeError(f'Unexpected source in {path}')
    path.write_text(value.replace(old,new),encoding='utf-8')
for name,lock in json.loads((ROOT/'webrtc.lock.json').read_text()).items():
    target=ROOT/'vendor'/f'webrtc-{name}'
    marker=target/'.clearmic-source'
    if not marker.exists() or marker.read_text()!=lock['commit']:
        data=urllib.request.urlopen(lock['url'],timeout=90).read()
        if hashlib.sha256(data).hexdigest()!=lock['sha256']:raise RuntimeError('WebRTC checksum mismatch')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                relative=Path(*Path(item.filename).parts[1:])
                if not relative.parts or item.is_dir():continue
                path=(target/relative).resolve()
                if not path.is_relative_to(target.resolve()):raise RuntimeError('Unsafe archive path')
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(item))
        marker.write_text(lock['commit'])
    if name=='aec3':
        path=target/'src/audio_processing/aec3/matched_filter_avx2.cc'
        text=path.read_text()
        # MSVC SIMD types expose named lane arrays instead of GCC vector subscripts.
        import re
        text=re.sub(r'\bs_inst_hadd_256\[(\d)\]',r's_inst_hadd_256.m256_f32[\1]',text)
        text=re.sub(r'\be_128\[(\d)\]',r'e_128.m128_f32[\1]',text)
        text=re.sub(r'\bsum\[(\d)\]',r'sum.m128_f32[\1]',text)
        path.write_text(text)
    notices=ROOT/'THIRD_PARTY'/f'webrtc-{name}';notices.mkdir(exist_ok=True)
    (notices/'LICENSE').write_bytes((target/'LICENSE').read_bytes())
    (notices/'SOURCE.txt').write_text(f"{lock['repo']}\nCommit {lock['commit']}\nSHA256 {lock['sha256']}\nMSVC: /Zc:__cplusplus, forced array include, named SIMD lane arrays.\n")
print('WebRTC sources verified and prepared')
