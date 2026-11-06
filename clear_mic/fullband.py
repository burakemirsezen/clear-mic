"""48 kHz enhancement, preserving full-band detail and the stereo echo path.

Streaming STFT/state initialization adapted from Ceva-IP DPDFNet 0.6.0,
Apache-2.0. Source/license and pinned weights: THIRD_PARTY/DPDFNet.
"""
import hashlib
import numpy as np
import onnxruntime as ort
from .processor import ROOT,FRAME,RATE
from .echo import EchoCanceller

MODEL='dpdfnet2_48khz_hr.onnx'
MODEL_SHA256='7f0575a5cec0ba4ffd8f8bd657e06d007e4ccdd955d76faab922b9d3291dc14b'
MODEL_DELAY=2400

def _validate_frames(mic,output):
    if not isinstance(mic,np.ndarray) or mic.shape!=(FRAME,) or mic.dtype!=np.float32:
        raise ValueError('Use a finite 480-sample full-band frame')
    if not isinstance(output,np.ndarray) or output.shape!=(FRAME,) or output.dtype!=np.float32 or not output.flags.writeable:
        raise ValueError('Use a writable float32 output frame')

class FullbandDenoiser:
    def __init__(self,threads=2):
        path=ROOT/'vendor/fullband'/MODEL
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_SHA256:
            raise RuntimeError('Full-band model is missing or modified. Extract the complete Clear Mic folder.')
        options=ort.SessionOptions();options.intra_op_num_threads=threads;options.inter_op_num_threads=1
        options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        options.add_session_config_entry('session.inter_op.allow_spinning','0')
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        metadata=self.session.get_modelmeta().custom_metadata_map
        self.initial_state=np.zeros(int(metadata['state_size']),np.float32)
        erb=int(metadata['erb_norm_state_size']);spec=int(metadata['spec_norm_state_size'])
        self.initial_state[:erb]=[float(v) for v in metadata['erb_norm_init'].split(',')]
        self.initial_state[erb:erb+spec]=[float(v) for v in metadata['spec_norm_init'].split(',')]
        self.inputs=[v.name for v in self.session.get_inputs()];self.outputs=[v.name for v in self.session.get_outputs()]
        if self.session.get_inputs()[0].shape[-2]!=481:raise RuntimeError('Expected the 48 kHz full-band model')
        n=np.arange(FRAME*2);self.window=np.sin(.5*np.pi*np.sin(np.pi*(n+.5)/(FRAME*2))**2).astype(np.float32)
        self.history=np.zeros(FRAME*2,np.float32);self.ola=np.zeros(FRAME*2,np.float32)
        self.analysis=np.empty(FRAME*2,np.float32);self.spectrum=np.empty((1,1,FRAME+1,2),np.float32)
        self.complex=np.empty(FRAME+1,np.complex128);self.time=np.empty(FRAME*2,np.float64)
        self.finite=np.empty(FRAME,np.bool_)
        self.state=self.initial_state.copy()
        # Allocate and warm ORT kernels before the audio callback starts.
        silence=np.zeros(FRAME,np.float32);discard=np.empty_like(silence)
        for _ in range(8):self.process(silence,discard)
        self.state=self.initial_state.copy();self.history.fill(0);self.ola.fill(0)
    def process(self,mic,output):
        if self.session is None:raise RuntimeError('Full-band denoiser is closed')
        _validate_frames(mic,output)
        if not np.isfinite(mic,out=self.finite).all():raise ValueError('Use a finite 480-sample full-band frame')
        self.history[:FRAME]=self.history[FRAME:];self.history[FRAME:]=mic
        np.multiply(self.history,self.window,out=self.analysis)
        np.fft.rfft(self.analysis,out=self.complex)
        self.spectrum[0,0,:,0]=self.complex.real;self.spectrum[0,0,:,1]=self.complex.imag
        enhanced,self.state=self.session.run(self.outputs,{self.inputs[0]:self.spectrum,self.inputs[1]:self.state})
        self.complex.real=enhanced[0,0,:,0];self.complex.imag=enhanced[0,0,:,1]
        np.fft.irfft(self.complex,n=FRAME*2,out=self.time)
        # Reuse analysis storage after inference: avoid two synthesis temporaries
        # and a fresh boolean array on every 10 ms audio callback.
        np.multiply(self.time,self.window,out=self.analysis,casting='unsafe')
        np.add(self.ola,self.analysis,out=self.ola)
        output[:]=self.ola[:FRAME];self.ola[:FRAME]=self.ola[FRAME:];self.ola[FRAME:]=0
        if not np.isfinite(output,out=self.finite).all():raise RuntimeError('Full-band model returned invalid audio')
    def close(self):self.session=None

class FullbandEngine:
    def __init__(self,strength=65,echo_enabled=False,preserve_voice=True,echo_tuning=None):
        self.echo=None;self.core=None
        self.configure(strength)
        try:
            if echo_enabled:self.echo=EchoCanceller(preserve_voice,echo_tuning)
            self.core=FullbandDenoiser()
        except Exception:self.close();raise
        self.echoed=np.empty(FRAME,np.float32);self.wet=np.empty(FRAME,np.float32);self.dry=np.empty(FRAME,np.float32)
        self.delay=np.zeros((MODEL_DELAY//FRAME,FRAME),np.float32);self.index=0
        self.mix=np.empty(FRAME,np.float32);self.ramp=np.linspace(0,1,FRAME,dtype=np.float32);self.metrics=np.zeros(3,np.float32);self.finite=np.empty(FRAME,np.bool_)
        self.current_mix=self.strength/100
        self.latency_samples=MODEL_DELAY+(self.echo.latency_samples if self.echo else 0)
    def configure(self,strength):
        value=float(strength)
        if not np.isfinite(value) or not 0<=value<=100:raise ValueError('Full-band noise strength must be between 0 and 100')
        self.strength=value
    def _denoise(self,signal,output):
        # Input validation must finish before the dry ring advances. Otherwise a
        # rejected nonfinite frame poisons later dry output and moves its timeline.
        self.core.process(signal,self.wet)
        self.dry[:]=self.delay[self.index];self.delay[self.index]=signal;self.index=(self.index+1)%len(self.delay)
        target=self.strength/100;end=self.current_mix+max(-.5,min(.5,target-self.current_mix))
        if end==self.current_mix:
            if end==0:np.copyto(output,self.dry);return
            if end==1:np.copyto(output,self.wet);return
            self.mix.fill(end)
        else:
            np.multiply(self.ramp,end-self.current_mix,out=self.mix);np.add(self.mix,self.current_mix,out=self.mix)
            self.current_mix=end
        np.subtract(self.wet,self.dry,out=output);output*=self.mix;output+=self.dry
    def process(self,mic,reference,output):
        if self.core is None:raise RuntimeError('Full-band engine is closed')
        _validate_frames(mic,output)
        signal=mic
        if self.echo:self.echo.process(mic,reference,self.echoed);signal=self.echoed;self.metrics[:]=self.echo.metrics
        self._denoise(signal,output)
    def process_live(self,mic,reference,output):
        if self.core is None:raise RuntimeError('Full-band engine is closed')
        _validate_frames(mic,output)
        peak=0;signal=mic
        if self.echo:
            if not np.isfinite(mic,out=self.finite).all():raise ValueError('Use a finite 480-sample full-band frame')
            peak=self.echo.process_live(mic,reference,self.echoed);signal=self.echoed;self.metrics[:]=self.echo.metrics
        self._denoise(signal,output);return peak
    def close(self):
        if self.core:self.core.close();self.core=None
        if self.echo:self.echo.close();self.echo=None
