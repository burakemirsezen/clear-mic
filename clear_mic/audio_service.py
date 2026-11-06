import ctypes,math,threading,time
from contextlib import contextmanager
from dataclasses import asdict,replace
import numpy as np
import sounddevice as sd
from .processor import Processor,FRAME,RATE
from .settings import Voice,voice_from
from .echo import EchoCanceller,SpeakerReference,physical_speaker
from .neural import NeuralEngine
from .fullband import FullbandEngine

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

def physical_microphone(name):
    return bool(name) and not any(word in name.lower() for word in ('streaming','cable','voicemeeter','virtual','clear mic'))

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
    def start(self,input_name,output_name,voice,speaker_name=None,preserve_voice=True,engine='classic'):
        if self.active:return
        if engine not in ('classic','fullband','neural_clean','neural_echo'):raise ValueError('Unknown audio engine')
        if not physical_microphone(input_name):raise ValueError('Choose your physical microphone as input to prevent a feedback loop.')
        if not any(word in output_name.lower() for word in ('streaming microphone','cable','voicemeeter','virtual','clear mic feed')):raise ValueError('Choose a virtual playback endpoint as output. Preview listening uses a separate device.')
        if speaker_name is not None and not physical_speaker(speaker_name):raise ValueError('Select the physical speakers you hear for echo cancellation.')
        self.configure(voice);self.stop_event.clear();self.stats={'status':'starting'}
        self.thread=threading.Thread(target=self._run,args=(input_name,output_name,speaker_name,preserve_voice,engine),daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
        if self.active:raise RuntimeError('The audio driver has not stopped yet. Please wait before restarting.')
    def _run(self,input_name,output_name,speaker_name,preserve_voice=True,engine='classic'):
        processor=None;reference=None;echo=None
        try:
            with com_apartment():
                inp=resolve(input_name,'input');out=resolve(output_name,'output')
                shaping=lambda voice:replace(voice,noise=0) if engine!='classic' else voice
                processor=Processor(shaping(self.pending[1]));applied=self.pending[0]
                if speaker_name is not None:reference=SpeakerReference(speaker_name)
                if engine=='fullband':echo=FullbandEngine(self.pending[1].fullband_strength,reference is not None,preserve_voice)
                elif engine!='classic':echo=NeuralEngine(engine)
                elif reference is not None:echo=EchoCanceller(preserve_voice)
                echo_result=np.empty(FRAME,np.float32)
                result=np.empty(FRAME,np.float32);frames=0;warnings=0;sum_ms=0;max_ms=0;clipped=0;deadline_misses=0;error=[]
                routing_note=''
                def callback(indata,outdata,count,timing,status):
                    nonlocal applied,frames,warnings,sum_ms,max_ms,clipped,deadline_misses
                    try:
                        begin=time.perf_counter()
                        if status:warnings+=1
                        if count!=FRAME:raise RuntimeError('Unsupported driver audio block size')
                        version,voice=self.pending
                        if version!=applied:
                            processor.configure(shaping(voice))
                            if engine=='fullband':echo.configure(voice.fullband_strength)
                            applied=version
                        signal=indata[:,0]
                        # Meter clipping before AEC, which could otherwise hide overloaded input.
                        raw_peak=float(np.max(np.abs(signal)));raw_clips=int(np.count_nonzero(np.abs(signal)>=.999))
                        reference_peak=0
                        if echo:
                            if not np.isfinite(signal).all():raise RuntimeError('Microphone returned invalid audio')
                            reference_peak=echo.process_live(signal,reference,echo_result);signal=echo_result
                        levels=processor.process(signal,result)
                        outdata[:]=result[:,None];frames+=1;clipped+=raw_clips
                        stats={'status':'running','input_db':db(raw_peak),'output_db':db(float(levels[1])),'compressor_gr':float(levels[2]),'limiter_gr':float(levels[3]),'automatic_gain_db':float(levels[5]),'frames':frames,'warnings':warnings,'clipped_samples':clipped,'reference_active':reference_peak>0,'reference_db':db(reference_peak),'reference_drops':int(reference.counters[0]) if reference else 0,'reference_discontinuities':int(reference.counters[1]) if reference else 0,'echo_delay_ms':float(echo.metrics[1]) if echo else 0}
                        stats['routing_note']=routing_note
                        stats['echo_processing']=bool(echo is not None and echo.metrics[2]>0)
                        stats['gate_input_db']=db(float(levels[7]));stats['gate_reduction_db']=float(levels[8])
                        stats['engine']=engine;stats['echo_enabled']=reference is not None
                        stats['enhancement_delay_ms']=echo.latency_samples/48 if engine!='classic' else 0
                        stats['dsp_delay_ms']=(processor.latency_samples+(echo.latency_samples if echo else 0))/48
                        elapsed=(time.perf_counter()-begin)*1000;sum_ms+=elapsed;max_ms=max(max_ms,elapsed)
                        if elapsed>FRAME/RATE*1000:deadline_misses+=1
                        stats.update(mean_ms=sum_ms/frames,max_ms=max_ms,processing_deadline_misses=deadline_misses)
                        self.stats=stats
                    except Exception as e:outdata.fill(0);error.append(str(e));raise sd.CallbackAbort
                stream,routing_note=open_route(inp,out,callback,output_name)
                with stream:
                    while stream.active and not self.stop_event.wait(.1):
                        if error:break
                    if error:raise RuntimeError(error[0])
                    if not self.stop_event.is_set():raise RuntimeError('Audio device disconnected or the stream stopped unexpectedly. Reconnect it, refresh devices and turn on the microphone again.')
                self.stats={**self.stats,'status':'stopped'}
        except Exception as e:self.stats={'status':'error','error':str(e)}
        finally:
            if processor:processor.close()
            if echo:echo.close()
            if reference:reference.close()

def record_preview(input_name,seconds=5,speaker_name=None):
    if not physical_microphone(input_name):raise ValueError('Choose your physical microphone before recording a preview.')
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
            data=sd.rec(int(seconds*RATE),samplerate=RATE,channels=1,dtype='float32',device=resolve(input_name,'input'),extra_settings=sd.WasapiSettings(auto_convert=True))
            if sd.wait():raise RuntimeError('Preview audio dropped samples. Try recording again.')
            return data[:,0].copy()
        finally:sd.stop()

def process_clip(signal,voice,reference=None,preserve_voice=True,engine='classic'):
    if engine not in ('classic','fullband','neural_clean','neural_echo'):raise ValueError('Unknown audio engine')
    signal=np.ascontiguousarray(signal,dtype=np.float32)
    if signal.ndim!=1 or not np.isfinite(signal).all():raise ValueError('Preview microphone audio must be finite and mono')
    has_reference=reference is not None
    if has_reference:
        reference=np.ascontiguousarray(reference,dtype=np.float32)
        if reference.shape!=(len(signal),2):raise ValueError('Preview reference length does not match microphone')
        if not np.isfinite(reference).all():raise ValueError('Preview speaker reference must be finite')
    shaping=replace(voice,noise=0) if engine!='classic' else voice
    processor=Processor(shaping);echo=None
    try:
        if engine=='fullband':echo=FullbandEngine(voice.fullband_strength,has_reference,preserve_voice)
        elif engine!='classic':echo=NeuralEngine(engine)
        elif has_reference:echo=EchoCanceller(preserve_voice)
        delay=processor.latency_samples+(echo.latency_samples if echo else 0)
        tail_frames=(delay+FRAME-1)//FRAME+2
        padded=np.pad(signal,(0,(-len(signal))%FRAME+FRAME*tail_frames));out=np.empty_like(padded)
        far=np.pad(reference,((0,len(padded)-len(signal)),(0,0))) if has_reference else None
        silence=np.zeros((FRAME,2),np.float32);clean=np.empty(FRAME,np.float32)
        for i in range(0,len(padded),FRAME):
            frame=padded[i:i+FRAME]
            if echo:echo.process(frame,far[i:i+FRAME] if has_reference else silence,clean);frame=clean
            processor.process(frame,out[i:i+FRAME])
    finally:
        processor.close()
        if echo:echo.close()
    # Compensate measured model, AEC, gate and limiter delays together.
    return out[delay:delay+len(signal)].copy()

def match_preview_level(original,processed):
    """Match Original to the processed speech level for a fair local A/B.

    Use the same voiced time regions in both files, rather than background noise
    or the largest single peak. Do not change the live stream or saved WAVs.
    """
    original=np.asarray(original,dtype=np.float32)
    count=len(original)//FRAME*FRAME
    if not count:return original.copy()
    energy=np.mean(original[:count].reshape(-1,FRAME).astype(np.float64)**2,axis=1)
    active=energy>max(float(np.max(energy))*10**(-18/10),10**(-55/10))
    if not np.any(active):return original.copy()
    x=original[:count].reshape(-1,FRAME)[active].astype(np.float64)
    y=np.asarray(processed[:count],np.float64).reshape(-1,FRAME)[active]
    gain=min(10**(18/20),np.sqrt(np.mean(y*y)/max(np.mean(x*x),1e-18)))
    gain=min(gain,10**(-1/20)/max(float(np.max(np.abs(original))),1e-9))
    return np.asarray(original*gain,np.float32)
