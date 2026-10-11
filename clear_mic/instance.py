import ctypes,atexit,hashlib
from .paths import DATA
def acquire():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle.restype=ctypes.c_int
    handle=kernel.CreateMutexW(None,False,'Local\\ClearMic-'+hashlib.sha256(str(DATA).encode()).hexdigest()[:16])
    if not handle:raise OSError('Cannot create Clear Mic application instance')
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(handle);user=ctypes.WinDLL('user32');user.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p];user.FindWindowW.restype=ctypes.c_void_p
        window=user.FindWindowW(None,'Clear Mic')
        if window:
            user.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int];user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
            user.ShowWindow(window,9);user.SetForegroundWindow(window)
        return False
    atexit.register(lambda:kernel.CloseHandle(handle));return True
