"""Fetch pinned 48 kHz DPDFNet weights and retain the upstream Apache notice."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];lock=json.loads((ROOT/'fullband.lock.json').read_text())
folder=ROOT/'vendor/fullband';folder.mkdir(exist_ok=True);path=folder/lock['model']
if not path.exists():
    url=f"https://huggingface.co/{lock['repository']}/resolve/{lock['revision']}/onnx/{lock['model']}"
    data=urllib.request.urlopen(url,timeout=90).read()
    if hashlib.sha256(data).hexdigest()!=lock['sha256']:raise RuntimeError('Full-band model checksum mismatch')
    path.write_bytes(data)
if hashlib.sha256(path.read_bytes()).hexdigest()!=lock['sha256']:raise RuntimeError('Modified full-band model')
notice=ROOT/'THIRD_PARTY/DPDFNet';notice.mkdir(exist_ok=True)
license=urllib.request.urlopen('https://raw.githubusercontent.com/ceva-ip/DPDFNet/main/LICENSE',timeout=30).read()
(notice/'LICENSE').write_bytes(license)
(notice/'SOURCE.txt').write_text(f"https://github.com/ceva-ip/DPDFNet\nPython streaming algorithm: dpdfnet 0.6.0 (Apache-2.0); adapted to fixed 480-sample buffers, pre-warmed ORT, 50 ms aligned dry blend and existing stereo AEC.\nModel: https://huggingface.co/{lock['repository']}\nRevision {lock['revision']}\nSHA256 {lock['sha256']}\n",encoding='utf-8')
print('Full-band model and attribution verified.')
