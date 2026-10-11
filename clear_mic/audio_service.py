import ctypes,math,threading,time
from contextlib import contextmanager
from dataclasses import asdict
import numpy as np
import sounddevice as sd
from .processor import Processor,FRAME,RATE
from .settings import Voice,voice_from

@contextmanager
def com_apartment():
    ole=ctypes.WinDLL('ole32');ole.CoInitializeEx.argtypes=[ctypes.c_void_p,ctypes.c_uint32];ole.CoInitializeEx.restype=ctypes.c_long
    status=ole.CoInitializeEx(None,2)
    if status<0 and status!=-2147417850:raise RuntimeError('Windows could not initialize microphone access')
    try:yield
    finally:
        if status>=0:ole.CoUninitialize()

def devices():
    apis=sd.query_hostapis();result={'input':[],'output':[]}
    for i,d in enumerate(sd.query_devices()):
        if apis[d['hostapi']]['name']!='Windows WASAPI':continue
        if d['max_input_channels']:result['input'].append((d['name'],i))
        if d['max_output_channels']:result['output'].append((d['name'],i))
    return result

def resolve(name,kind):
    matches=[i for label,i in devices()[kind] if label==name]
    if len(matches)!=1:raise RuntimeError(f'{name or "Selected device"} is unavailable. Refresh devices and choose it again.')
    return matches[0]

def db(value):return max(-60,20*math.log10(max(value,1e-9)))

class AudioService:
    def __init__(self):
        self.thread=None;self.stop_event=threading.Event();self.stats={'status':'stopped'};self.pending=(0,Voice());self.version=0
    @property
    def active(self):return bool(self.thread and self.thread.is_alive())
    def configure(self,voice):
        self.version+=1;self.pending=(self.version,voice_from(asdict(voice)))
    def start(self,input_name,output_name,voice):
        if self.active:return
        if any(word in input_name.lower() for word in ('streaming microphone','cable output','voicemeeter','virtual')):raise ValueError('Choose your physical microphone as input to prevent a feedback loop.')
        if not any(word in output_name.lower() for word in ('streaming microphone','cable','voicemeeter','virtual')):raise ValueError('Choose a virtual playback endpoint as output. Preview listening uses a separate device.')
        self.configure(voice);self.stop_event.clear();self.stats={'status':'starting'}
        self.thread=threading.Thread(target=self._run,args=(input_name,output_name),daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
        if self.active:raise RuntimeError('The audio driver has not stopped yet. Please wait before restarting.')
    def _run(self,input_name,output_name):
        processor=None
        try:
            with com_apartment():
                inp=resolve(input_name,'input');out=resolve(output_name,'output');processor=Processor(self.pending[1]);applied=self.pending[0]
                result=np.empty(FRAME,np.float32);frames=0;warnings=0;sum_ms=0;max_ms=0;clipped=0;error=[]
                def callback(indata,outdata,count,timing,status):
                    nonlocal applied,frames,warnings,sum_ms,max_ms,clipped
                    try:
                        if status:warnings+=1
                        if count!=FRAME:raise RuntimeError('Unsupported driver audio block size')
                        version,voice=self.pending
                        if version!=applied:processor.configure(voice);applied=version
                        begin=time.perf_counter();levels=processor.process(indata[:,0],result);elapsed=(time.perf_counter()-begin)*1000
                        outdata[:]=result[:,None];frames+=1;sum_ms+=elapsed;max_ms=max(max_ms,elapsed);clipped+=int(levels[4])
                        self.stats={'status':'running','input_db':db(float(levels[0])),'output_db':db(float(levels[1])),'compressor_gr':float(levels[2]),'limiter_gr':float(levels[3]),'frames':frames,'warnings':warnings,'mean_ms':sum_ms/frames,'max_ms':max_ms,'clipped_samples':clipped}
                    except Exception as e:outdata.fill(0);error.append(str(e));raise sd.CallbackAbort
                extra=(sd.WasapiSettings(auto_convert=True),sd.WasapiSettings(auto_convert=True));channels=min(2,sd.query_devices(out)['max_output_channels'])
                with sd.Stream(device=(inp,out),samplerate=RATE,blocksize=FRAME,channels=(1,channels),dtype='float32',latency='low',extra_settings=extra,callback=callback) as stream:
                    while stream.active and not self.stop_event.wait(.1):
                        if error:break
                    if error:raise RuntimeError(error[0])
                self.stats={**self.stats,'status':'stopped'}
        except Exception as e:self.stats={'status':'error','error':str(e)}
        finally:
            if processor:processor.close()

def record_preview(input_name,seconds=5):
    with com_apartment():
        try:
            data=sd.rec(int(seconds*RATE),samplerate=RATE,channels=1,dtype='float32',device=resolve(input_name,'input'),extra_settings=sd.WasapiSettings(auto_convert=True));sd.wait();return data[:,0].copy()
        finally:sd.stop()

def process_clip(signal,voice):
    padded=np.pad(np.ascontiguousarray(signal,dtype=np.float32),(0,(-len(signal))%FRAME+FRAME*5));out=np.empty_like(padded)
    processor=Processor(voice)
    try:
        for i in range(0,len(padded),FRAME):processor.process(padded[i:i+FRAME],out[i:i+FRAME])
    finally:processor.close()
    delay=(960 if voice.noise else 0)+(96 if voice.limiter else 0)
    return out[delay:delay+len(signal)].copy()
