import ctypes,math,threading,time
from contextlib import contextmanager
from dataclasses import asdict
import numpy as np
import sounddevice as sd
from .processor import Processor,FRAME,RATE
from .settings import Voice,voice_from
from .echo import EchoCanceller,SpeakerReference,physical_speaker

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

def open_route(inp,out,callback,output_name):
    def create(index):
        channels=min(2,sd.query_devices(index)['max_output_channels'])
        return sd.Stream(device=(inp,index),samplerate=RATE,blocksize=FRAME,channels=(1,channels),dtype='float32',latency='low',extra_settings=(sd.WasapiSettings(auto_convert=True),sd.WasapiSettings(auto_convert=True)),callback=callback)
    try:return create(out),''
    except sd.PortAudioError:
        # Some VB-CABLE endpoint configurations reject the stereo playback client
        # while the 16-channel feed to the same owned cable remains usable.
        if output_name!='Speakers (Clear Mic (VB-Audio Virtual Cable))':raise
        compatible='CABLE In 16 Ch (Clear Mic (VB-Audio Virtual Cable))'
        try:alternative=resolve(compatible,'output')
        except RuntimeError:raise RuntimeError('Clear Mic playback is unavailable. Refresh devices or restart Windows.')
        return create(alternative),'Using the compatible Clear Mic playback feed.'

class AudioService:
    def __init__(self):
        self.thread=None;self.stop_event=threading.Event();self.stats={'status':'stopped'};self.pending=(0,Voice());self.version=0
    @property
    def active(self):return bool(self.thread and self.thread.is_alive())
    def configure(self,voice):
        self.version+=1;self.pending=(self.version,voice_from(asdict(voice)))
    def start(self,input_name,output_name,voice,speaker_name=None):
        if self.active:return
        if any(word in input_name.lower() for word in ('streaming microphone','cable output','voicemeeter','virtual','clear mic')):raise ValueError('Choose your physical microphone as input to prevent a feedback loop.')
        if not any(word in output_name.lower() for word in ('streaming microphone','cable','voicemeeter','virtual','clear mic feed')):raise ValueError('Choose a virtual playback endpoint as output. Preview listening uses a separate device.')
        if speaker_name is not None and not physical_speaker(speaker_name):raise ValueError('Select the physical speakers you hear for echo cancellation.')
        self.configure(voice);self.stop_event.clear();self.stats={'status':'starting'}
        self.thread=threading.Thread(target=self._run,args=(input_name,output_name,speaker_name),daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
        if self.active:raise RuntimeError('The audio driver has not stopped yet. Please wait before restarting.')
    def _run(self,input_name,output_name,speaker_name):
        processor=None;reference=None;echo=None
        try:
            with com_apartment():
                inp=resolve(input_name,'input');out=resolve(output_name,'output');processor=Processor(self.pending[1]);applied=self.pending[0]
                if speaker_name is not None:reference=SpeakerReference(speaker_name);echo=EchoCanceller()
                echo_result=np.empty(FRAME,np.float32)
                result=np.empty(FRAME,np.float32);frames=0;warnings=0;sum_ms=0;max_ms=0;clipped=0;error=[]
                routing_note=''
                def callback(indata,outdata,count,timing,status):
                    nonlocal applied,frames,warnings,sum_ms,max_ms,clipped
                    try:
                        if status:warnings+=1
                        if count!=FRAME:raise RuntimeError('Unsupported driver audio block size')
                        version,voice=self.pending
                        if version!=applied:processor.configure(voice);applied=version
                        begin=time.perf_counter();signal=indata[:,0]
                        # Meter clipping before AEC, which could otherwise hide overloaded input.
                        raw_peak=float(np.max(np.abs(signal)));raw_clips=int(np.count_nonzero(np.abs(signal)>=.999))
                        reference_peak=0
                        if echo:
                            if not np.isfinite(signal).all():raise RuntimeError('Microphone returned invalid audio')
                            reference_peak=echo.process_live(signal,reference,echo_result);signal=echo_result
                        levels=processor.process(signal,result);elapsed=(time.perf_counter()-begin)*1000
                        outdata[:]=result[:,None];frames+=1;sum_ms+=elapsed;max_ms=max(max_ms,elapsed);clipped+=raw_clips
                        self.stats={'status':'running','input_db':db(raw_peak),'output_db':db(float(levels[1])),'compressor_gr':float(levels[2]),'limiter_gr':float(levels[3]),'automatic_gain_db':float(levels[5]),'frames':frames,'warnings':warnings,'mean_ms':sum_ms/frames,'max_ms':max_ms,'clipped_samples':clipped,'echo_enabled':bool(echo),'reference_active':reference_peak>0,'reference_db':db(reference_peak),'reference_drops':int(reference.counters[0]) if reference else 0,'reference_discontinuities':int(reference.counters[1]) if reference else 0,'echo_delay_ms':float(echo.metrics[1]) if echo else 0}
                        self.stats['routing_note']=routing_note
                    except Exception as e:outdata.fill(0);error.append(str(e));raise sd.CallbackAbort
                stream,routing_note=open_route(inp,out,callback,output_name)
                with stream:
                    while stream.active and not self.stop_event.wait(.1):
                        if error:break
                    if error:raise RuntimeError(error[0])
                self.stats={**self.stats,'status':'stopped'}
        except Exception as e:self.stats={'status':'error','error':str(e)}
        finally:
            if processor:processor.close()
            if echo:echo.close()
            if reference:reference.close()

def record_preview(input_name,seconds=5,speaker_name=None):
    if speaker_name is not None:
        count=int(seconds*RATE);raw=np.zeros(count,np.float32);far=np.zeros((count,2),np.float32);position=0;errors=[]
        with com_apartment():
            reference=SpeakerReference(speaker_name)
            try:
                def capture(data,n,timing,status):
                    nonlocal position
                    try:
                        if n!=FRAME:raise RuntimeError('Unsupported preview frame size')
                        if status:raise RuntimeError('Preview audio dropped samples. Try recording again.')
                        take=min(n,count-position);raw[position:position+take]=data[:take,0];far[position:position+take]=reference.read()[:take];position+=take
                        if position>=count:raise sd.CallbackStop
                    except sd.CallbackStop:raise
                    except Exception as e:errors.append(str(e));raise sd.CallbackAbort
                with sd.InputStream(device=resolve(input_name,'input'),samplerate=RATE,blocksize=FRAME,channels=1,dtype='float32',latency='low',extra_settings=sd.WasapiSettings(auto_convert=True),callback=capture) as stream:
                    end=time.monotonic()+seconds+3
                    while stream.active and time.monotonic()<end:time.sleep(.02)
                    if errors:raise RuntimeError(errors[0])
                    if position<count:raise RuntimeError('Preview recording did not finish')
                return raw,far
            finally:reference.close()
    with com_apartment():
        try:
            data=sd.rec(int(seconds*RATE),samplerate=RATE,channels=1,dtype='float32',device=resolve(input_name,'input'),extra_settings=sd.WasapiSettings(auto_convert=True));sd.wait();return data[:,0].copy()
        finally:sd.stop()

def process_clip(signal,voice,reference=None):
    padded=np.pad(np.ascontiguousarray(signal,dtype=np.float32),(0,(-len(signal))%FRAME+FRAME*5));out=np.empty_like(padded)
    processor=Processor(voice);echo=None
    if reference is not None:
        if reference.shape!=(len(signal),2):processor.close();raise ValueError('Preview reference length does not match microphone')
        far=np.pad(np.ascontiguousarray(reference,dtype=np.float32),((0,len(padded)-len(signal)),(0,0)))
        try:echo=EchoCanceller()
        except Exception:processor.close();raise
        clean=np.empty(FRAME,np.float32)
    try:
        for i in range(0,len(padded),FRAME):
            frame=padded[i:i+FRAME]
            if echo:echo.process(frame,far[i:i+FRAME],clean);frame=clean
            processor.process(frame,out[i:i+FRAME])
    finally:
        processor.close()
        if echo:echo.close()
    # Measured impulse delay of AEC3's 48 kHz splitting/merging and block framing.
    delay=(960 if voice.noise else 0)+(96 if voice.limiter else 0)+(430 if echo is not None else 0)
    return out[delay:delay+len(signal)].copy()
