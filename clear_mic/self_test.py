import json,time
import numpy as np
from .paths import DATA
from .processor import Processor,FRAME,RATE
from .settings import Voice
def run():
    engine=Processor();rng=np.random.default_rng(3);times=[];i=np.empty(FRAME,np.float32);o=np.empty(FRAME,np.float32);cpu=time.process_time();peak=0
    try:
        for frame in range(1000):
            t=(np.arange(FRAME)+frame*FRAME)/RATE;i[:]=.1*np.sin(2*np.pi*150*t)+rng.uniform(-.025,.025,FRAME)
            begin=time.perf_counter();engine.process(i,o);times.append((time.perf_counter()-begin)*1000);peak=max(peak,float(np.max(np.abs(o))))
            if not np.isfinite(o).all():raise RuntimeError('Nonfinite audio output')
    finally:engine.close()
    result={'frames':len(times),'audio_seconds':10,'mean_ms':float(np.mean(times)),'p95_ms':float(np.percentile(times,95)),'max_ms':max(times),'cpu_percent_one_core':100*(time.process_time()-cpu)/10,'output_peak':peak,'finite':True,'scope':'Synthetic processing benchmark; excludes audio capture/output.'}
    from .fullband import FullbandEngine
    fullband=FullbandEngine(65,True);shaping=Processor(Voice(noise=0));clean=np.empty(FRAME,np.float32);reference=np.zeros((FRAME,2),np.float32);full_times=[]
    try:
        for frame in range(300):
            t=(np.arange(FRAME)+frame*FRAME)/RATE;i[:]=.1*np.sin(2*np.pi*150*t)+.01*np.sin(2*np.pi*12000*t)
            begin=time.perf_counter();fullband.process(i,reference,clean);shaping.process(clean,o);full_times.append((time.perf_counter()-begin)*1000)
            if not np.isfinite(o).all():raise RuntimeError('Nonfinite full-band output')
        result['fullband']={'frames':len(full_times),'finite':True,'p95_ms':float(np.percentile(full_times,95)),'max_ms':max(full_times),'fixed_dsp_delay_ms':(fullband.latency_samples+96)/48}
    finally:fullband.close();shaping.close()
    if max(times)>10:result['note']='One or more frames exceeded the frame budget; inspect host load.'
    (DATA/'self-test.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
