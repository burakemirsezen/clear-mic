"""Measure round-trip delay through the Clear Mic virtual cable.

Plays short chirps into the cable's playback end and records its recording end
in one shared-WASAPI duplex stream, the same way the live route opens devices.
Only virtual endpoints are opened: nothing is played on real speakers.
The result covers the cable buffer plus Windows stream buffering, which is the
delay a calling app adds on top of Clear Mic's fixed DSP delay.
"""
import json,sys
import numpy as np
import sounddevice as sd

RATE=48000;FRAME=480

def find(fragment,kind):
    api=next(i for i,a in enumerate(sd.query_hostapis()) if a['name']=='Windows WASAPI')
    for i,d in enumerate(sd.query_devices()):
        if d['hostapi']==api and fragment in d['name'] and d[f'max_{kind}_channels']>0 and '16 Ch' not in d['name']:return i,d['name']
    raise SystemExit(f'No WASAPI {kind} device containing {fragment!r}')

def measure(seconds=6,latency='low'):
    out,out_name=find('Clear Mic (VB-Audio Virtual Cable)','output');inp,in_name=find('CABLE Output (Clear Mic','input')
    t=np.arange(int(.02*RATE))/RATE;chirp=(np.sin(2*np.pi*(500*t+60000*t*t))*np.hanning(len(t))*.5).astype(np.float32)
    play=np.zeros(seconds*RATE,np.float32);starts=list(range(RATE,len(play)-RATE,RATE//2))
    for s in starts:play[s:s+len(chirp)]=chirp
    rec=np.zeros_like(play);pos=[0]
    def callback(indata,outdata,frames,time,status):
        i=pos[0];n=min(frames,len(play)-i)
        outdata[:]=0;outdata[:n,0]=play[i:i+n];rec[i:i+n]=indata[:n,0];pos[0]+=frames
        if pos[0]>=len(play):raise sd.CallbackStop
    out_channels=sd.query_devices(out)['max_output_channels']
    with sd.Stream(device=(inp,out),samplerate=RATE,blocksize=FRAME,channels=(1,min(2,out_channels)),dtype='float32',latency=latency,
                   extra_settings=(sd.WasapiSettings(auto_convert=True),sd.WasapiSettings(auto_convert=True)),callback=callback) as stream:
        reported=stream.latency
        while stream.active:sd.sleep(100)
    delays=[]
    for s in starts:
        seg=rec[s:s+RATE//2]
        if np.max(np.abs(seg))<1e-4:continue
        corr=np.correlate(seg,chirp,'valid');delays.append(int(np.argmax(np.abs(corr))))
    if not delays:raise SystemExit('No chirps came back. Is the Clear Mic cable installed and not muted?')
    return {'output':out_name,'input':in_name,'roundtrip_ms_median':round(float(np.median(delays))/48,1),'roundtrip_ms_min':round(min(delays)/48,1),
            'roundtrip_ms_max':round(max(delays)/48,1),'stream_reported_ms':[round(v*1000,1) for v in reported],'chirps':len(delays)}

if __name__=='__main__':
    print(json.dumps(measure(),indent=2))
