"""Driver-free checks of real DSP latency and callback diagnostics."""
import unittest
from contextlib import nullcontext
from unittest.mock import patch,MagicMock
import numpy as np
from clear_mic.audio_service import AudioService,process_clip
from clear_mic.processor import Processor,FRAME
from clear_mic.settings import Voice

class AudioTimingTests(unittest.TestCase):
    def run_callback(self,engine='classic',speaker=False,updated=None,elapsed_ms=1):
        service=AudioService();service.configure(Voice(noise=1,gate=1,limiter=1))
        class Enhancer:
            def __init__(self,*args):
                self.metrics=np.zeros(3,np.float32)
                self.latency_samples=(2400+(430 if args[1] else 0)) if len(args)>1 else 430
            def process_live(self,mic,reference,out):out[:]=mic;return 0
            def configure(self,*args):pass
            def close(self):pass
        def open_stream(inp,out,callback,name,exclusive=False):
            class Stream:
                active=False
                def __enter__(self):
                    if updated is not None:service.configure(updated)
                    callback(np.zeros((FRAME,1),np.float32),np.empty((FRAME,2),np.float32),FRAME,None,False)
                    service.stop_event.set();return self
                def __exit__(self,*args):pass
            return Stream(),''
        reference=MagicMock();reference.counters=[0,0]
        with patch('clear_mic.audio_service.com_apartment',return_value=nullcontext()),patch('clear_mic.audio_service.resolve',return_value=1),patch('clear_mic.audio_service.open_route',side_effect=open_stream),patch('clear_mic.audio_service.SpeakerReference',return_value=reference),patch('clear_mic.audio_service.EchoCanceller',Enhancer),patch('clear_mic.audio_service.FullbandEngine',Enhancer),patch('clear_mic.audio_service.time.perf_counter',side_effect=[1,1+elapsed_ms/1000]):
            service._run('USB mic','CABLE Input','Headphones' if speaker else None,True,engine)
        self.assertEqual(service.stats['status'],'stopped',service.stats)
        return service.stats

    def test_fixed_dsp_delay_includes_model_echo_noise_gate_and_limiter(self):
        for engine,speaker,samples in (('classic',False,960+240+96),('classic',True,960+430+240+96),('fullband',False,2400+240+96),('fullband',True,2400+430+240+96)):
            stats=self.run_callback(engine,speaker)
            self.assertAlmostEqual(stats['dsp_delay_ms'],samples/48)

    def test_live_setting_changes_update_reported_latency(self):
        stats=self.run_callback(updated=Voice(noise=0,gate=0,limiter=0))
        self.assertEqual(stats['dsp_delay_ms'],0)

    def test_slow_callback_is_counted_separately_from_fixed_dsp_delay(self):
        stats=self.run_callback(elapsed_ms=12)
        self.assertAlmostEqual(stats['mean_ms'],12)
        self.assertAlmostEqual(stats['max_ms'],12)
        self.assertEqual(stats['processing_deadline_misses'],1)
        self.assertEqual(stats['dsp_delay_ms'],27)

    def test_native_latency_remains_correct_after_reconfiguration(self):
        processor=Processor(Voice(noise=1,gate=1,limiter=1));self.addCleanup(processor.close)
        self.assertEqual(processor.latency_samples,1296)
        processor.configure(Voice(noise=0,gate=0,limiter=0))
        self.assertEqual(processor.latency_samples,0)

    def test_invalid_preview_audio_is_rejected_before_dsp_allocation(self):
        raw=np.zeros(FRAME,np.float32)
        with patch('clear_mic.audio_service.Processor') as factory:
            for signal,far in ((raw[:,None],None),(raw+np.nan,None),(raw,np.zeros((FRAME,1))),(raw,np.full((FRAME,2),np.inf))):
                with self.assertRaises(ValueError):process_clip(signal,Voice(),far,engine='fullband')
            factory.assert_not_called()
