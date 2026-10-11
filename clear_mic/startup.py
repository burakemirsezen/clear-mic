import sys,winreg,subprocess
from .paths import command
KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
def enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:winreg.QueryValueEx(key,'ClearMic');return True
    except OSError:return False
def set_enabled(value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
        if value:
            cmd=command('--tray')
            if not getattr(sys,'frozen',False):cmd[0]=cmd[0].replace('python.exe','pythonw.exe')
            winreg.SetValueEx(key,'ClearMic',0,winreg.REG_SZ,subprocess.list2cmdline(cmd))
        else:
            try:winreg.DeleteValue(key,'ClearMic')
            except FileNotFoundError:pass
