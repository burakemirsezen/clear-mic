"""Exercise the real live callback with synthetic devices; never opens audio endpoints."""
import argparse,ctypes as C,gc,json,subprocess,sys,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from clear_mic import __version__
from clear_mic.audio_service import AudioService
from clear_mic.processor import FRAME,RATE
from clear_mic.settings import Voice
from scripts.measure_echo_quality import fullband_scenario

class Counters(C.Structure):
    _fields_=[('cb',C.c_ulong),('faults',C.c_ulong)]+[(name,C.c_size_t) for name in ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]

def memory():
    stats=Counters();stats.cb=C.sizeof(stats)
    kernel=C.WinDLL('kernel32');kernel.GetCurrentProcess.restype=C.c_void_p
    psapi=C.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[C.c_void_p,C.POINTER(Counters),C.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),C.byref(stats),stats.cb):raise C.WinError()
    return {'private_mib':stats.private/1048576,'working_mib':stats.working/1048576}

@contextmanager
def audio_scheduling():
    # PortAudio's shared-WASAPI callback uses the MMCSS Audio task. A plain
    # Python main thread is not an equivalent scheduling/deadline harness.
    # Scope this to the synthetic callback runner and always undo registration.
    avrt=C.WinDLL('avrt',use_last_error=True)
    avrt.AvSetMmThreadCharacteristicsW.argtypes=[C.c_wchar_p,C.POINTER(C.c_ulong)];avrt.AvSetMmThreadCharacteristicsW.restype=C.c_void_p
    avrt.AvRevertMmThreadCharacteristics.argtypes=[C.c_void_p];avrt.AvRevertMmThreadCharacteristics.restype=C.c_int
    task=C.c_ulong();handle=avrt.AvSetMmThreadCharacteristicsW('Audio',C.byref(task))
    if not handle:raise C.WinError(C.get_last_error())
    try:yield
    finally:
        if not avrt.AvRevertMmThreadCharacteristics(handle):raise C.WinError(C.get_last_error())

class Reference:
    def __init__(self):self.samples=np.zeros((FRAME,2),np.float32);self.active=False;self.counters=[0,0];self.ready=False
    def set(self,frame):self.samples[:]=frame;self.ready=True
    def read(self):self.active=self.ready;self.ready=False;return self.samples
    def close(self):pass

def run(seconds,mic,far,paced=True,dynamic=True):
    service=AudioService();service.configure(Voice());reference=Reference();times=[];lateness=[];resources=[];changes=0
    input_frame=np.empty((FRAME,1),np.float32);output_frame=np.empty((FRAME,2),np.float32)
    presets=[Voice(),Voice(fullband_strength=0),Voice(fullband_strength=100),Voice(gate=1,output_db=-6),Voice(limiter=0),Voice(gate=1),Voice(fullband_strength=45,input_db=-3)]
    class Stream:
        active=False
        def __enter__(self):
            with audio_scheduling():return self._run()
        def _run(self):
            nonlocal changes
            # Feed a chronological warmup prefix; measured stream continues after it.
            for n in range(100):
                i=n*FRAME;input_frame[:,0]=mic[i:i+FRAME];reference.set(far[i:i+FRAME]);callback(input_frame,output_frame,FRAME,None,False)
            start=time.perf_counter();cpu=time.process_time();resources.append({'seconds':0,**memory()})
            for n in range(round(seconds*100)):
                if dynamic and n and n%500==0:service.configure(presets[(n//500)%len(presets)]);changes+=1
                i=((n+100)*FRAME)%(len(mic)//FRAME*FRAME)
                input_frame[:,0]=mic[i:i+FRAME]
                # Exercise transparent echo transitions with quiet reference gaps.
                reference.set(far[i:i+FRAME] if n%1800<1500 else np.zeros((FRAME,2),np.float32))
                due=start+n*.01
                if paced:
                    wait=due-time.perf_counter()
                    if wait>0:time.sleep(wait)
                lateness.append(max(0,time.perf_counter()-due)*1000)
                begin=time.perf_counter();callback(input_frame,output_frame,FRAME,None,False);times.append((time.perf_counter()-begin)*1000)
                if service.stats.get('status')!='running' or not np.isfinite(output_frame).all():raise RuntimeError('Invalid callback output/state: '+str(service.stats))
                if n and n%500==0:resources.append({'seconds':n/100,**memory()})
            self.cpu_seconds=time.process_time()-cpu;resources.append({'seconds':seconds,**memory()});service.stop_event.set();return self
        def __exit__(self,*args):pass
    stream=Stream();callback=None
    def open_stream(inp,out,fn,name):
        nonlocal callback
        callback=fn;return stream,''
    with patch('clear_mic.audio_service.resolve',return_value=1),patch('clear_mic.audio_service.SpeakerReference',return_value=reference),patch('clear_mic.audio_service.open_route',side_effect=open_stream):
        service._run('Synthetic physical mic','CABLE Input','Synthetic speakers',True,'fullband')
    if service.stats.get('status')!='stopped':raise RuntimeError('Stream did not stop cleanly: '+str(service.stats))
    return {'seconds':seconds,'frames':len(times),'controls_changed':changes,'paced':paced,'scheduling':'MMCSS Audio, same task as shared WASAPI; registration reverted on exit','mean_callback_ms':float(np.mean(times)),'p99_callback_ms':float(np.percentile(times,99)),'max_callback_ms':max(times),'calls_over_10ms':sum(t>10 for t in times),'calls_past_next_slot':sum(a+b>10 for a,b in zip(times,lateness)) if paced else None,'pacer_p99_lateness_ms':float(np.percentile(lateness,99)) if paced else None,'cpu_core_equivalents':stream.cpu_seconds/seconds,'reported_processing_deadline_misses':service.stats['processing_deadline_misses'],'memory':resources,'steady_private_growth_mib':resources[-1]['private_mib']-resources[0]['private_mib'],'clean_stop':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path);parser.add_argument('--seconds',type=int,default=60);parser.add_argument('--workers',type=int,default=6);args=parser.parse_args()
    if not 10<=args.seconds<=600 or not 0<=args.workers<=12:parser.error('Use10–600seconds and0–12workers')
    target,far,echo=fullband_scenario();mic=target+echo;workers=[]
    try:
        code=f'import time; end=time.perf_counter()+{args.seconds+30}; x=1\nwhile time.perf_counter()<end: x=(x*1664525+1013904223)&0xffffffff'
        workers=[subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for _ in range(args.workers)]
        loaded=run(args.seconds,mic,far)
    finally:
        for process in workers:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)
    gc.collect();before=memory();restarts=[]
    for _ in range(8):restarts.append(run(1,mic,far,paced=False,dynamic=False));gc.collect()
    after=memory()
    report={'version':__version__,'scope':'Real AudioService live callback, actual full-band/AEC/shaping DLLs, synthetic duplex/reference endpoints and prerecorded full-band signals. No microphone, speaker, virtual-driver or Discord endpoint was opened. Includes control changes, reference gaps, resource sampling and8unpaced restarts.','busy_processes':args.workers,'loaded_run':loaded,'restart_count':len(restarts),'all_restarts_clean':all(r['clean_stop'] for r in restarts),'private_growth_across_restarts_mib':after['private_mib']-before['private_mib'],'restart_memory_before':before,'restart_memory_after':after}
    report['pass']=loaded['calls_over_10ms']==0 and loaded['calls_past_next_slot']==0 and loaded['steady_private_growth_mib']<32 and report['all_restarts_clean'] and report['private_growth_across_restarts_mib']<32
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
    if not report['pass']:raise SystemExit('Stability thresholds failed; inspect report')

if __name__=='__main__':main()
