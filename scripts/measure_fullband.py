"""Reproducible paced full-band CPU benchmark; no device or microphone is opened."""
import argparse,json,subprocess,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from clear_mic.fullband import FullbandEngine
from clear_mic.processor import Processor,FRAME,RATE
from clear_mic.settings import Voice
from scripts.measure_echo_quality import scenario

def pipeline(mic,reference,paced=True,gate=False):
    if len(mic)<RATE+FRAME or reference.shape!=(len(mic),2):raise ValueError('Benchmark needs at least one second of warmup and one measured frame with matching stereo reference')
    enhancer=FullbandEngine(65,True,True);processor=None
    clean=np.empty(FRAME,np.float32);out=np.empty_like(clean);times=[];late=[]
    try:
        processor=Processor(Voice(noise=0,gate=int(gate)))
        # Warm on the prefix, then continue the same chronological stream. Replaying
        # the prefix after warmup jumps the acoustic/model histories backwards.
        for i in range(0,RATE,FRAME):
            enhancer.process(mic[i:i+FRAME],reference[i:i+FRAME],clean);processor.process(clean,out)
        cpu=time.process_time();start=time.perf_counter()
        for i in range(RATE,len(mic)//FRAME*FRAME,FRAME):
            due=start+(i-RATE)/RATE
            if paced:
                wait=due-time.perf_counter()
                if wait>0:time.sleep(wait)
            late.append(max(0,time.perf_counter()-due)*1000)
            begin=time.perf_counter();enhancer.process(mic[i:i+FRAME],reference[i:i+FRAME],clean);processor.process(clean,out)
            times.append((time.perf_counter()-begin)*1000)
            if not np.isfinite(out).all():raise RuntimeError('Invalid output')
        consumed=time.process_time()-cpu
    finally:
        enhancer.close()
        if processor:processor.close()
    return {'frames':len(times),'audio_seconds':len(times)/100,'warmup_seconds':1,'mean_ms':float(np.mean(times)),'p95_ms':float(np.percentile(times,95)),'p99_ms':float(np.percentile(times,99)),'max_ms':max(times),'calls_over_10ms':sum(t>10 for t in times),'calls_past_next_slot':sum(a+b>10 for a,b in zip(times,late)),'pacer_p99_lateness_ms':float(np.percentile(late,99)),'cpu_seconds':consumed,'cpu_core_equivalents':consumed/(len(times)/100),'fixed_dsp_delay_ms':(2400+430+96+240*gate)/48,'gate':gate,'onnx_threads':2,'strength':65,'echo_mode':'natural','paced':paced}

def main():
    args=argparse.ArgumentParser(description=__doc__);args.add_argument('report',type=Path);args.add_argument('--stress',action='store_true');opts=args.parse_args()
    target,ref,acoustic=scenario('music');mic=(target+acoustic)[:RATE*11];ref=ref[:len(mic)]
    from clear_mic import __version__
    result={'version':__version__,'scope':'CPU processing of prerecorded speech with simulated stereo acoustic echo, default full-band shaping. One chronological second of warmup precedes ten measured seconds. Excludes audio devices, drivers, Discord and network.','normal':pipeline(mic,ref)}
    if opts.stress:
        workers=[]
        try:
            code='import time; end=time.perf_counter()+30; x=1\nwhile time.perf_counter()<end: x=(x*1664525+1013904223)&0xffffffff'
            workers=[subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for _ in range(4)]
            result['four_busy_processes_gate_on']=pipeline(mic,ref,gate=True)
        finally:
            for process in workers:
                if process.poll() is None:process.terminate()
                process.wait(timeout=5)
    opts.report.parent.mkdir(parents=True,exist_ok=True);opts.report.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
