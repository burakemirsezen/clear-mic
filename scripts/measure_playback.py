"""Voice retention while real music plays through simulated speakers.

Usage: python scripts/measure_playback.py [MUSIC_FILE] [--report out.json] [--samples DIR]

The music file is any local track (stereo, any rate). It is played through a
simulated room (delay, decaying reverb, cheap-speaker lowpass and mild
saturation) into the microphone together with pinned upstream speech plus
synthetic 8.5-18 kHz detail. Every configuration receives identical input.
Voice retention is measured by projecting the output onto the clean voice,
so leftover music does not count as retained voice. Not a listening score.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from clear_mic.processor import FRAME,RATE
from clear_mic.fullband import FullbandEngine

SECONDS=20;WARM=6
BANDS=((100,300),(300,1000),(1000,3000),(3000,6000),(6000,8500),(8500,12000),(12000,18000))

def rms(x):return float(np.sqrt(np.mean(np.asarray(x,np.float64)**2)))
def db(x):return float(20*np.log10(max(x,1e-12)))

def resample(x,rate):
    if rate==RATE:return x.astype(np.float32)
    t=np.arange(round(len(x)*RATE/rate))*rate/RATE
    return np.stack([np.interp(t,np.arange(len(x)),x[:,c]) for c in range(x.shape[1])],axis=1).astype(np.float32)

def voice():
    x,rate=sf.read(ROOT/'vendor/webrtc-aec3/tests/near.wav',dtype='float32')
    if x.ndim>1:x=x[:,0]
    x=resample(x[:,None],rate)[:,0]
    x=np.tile(x,int(np.ceil(SECONDS*RATE/len(x))))[:SECONDS*RATE]
    n=len(x);rng=np.random.default_rng(7)
    spec=np.fft.rfft(rng.normal(0,1,n));hz=np.fft.rfftfreq(n,1/RATE);spec[(hz<8500)|(hz>18000)]=0
    detail=np.fft.irfft(spec,n=n);env=np.abs(np.convolve(x,np.ones(480)/480,'same'));detail*=env/max(env.max(),1e-9)
    x=x/rms(x)*.03;detail=detail/rms(detail)*.004
    out=(x+detail).astype(np.float32);out[:RATE*4]=0  # far-end only while AEC converges
    return out

def synthetic_music():
    """Deterministic broadband 'band': bass/chords plus hi-hat and cymbal noise to 16 kHz."""
    n=SECONDS*RATE;t=np.arange(n)/RATE;rng=np.random.default_rng(11)
    chords=sum(np.sin(2*np.pi*f*t+p) for f,p in zip((82.4,164.8,196,246.9,329.6,392),rng.uniform(0,6,6)))
    beat=(t*4)%1;hats=rng.normal(0,1,n)*np.exp(-beat*30);cym=rng.normal(0,1,n)*np.exp(-((t*.5)%1)*3)
    spec=np.fft.rfft(hats+.4*cym);hz=np.fft.rfftfreq(n,1/RATE);spec[(hz<5000)|(hz>16000)]=0
    high=np.fft.irfft(spec,n=n);high*=.5*rms(chords)/rms(high)
    left=chords+high;right=chords+np.roll(high,37)
    x=np.stack([left,right],1);return (x/rms(x)*.12).astype(np.float32)

def music(path=None,offset=45):
    if path is None:return synthetic_music()
    x,rate=sf.read(path,dtype='float32',start=int(offset*44100),frames=int((SECONDS+1)*44100))
    if x.ndim==1:x=np.stack([x,x],1)
    x=resample(x[:,:2],rate)[:SECONDS*RATE]
    return (x/rms(x)*.12).astype(np.float32)  # loud-ish playback level

def room(reference,delay=2600,echo_db=-6.):
    """Speaker output -> microphone: system/air delay, reverb tail, lowpass, saturation."""
    # Desk setup: direct path ~3 dB above early reflections + a 0.3 s RT60 tail.
    rng=np.random.default_rng(3);n=int(.3*RATE)
    tail=rng.normal(0,1,n)*np.exp(-np.arange(n)/(0.022*RATE));tail[:96]=0
    tail*=np.sqrt(.5/np.sum(tail**2));rir=tail;rir[0]+=1
    for d,g in ((140,.45),(310,-.3),(520,.22)):rir[d]+=g
    mono=reference.mean(1)
    driven=np.tanh(1.6*mono)/1.6  # mild monitor-speaker distortion
    spec=np.fft.rfft(driven);hz=np.fft.rfftfreq(len(driven),1/RATE);spec/=np.sqrt(1+(hz/9000)**4);spec*=np.sqrt(1/(1+(80/np.maximum(hz,1))**4))
    driven=np.fft.irfft(spec,n=len(driven))
    wet=np.convolve(driven,rir)[:len(driven)]
    out=np.zeros_like(wet);out[delay:]=wet[:-delay]
    return (out*10**(echo_db/20)*rms(mono)/max(rms(out),1e-12)).astype(np.float32)

def run(engine,mic,reference):
    y=np.empty_like(mic)
    try:
        for i in range(0,len(mic)-FRAME+1,FRAME):engine.process(mic[i:i+FRAME],reference[i:i+FRAME],y[i:i+FRAME])
    finally:engine.close()
    return y,engine.latency_samples

def scores(target,echo,y,latency):
    a=target[RATE*WARM:len(y)-latency].astype(np.float64);b=y[RATE*WARM+latency:].astype(np.float64)
    A=np.fft.rfft(a);B=np.fft.rfft(b);hz=np.fft.rfftfreq(len(a),1/RATE);bands={}
    for lo,hi in BANDS:
        m=(hz>=lo)&(hz<hi);bands[f'{lo}-{hi}']=round(db(abs(np.real(np.vdot(A[m],B[m])))/np.sum(abs(A[m])**2)),1)
    scale=float(np.dot(a,b)/np.dot(a,a));err=b-scale*a
    quiet=np.convolve(a*a,np.ones(4800)/4800,'same')<1e-7  # voice pauses (100 ms energy)
    e=echo[RATE*WARM:len(y)-latency]
    return {'voice_gain_db':round(db(abs(scale)),1),'si_sdr_db':round(db(rms(scale*a)/max(rms(err),1e-12)),1),
            'music_left_in_pauses_db':round(db(rms(b[quiet])/max(rms(e[quiet]),1e-12)),1) if quiet.any() else None,'band_voice_gain_db':bands}

CONFIGS={
 'no_aec_fullband65':dict(strength=65,echo_enabled=False),
 'aec_natural_fullband65':dict(strength=65,echo_enabled=True,preserve_voice=True),
 'aec_strong_fullband65':dict(strength=65,echo_enabled=True,preserve_voice=False),
 'aec_natural_only':dict(strength=0,echo_enabled=True,preserve_voice=True),
}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('music',nargs='?',help='omit for deterministic synthetic broadband music');p.add_argument('--report');p.add_argument('--samples',type=Path)
    p.add_argument('--only',nargs='*');a=p.parse_args()
    target=voice();reference=music(a.music);echo=room(reference);mic=(target+echo).astype(np.float32)
    result={'input_voice_to_music_db':round(db(rms(target[RATE*4:])/rms(echo[RATE*4:])),1)}
    if a.samples:a.samples.mkdir(parents=True,exist_ok=True);sf.write(a.samples/'0-mic-input.wav',mic,RATE)
    for name,cfg in CONFIGS.items():
        if a.only and name not in a.only:continue
        y,lat=run(FullbandEngine(**cfg),mic,reference);result[name]=scores(target,echo,y,lat)
        if a.samples:sf.write(a.samples/f'{name}.wav',y,RATE)
        print(name,json.dumps(result[name]),flush=True)
    if a.report:Path(a.report).write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
