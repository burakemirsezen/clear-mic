"""Measure the actual 48 kHz streaming pipeline; no microphones are opened."""
import argparse,json,subprocess,sys,time
from dataclasses import replace
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from clear_mic.neural import NeuralEngine
from clear_mic.processor import Processor,FRAME,RATE
from clear_mic.settings import Voice
from clear_mic.audio_service import process_clip
from scripts.measure_echo_quality import scenario
from scripts.measure_voice import rms,db

def score(target,output):
    a=target[RATE*6:-FRAME].astype(np.float64);b=output[RATE*6:-FRAME].astype(np.float64)
    scale=float(np.dot(a,b)/np.dot(a,a))
    return {'si_sdr_db':db(rms(scale*a)/max(rms(b-scale*a),1e-12)),'voice_gain_db':db(abs(scale)),'correlation':float(np.corrcoef(a,b)[0,1])}

def pipeline(mic,reference,mode,threads=None,paced=False):
    if threads is None:threads=4 if mode=='neural_clean' else 2
    count=len(mic);extra=(-count)%FRAME+FRAME*5
    mic=np.pad(mic,(0,extra));reference=np.pad(reference,((0,extra),(0,0)))
    enhancer=NeuralEngine(mode,threads);processor=Processor(Voice(noise=0,highpass=0,auto_level=0,compressor=0,limiter=0))
    out=np.empty_like(mic);clean=np.empty(FRAME,np.float32);times=[];late=[];cpu=time.process_time();start=time.perf_counter()
    try:
        for i in range(0,len(mic),FRAME):
            if paced:
                due=start+i/RATE;wait=due-time.perf_counter()
                if wait>0:time.sleep(wait)
                late.append(max(0,time.perf_counter()-due)*1000)
            begin=time.perf_counter();enhancer.process(mic[i:i+FRAME],reference[i:i+FRAME],clean);processor.process(clean,out[i:i+FRAME]);times.append((time.perf_counter()-begin)*1000)
        consumed=time.process_time()-cpu
    finally:enhancer.close();processor.close()
    timing={'mean_ms_per_10ms_callback':float(np.mean(times)),'p95_ms':float(np.percentile(times,95)),'p99_ms':float(np.percentile(times,99)),'max_ms':max(times),'callbacks_over_10ms':sum(t>10 for t in times),'cpu_seconds':consumed,'audio_seconds':count/RATE,'fixed_enhancement_delay_ms':36,'threads':threads,'paced_realtime':paced}
    if paced:timing.update({'python_pacer_p99_lateness_ms':float(np.percentile(late,99)),'callbacks_past_next_slot':sum(a+b>10 for a,b in zip(times,late))})
    return out[1728:1728+count].copy(),timing

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path);parser.add_argument('--samples',type=Path);parser.add_argument('--stress',action='store_true');args=parser.parse_args()
    results={'scope':'Pinned speech and simulated acoustic paths; excludes Windows/virtual cable/Discord/network latency.','engines':{}}
    for mode in ('neural_clean','neural_echo'):
        result={}
        for label in ('music','speech','keyboard'):
            target,reference,acoustic=scenario('music' if label=='keyboard' else label)
            if label=='keyboard':
                rng=np.random.default_rng(123);acoustic=rng.normal(0,.002,len(target)).astype(np.float32)
                for i in range(2400,len(acoustic)-360,16500):acoustic[i:i+360]+=rng.normal(0,.01,360).astype(np.float32)*np.exp(-np.arange(360)/90)
                reference.fill(0)
            output,timing=pipeline(target+acoustic,reference,mode)
            result[label]={'quality':score(target,output),'timing':timing,'quiet_residual_rms_dbfs':db(rms(output[RATE:RATE*3]))}
            if args.samples:
                args.samples.mkdir(parents=True,exist_ok=True)
                sf.write(args.samples/f'{mode}-{label}.wav',output[RATE*6:-FRAME]*4,RATE)
                if mode=='neural_clean':
                    sf.write(args.samples/f'original-{label}.wav',(target+acoustic)[RATE*6:-FRAME]*4,RATE)
                    voice=Voice(noise=0,highpass=0,compressor=0,limiter=0,auto_level=0)
                    classic=process_clip(target+acoustic,voice,reference if label!='keyboard' else None)
                    sf.write(args.samples/f'classic-{label}.wav',classic[RATE*6:-FRAME]*4,RATE)
        results['engines'][mode]=result
    if args.stress:
        workers=[]
        try:
            code='import time; end=time.perf_counter()+45; x=1\nwhile time.perf_counter()<end: x=(x*1664525+1013904223)&0xffffffff'
            workers=[subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for _ in range(4)]
            target,ref,acoustic=scenario('music');results['four_busy_processes']={}
            for threads in (2,4):
                _,timing=pipeline((target+acoustic)[:RATE*10],ref[:RATE*10],'neural_clean',threads,paced=True)
                results['four_busy_processes'][str(threads)]=timing
        finally:
            for p in workers:
                if p.poll() is None:p.terminate()
                p.wait(timeout=5)
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results,indent=2))

if __name__=='__main__':main()
