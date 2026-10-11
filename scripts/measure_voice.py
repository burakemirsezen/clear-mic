"""Deterministic CPU/AEC/leveler regression measurements; no devices or recordings."""
import json,time,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from clear_mic.echo import EchoCanceller
from clear_mic.processor import Processor,FRAME,RATE
from clear_mic.settings import Voice

def speech(seconds=12):
    t=np.arange(int(seconds*RATE))/RATE
    x=sum(a*np.sin(2*np.pi*120*(h+1)*t) for h,a in enumerate([1,.7,.5,.4,.35,.3,.25,.2,.15]))
    x*=.15+.85*np.maximum(0,np.sin(2*np.pi*3*t))
    return np.asarray(x/np.max(np.abs(x)),np.float32)
def frames(processor,x):
    y=np.empty_like(x);times=[];gains=[]
    for i in range(0,len(x),FRAME):
        start=time.perf_counter();stats=processor.process(x[i:i+FRAME],y[i:i+FRAME]);times.append((time.perf_counter()-start)*1000);gains.append(float(stats[5]))
    return y,times,gains
def rms(x):return float(np.sqrt(np.mean(np.asarray(x,np.float64)**2)))
def db(x):return float(20*np.log10(max(x,1e-12)))
def echo_run(mic,reference):
    p=EchoCanceller();output=np.empty_like(mic);times=[]
    try:
        for i in range(0,len(mic),FRAME):
            start=time.perf_counter();p.process(mic[i:i+FRAME],reference[i:i+FRAME],output[i:i+FRAME]);times.append((time.perf_counter()-start)*1000)
    finally:p.close()
    return output,times
def measure():
    rng=np.random.default_rng(7);n=RATE*12
    # Independent stereo channels, band-limited noise and several delayed reflections.
    ref=rng.normal(0,.06,(n,2));ref=(ref+np.roll(ref,1,axis=0)+np.roll(ref,2,axis=0))/3
    ref=np.asarray(ref,np.float32);echo=np.zeros(n,np.float32)
    for delay,gain,ch in [(2400,.55,0),(3400,.2,1),(4200,.1,0)]:echo[delay:]+=ref[:-delay,ch]*gain
    clean,times=echo_run(echo,ref);tail=slice(RATE*9,None)
    attenuation=db(rms(echo[tail])/max(rms(clean[tail]),1e-12))
    # Near-end preservation during simultaneous playback; cancel the same echo-only run
    # to isolate the surviving near-end component, then account for fixed filter delay.
    near=speech()*.08;near[:RATE*5]=0
    mixed,_=echo_run(echo+near,ref);surviving=mixed-clean
    lag_scores=[float(np.dot(near[RATE*8:-512],surviving[RATE*8+d:len(near)-512+d])) for d in range(512)]
    lag=int(np.argmax(lag_scores));a=near[RATE*8:-512];b=surviving[RATE*8+lag:len(near)-512+lag]
    corr=float(np.corrcoef(a,b)[0,1]);voice_change=db(rms(b)/rms(a))
    base=Voice(noise=0,highpass=0,compressor=0,limiter=1,auto_level=1)
    agc={}
    for level in (-42,-30,-18):
        x=speech()*10**(level/20);p=Processor(base)
        try:y,_,gain=frames(p,x)
        finally:p.close()
        agc[str(level)]={'input_rms_db':db(rms(x[-RATE*3:])),'output_rms_db':db(rms(y[-RATE*3:])),'final_gain_db':gain[-1],'peak_db':db(float(np.max(np.abs(y))))}
    noise=np.asarray(rng.normal(0,10**(-52/20),n),np.float32);p=Processor(base)
    try:noise_out,_,gains=frames(p,noise)
    finally:p.close()
    p=Processor(Voice());_,full_times,_=frames(p,speech()*.05);p.close()
    result={'scope':'Deterministic synthetic signals, no Discord comparison or physical acoustic measurement',
        'echo_attenuation_db':attenuation,'double_talk_voice_correlation':corr,'double_talk_voice_change_db':voice_change,'aec_alignment_samples':lag,
        'aec_mean_ms':float(np.mean(times)),'aec_p95_ms':float(np.percentile(times,95)),
        'full_chain_mean_ms':float(np.mean(full_times)),'full_chain_p95_ms':float(np.percentile(full_times,95)),
        'agc_speech':agc,'agc_noise_output_db':db(rms(noise_out[-RATE*3:])),'agc_noise_final_gain_db':gains[-1]}
    return result
if __name__=='__main__':
    value=measure();print(json.dumps(value,indent=2))
    if len(sys.argv)>1:
        target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(value,indent=2))
