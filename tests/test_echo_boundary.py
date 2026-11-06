"""Reject bad live frames before native pointers or AEC state are used."""
import unittest
from unittest.mock import patch
import numpy as np
from clear_mic.echo import EchoCanceller
from clear_mic.processor import FRAME

class Reference:
    def __init__(self,samples=None):self.samples=samples;self.active=False;self.reads=0
    def read(self):
        self.reads+=1;self.active=self.samples is not None
        return self.samples

class EchoBoundaryTests(unittest.TestCase):
    def create(self):
        engine=EchoCanceller();self.addCleanup(engine.close);return engine

    def test_invalid_live_capture_never_reads_playback_or_advances_native_state(self):
        engine=self.create();baseline=self.create();mic=np.zeros(FRAME,np.float32);output=np.empty_like(mic);reference=Reference()
        readonly=np.empty(FRAME,np.float32);readonly.flags.writeable=False
        invalid=((mic[:-1],output),(mic.reshape(1,-1),output),(mic.astype(np.float64),output),
                 (np.zeros(FRAME*2,np.float32)[::2],output),(np.full(FRAME,np.nan,np.float32),output),
                 (np.full(FRAME,np.inf,np.float32),output),(mic,output[:-1]),(mic,readonly),
                 (mic,np.empty(FRAME*2,np.float32)[::2]),(mic,np.empty(FRAME,np.float64)))
        with patch.object(engine.lib,'cm_echo_render',wraps=engine.lib.cm_echo_render) as render,patch.object(engine.lib,'cm_echo_capture',wraps=engine.lib.cm_echo_capture) as capture:
            for source,destination in invalid:
                with self.assertRaises(ValueError):engine.process_live(source,reference,destination)
            self.assertEqual(reference.reads,0);render.assert_not_called();capture.assert_not_called()
        # Accepted frames after those errors must retain the untouched timeline.
        rng=np.random.default_rng(41);expected=np.empty(FRAME,np.float32)
        for _ in range(4):
            mic[:]=rng.uniform(-.1,.1,FRAME)
            engine.process_live(mic,reference,output);baseline.process_live(mic,Reference(),expected)
            np.testing.assert_array_equal(output,expected)

    def test_invalid_active_playback_never_reaches_native_render_or_capture(self):
        engine=self.create();mic=np.zeros(FRAME,np.float32);output=np.empty_like(mic)
        invalid=(np.full((FRAME,2),np.nan,np.float32),np.full((FRAME,2),np.inf,np.float32),
                 np.zeros((FRAME,2),np.float64),np.zeros((FRAME,4),np.float32)[:,::2],
                 np.zeros((2,FRAME),np.float32))
        with patch.object(engine.lib,'cm_echo_render',wraps=engine.lib.cm_echo_render) as render,patch.object(engine.lib,'cm_echo_capture',wraps=engine.lib.cm_echo_capture) as capture:
            for samples in invalid:
                with self.assertRaises(ValueError):engine.process_live(mic,Reference(samples),output)
            render.assert_not_called();capture.assert_not_called()

    def test_offline_and_live_share_capture_validation(self):
        engine=self.create();mic=np.zeros(FRAME,np.float32);far=np.zeros((FRAME,2),np.float32)
        with patch.object(engine.lib,'cm_echo_process',wraps=engine.lib.cm_echo_process) as process:
            with self.assertRaises(ValueError):engine.process(mic,far,np.empty(FRAME*2,np.float32)[::2])
            process.assert_not_called()

    def test_valid_single_render_live_path_matches_offline_audio_exactly(self):
        live=self.create();offline=self.create();rng=np.random.default_rng(42)
        class SingleBlock(Reference):
            def read(self):
                self.active=self.reads==0;self.reads+=1;return self.samples
        output=np.empty(FRAME,np.float32);expected=np.empty_like(output)
        for _ in range(30):
            mic=rng.uniform(-.1,.1,FRAME).astype(np.float32);far=rng.uniform(-.03,.03,(FRAME,2)).astype(np.float32)
            live.process_live(mic,SingleBlock(far),output);offline.process(mic,far,expected)
            np.testing.assert_array_equal(output,expected)

    def test_closed_live_echo_rejects_before_reading_reference(self):
        engine=self.create();engine.close();reference=Reference()
        with self.assertRaisesRegex(RuntimeError,'closed'):engine.process_live(np.zeros(FRAME,np.float32),reference,np.empty(FRAME,np.float32))
        self.assertEqual(reference.reads,0)
