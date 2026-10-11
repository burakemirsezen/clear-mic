"""Verify the pinned driver with Microsoft's kernel signing policy."""
import os, subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sdk = Path(os.environ['ProgramFiles(x86)']) / 'Windows Kits' / '10' / 'bin'
tools = sorted(sdk.glob('*/x64/signtool.exe'))
if not tools:
    raise RuntimeError('Windows SDK signtool is required to verify kernel driver signing')
package = root / 'vendor' / 'vbcable'
subprocess.run([str(tools[-1]), 'verify', '/kp', '/c', str(package / 'vbaudio_cable64_win10.cat'), str(package / 'vbaudio_cable64_win10.sys')], check=True)
