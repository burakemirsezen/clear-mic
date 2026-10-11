import ctypes as C
import os
from dataclasses import asdict
import numpy as np
from .paths import ROOT
from .settings import Voice
FRAME=480;RATE=48000;FP=C.POINTER(C.c_float)
_dll_directory=os.add_dll_directory(str(ROOT/'vendor'))
class Config(C.Structure):
    _fields_=[(name,C.c_int if name in ('noise','highpass','compressor','limiter','auto_level') else C.c_float) for name in Voice.__dataclass_fields__]
class Processor:
    def __init__(self,voice=None):
        voice=(voice or Voice()).validate()
        self.lib=C.CDLL(str(ROOT/'vendor'/'clearmic_native.dll'))
        self.lib.cm_cpu_supported.argtypes=[];self.lib.cm_cpu_supported.restype=C.c_int
        if not self.lib.cm_cpu_supported():raise RuntimeError('This Windows build requires an x64 CPU with AVX2 support.')
        self.lib.cm_create.argtypes=[];self.lib.cm_create.restype=C.c_void_p
        self.lib.cm_destroy.argtypes=[C.c_void_p];self.lib.cm_destroy.restype=None
        self.lib.cm_configure.argtypes=[C.c_void_p,C.POINTER(Config)];self.lib.cm_configure.restype=C.c_int
        self.lib.cm_process.argtypes=[C.c_void_p,FP,FP,C.c_uint];self.lib.cm_process.restype=C.c_int
        self.lib.cm_stats.argtypes=[C.c_void_p,FP];self.lib.cm_stats.restype=None
        self.lib.cm_latency.argtypes=[C.c_void_p];self.lib.cm_latency.restype=C.c_uint
        self.state=self.lib.cm_create()
        if not self.state:raise RuntimeError('Cannot initialize voice processing')
        self.values=np.empty(7,np.float32)
        try:self.configure(voice)
        except Exception:self.close();raise
    def configure(self,voice):
        voice.validate();config=Config(**asdict(voice))
        if self.lib.cm_configure(self.state,C.byref(config)):raise ValueError('Invalid voice settings')
    def process(self,input,output):
        if not self.state:raise RuntimeError('Processor is closed')
        if input.dtype!=np.float32 or output.dtype!=np.float32 or input.size!=FRAME or output.size!=FRAME or not input.flags.c_contiguous or not output.flags.c_contiguous or not output.flags.writeable:raise ValueError('Use contiguous 480-sample float32 audio frames')
        status=self.lib.cm_process(self.state,input.ctypes.data_as(FP),output.ctypes.data_as(FP),FRAME)
        if status:raise RuntimeError(f'Audio processing failed: {status}')
        self.lib.cm_stats(self.state,self.values.ctypes.data_as(FP))
        return self.values
    def close(self):
        if self.state:self.lib.cm_destroy(self.state);self.state=None
