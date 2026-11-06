"""Local WebRTC AEC3 and Windows speaker reference. No audio is saved here."""
import ctypes as C
import numpy as np
from .processor import FP,FRAME,ROOT

def physical_speaker(name):
    return bool(name) and not any(w in name.lower() for w in ('clear mic','virtual','cable','voicemeeter','streaming microphone','streaming speakers'))

class EchoCanceller:
    # Measured AEC3 split-band/processing impulse delay at the fixed 48 kHz rate.
    latency_samples=430
    def __init__(self,preserve_voice=True,tuning=None):
        self.lib=C.CDLL(str(ROOT/'vendor/cm_aec3.dll'))
        self.lib.cm_echo_create.argtypes=[];self.lib.cm_echo_create.restype=C.c_void_p
        self.lib.cm_echo_destroy.argtypes=[C.c_void_p];self.lib.cm_echo_destroy.restype=None
        self.lib.cm_echo_process.argtypes=[C.c_void_p,FP,FP,FP,C.c_int];self.lib.cm_echo_process.restype=C.c_int
        self.lib.cm_echo_metrics.argtypes=[C.c_void_p,FP];self.lib.cm_echo_metrics.restype=None
        self.lib.cm_echo_render.argtypes=[C.c_void_p,FP];self.lib.cm_echo_render.restype=C.c_int
        self.lib.cm_echo_capture.argtypes=[C.c_void_p,FP,FP,C.c_int];self.lib.cm_echo_capture.restype=C.c_int
        if tuning is not None:
            # (filter_blocks, split_upper_bands, upper_band_natural_voice) for measurements.
            self.lib.cm_echo_create_tuned.argtypes=[C.c_int]*4;self.lib.cm_echo_create_tuned.restype=C.c_void_p
            self.state=self.lib.cm_echo_create_tuned(int(preserve_voice),*map(int,tuning))
        elif preserve_voice:self.state=self.lib.cm_echo_create()
        else:
            self.lib.cm_echo_create_with_protection.argtypes=[C.c_int];self.lib.cm_echo_create_with_protection.restype=C.c_void_p
            self.state=self.lib.cm_echo_create_with_protection(0)
        self.metrics=np.zeros(3,np.float32)
        if not self.state:raise RuntimeError('Cannot initialize speaker echo cancellation')
        self.silence=np.zeros((FRAME,2),np.float32)
    @staticmethod
    def _validate_frame(value,shape):
        if not isinstance(value,np.ndarray) or value.dtype!=np.float32 or value.shape!=shape or not value.flags.c_contiguous:
            raise ValueError('Echo cancellation needs contiguous float32 10 ms frames')
    def _validate_capture(self,mic,output):
        if not self.state:raise RuntimeError('Echo canceller is closed')
        self._validate_frame(mic,(FRAME,));self._validate_frame(output,(FRAME,))
        if not output.flags.writeable:raise ValueError('Echo output must be writable')
        if not np.isfinite(mic).all():raise ValueError('Nonfinite echo input')
    def _validate_reference(self,reference):
        self._validate_frame(reference,(FRAME,2))
        if not np.isfinite(reference).all():raise ValueError('Nonfinite echo input')
    def process(self,mic,reference,output):
        self._validate_capture(mic,output);self._validate_reference(reference)
        if self.lib.cm_echo_process(self.state,mic.ctypes.data_as(FP),reference.ctypes.data_as(FP),output.ctypes.data_as(FP),0):raise RuntimeError('Echo cancellation failed')
        self.lib.cm_echo_metrics(self.state,self.metrics.ctypes.data_as(FP))
    def process_live(self,mic,reference,output):
        # Reject invalid capture buffers before reading playback or advancing AEC.
        self._validate_capture(mic,output)
        # Drain fresh playback blocks before the capture block. Independent hardware
        # clocks and Windows packet sizes need not yield exactly one render per capture.
        rendered=0;peak=0
        for _ in range(8):
            samples=reference.read()
            if not reference.active:break
            self._validate_reference(samples)
            peak=max(peak,float(np.max(np.abs(samples))));rendered+=1
            if self.lib.cm_echo_render(self.state,samples.ctypes.data_as(FP)):raise RuntimeError('Speaker reference processing failed')
        if not rendered:
            if self.lib.cm_echo_render(self.state,self.silence.ctypes.data_as(FP)):raise RuntimeError('Speaker reference processing failed')
        if self.lib.cm_echo_capture(self.state,mic.ctypes.data_as(FP),output.ctypes.data_as(FP),0):raise RuntimeError('Echo cancellation failed')
        self.lib.cm_echo_metrics(self.state,self.metrics.ctypes.data_as(FP))
        return peak
    def close(self):
        if self.state:self.lib.cm_echo_destroy(self.state);self.state=None

class SpeakerReference:
    def __init__(self,name):
        if not physical_speaker(name):raise ValueError('Choose the physical speakers you hear, not the virtual microphone.')
        self.lib=C.CDLL(str(ROOT/'vendor/cm_reference.dll'))
        self.lib.cm_ref_create.argtypes=[C.c_char_p,C.c_char_p,C.c_uint];self.lib.cm_ref_create.restype=C.c_void_p
        self.lib.cm_ref_destroy.argtypes=[C.c_void_p];self.lib.cm_ref_destroy.restype=None
        self.lib.cm_ref_read.argtypes=[C.c_void_p,FP];self.lib.cm_ref_read.restype=C.c_int
        self.lib.cm_ref_stats.argtypes=[C.c_void_p,C.POINTER(C.c_uint)];self.lib.cm_ref_stats.restype=None
        error=C.create_string_buffer(1024);self.state=self.lib.cm_ref_create(name.encode('utf-8'),error,len(error))
        if not self.state:raise RuntimeError(error.value.decode('utf-8','replace') or 'Cannot capture speaker playback')
        self.samples=np.zeros((FRAME,2),np.float32);self.counters=(C.c_uint*2)();self.active=False
    def read(self):
        status=self.lib.cm_ref_read(self.state,self.samples.ctypes.data_as(FP))
        if status<0:raise RuntimeError('Speaker reference disconnected. Stop, refresh devices and select your speakers again.')
        self.active=status>0
        self.lib.cm_ref_stats(self.state,self.counters)
        return self.samples
    def close(self):
        if self.state:self.lib.cm_ref_destroy(self.state);self.state=None
