"""Voice fidelity during simultaneous playback. Uses pinned upstream speech.

No microphone capture. Scores describe simulated rooms, not listening quality.
Run with an optional report path. --samples DIRECTORY writes a local comparison.
"""
import argparse,json,sys,time
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from clear_mic.echo import EchoCanceller
from clear_mic.processor import FRAME,RATE
from scripts.measure_voice import rms,db

def fixture(name,seconds=18):
    x,rate=sf.read(ROOT/'vendor/webrtc-aec3/tests'/name,dtype='float32')
    if x.ndim>1:x=x[:,0]
    x=np.interp(np.arange(round(len(x)*RATE/rate))*rate/RATE,np.arange(len(x)),x)
    return np.tile(x,int(np.ceil(seconds*RATE/len(x))))[:seconds*RATE].astype(np.float32)

def run(mic,reference,preserve_voice=True):
    p=EchoCanceller(preserve_voice);y=np.empty_like(mic);times=[]
    try:
        for i in range(0,len(mic),FRAME):
            start=time.perf_counter();p.process(mic[i:i+FRAME],reference[i:i+FRAME],y[i:i+FRAME]);times.append((time.perf_counter()-start)*1000)
    finally:p.close()
    return y,float(np.percentile(times,95))

def score(target,y):
    # AEC3's measured fixed delay; discard convergence and the final partial tail.
    a=target[RATE*6:-480].astype(np.float64);b=y[RATE*6+430:-50].astype(np.float64)
    scale=float(np.dot(a,b)/np.dot(a,a));error=b-scale*a
    return {'si_sdr_db':db(rms(scale*a)/max(rms(error),1e-12)),'voice_gain_db':db(abs(scale)),'correlation':float(np.corrcoef(a,b)[0,1])}

def scenario(label='music',level=1.):
    near=fixture('near.wav');near*=.035/rms(near)
    if label=='speech':
        source=fixture('far.wav');source*=.05/rms(source)
    else:
        t=np.arange(len(near))/RATE
        source=np.asarray(.022*sum(np.sin(2*np.pi*f*t)*(1+.25*np.sin(2*np.pi*.7*t)) for f in (196,246.94,293.66,392,493.88,587.33)),np.float32)
    reference=np.stack([source,np.roll(source,73)*.8],axis=1).astype(np.float32)
    acoustic=np.zeros(len(near),np.float32)
    for delay,gain,ch in [(2400,.55,0),(3400,.2,1),(4200,.1,0)]:acoustic[delay:]+=reference[:-delay,ch]*gain
    target=near*level;target[:RATE*4]=0
    return target,reference,acoustic


def fullband_scenario():
    """Expose upper-band loss that the originally 16 kHz speech fixture misses.

    Add deterministic, speech-shaped high-frequency bursts to near-end speech.
    Playback contains low-frequency musical chords only, so upper-band output
    cannot earn a better retention score by leaving high-frequency music behind.
    This is a synthetic bandwidth regression, not recorded fricatives or a
    perceptual speech-quality score.
    """
    target,reference,acoustic=scenario('music')
    rng=np.random.default_rng(121);count=len(target)
    spectrum=np.fft.rfft(rng.normal(0,1,count));hz=np.fft.rfftfreq(count,1/RATE)
    spectrum[(hz<8500)|(hz>18000)]=0
    detail=np.fft.irfft(spectrum,n=count)
    envelope=np.maximum(0,np.sin(2*np.pi*3.4*np.arange(count)/RATE))**4
    detail*=envelope;detail*=.012/rms(detail);detail[:RATE*4]=0
    return np.asarray(target+detail,np.float32),reference,acoustic


def band_scores(target,y):
    """Compare complete aligned output to target without echo-only subtraction."""
    a=target[RATE*6:-480].astype(np.float64);b=y[RATE*6+430:-50].astype(np.float64)
    A=np.fft.rfft(a);B=np.fft.rfft(b);hz=np.fft.rfftfreq(len(a),1/RATE);result={}
    for low,high in ((300,3000),(4000,7500),(8500,12000),(12000,18000)):
        band=(hz>=low)&(hz<high)
        # Parseval's identity gives the band RMS ratio with identical FFT lengths.
        power_ratio=float(np.sum(abs(B[band])**2)/np.sum(abs(A[band])**2))
        scale=float(np.real(np.vdot(A[band],B[band]))/np.sum(abs(A[band])**2))
        result[f'{low}-{high}']={'output_power_change_db':10*np.log10(max(power_ratio,1e-24)),
                                'projected_voice_gain_db':db(abs(scale))}
    return result


def measure_fullband():
    target,reference,acoustic=fullband_scenario();result={}
    for preserve,name in ((True,'natural_voice'),(False,'strong_isolation')):
        output,p95=run(target+acoustic,reference,preserve)
        result[name]={'voice':score(target,output),'bands_hz':band_scores(target,output),'p95_ms':p95}
    result['scope']='Synthetic 8.5–18 kHz near-end bursts added to pinned speech over low-frequency music echo; excludes room acoustics and listening quality. Complete output scored without subtracting a separate echo-only run.'
    return result

def measure(preserve_voice=True):
    cases={}
    for label in ('speech','music'):
        target,reference,acoustic=scenario(label)
        residual,_=run(acoustic,reference,preserve_voice)
        cases[label+'_echo_reduction_db']=db(rms(acoustic[RATE*6:])/max(rms(residual[RATE*6:]),1e-12))
        for level in (.3,1.,2.):
            voice=target*level;out,p95=run(acoustic+voice,reference,preserve_voice)
            result=score(voice,out);result['p95_ms']=p95;cases[f'{label}_voice_{level}']=result
    return cases

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',nargs='?');parser.add_argument('--samples',type=Path)
    args=parser.parse_args()
    value={'scope':'Pinned upstream speech over simulated speaker echo; not a human listening score.','strong_isolation':measure(False),'natural_voice':measure(True),'fullband_voice_detail':measure_fullband()}
    if args.samples:
        args.samples.mkdir(parents=True,exist_ok=True)
        target,reference,acoustic=scenario('music')
        # Use the same fixed gain and timeline for all three files.
        sf.write(args.samples/'target-voice.wav',target[RATE*6:-480]*4,RATE)
        for preserve,name in [(False,'before-strong-isolation'),(True,'after-natural-voice')]:
            audio,_=run(target+acoustic,reference,preserve)
            sf.write(args.samples/f'{name}.wav',audio[RATE*6+430:-50]*4,RATE)
    rendered=json.dumps(value,indent=2);print(rendered)
    if args.report:Path(args.report).write_text(rendered,encoding='utf-8')
