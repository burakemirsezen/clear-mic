"""Streaming LocalVQE with a fixed-delay, anti-aliased 48↔16 kHz adapter."""
import ctypes as C
import hashlib,os
import numpy as np
from .processor import ROOT,FP,FRAME

MODELS={
    'neural_clean':('localvqe-v1.3-4.8M-f32.gguf','c4f7912485c32cfc206c536f2f050b52513f2f613fdbc616391f6b26ab1d51ec'),
    'neural_echo':('localvqe-v1.4-aec-200K-f32.gguf','b6e43138588a83bfe903ab5e143b4020b91c1e1629f5a575ac5855ff0003c731')}

class NeuralEngine:
    def __init__(self,mode='neural_clean',threads=None):
        self.state=None;self.directory=None
        if mode not in MODELS:raise ValueError('Unknown neural engine')
        if threads is None:threads=min(os.cpu_count() or 2,4 if mode=='neural_clean' else 2)
        folder=ROOT/'vendor/neural';name,digest=MODELS[mode];model=folder/name
        if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest()!=digest:raise RuntimeError('Neural voice model is missing or modified. Extract the complete updated app folder.')
        try:
            self.directory=os.add_dll_directory(str(folder));self.lib=C.CDLL(str(folder/'cm_neural.dll'))
            for name,args,result in [('cm_neural_create',[C.c_char_p,C.c_int],C.c_void_p),('cm_neural_error',[],C.c_char_p),('cm_neural_destroy',[C.c_void_p],None),('cm_neural_process',[C.c_void_p,FP,FP,FP],C.c_int),('cm_neural_latency',[],C.c_uint)]:
                fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=result
            self.state=self.lib.cm_neural_create(str(model).encode('utf-8'),threads)
            if not self.state:raise RuntimeError(self.lib.cm_neural_error().decode('utf-8','replace'))
            self.latency_samples=int(self.lib.cm_neural_latency());self.metrics=np.zeros(3,np.float32)
            self.silence=np.zeros((FRAME,2),np.float32)
        except Exception:self.close();raise
    def process(self,mic,reference,output):
        if not self.state:raise RuntimeError('Neural engine is closed')
        if mic.shape!=(FRAME,) or reference.shape!=(FRAME,2) or output.shape!=(FRAME,):raise ValueError('Neural processing needs 480-sample microphone/output and stereo reference frames')
        if any(x.dtype!=np.float32 or not x.flags.c_contiguous for x in (mic,reference,output)) or not output.flags.writeable:raise ValueError('Use contiguous float32 neural frames')
        status=self.lib.cm_neural_process(self.state,mic.ctypes.data_as(FP),reference.ctypes.data_as(FP),output.ctypes.data_as(FP))
        if status:raise RuntimeError(self.lib.cm_neural_error().decode('utf-8','replace'))
    def process_live(self,mic,reference,output):
        far=reference.read() if reference is not None else self.silence
        peak=float(np.max(np.abs(far)));self.process(mic,far,output)
        self.metrics[2]=float(peak>.0031622777)
        return peak
    def close(self):
        if self.state:self.lib.cm_neural_destroy(self.state);self.state=None
        if self.directory:self.directory.close();self.directory=None
