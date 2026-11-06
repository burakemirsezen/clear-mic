import unittest
import numpy as np
from clear_mic.processor import Processor,FRAME,RATE
from clear_mic.settings import Voice,voice_from
from clear_mic.audio_service import process_clip


class NoiseGateTests(unittest.TestCase):
    def voice(self,**values):
        fields=dict(noise=0,highpass=0,compressor=0,limiter=0,auto_level=0,gate=1,gate_threshold_db=-40)
        fields.update(values);return Voice(**fields)

    def run_audio(self,source,**values):
        p=Processor(self.voice(**values));self.addCleanup(p.close)
        out=np.empty_like(source)
        for i in range(0,len(source),FRAME):p.process(source[i:i+FRAME],out[i:i+FRAME])
        return out,p

    def test_quiet_keyboard_transients_stay_muted(self):
        source=np.random.default_rng(81).uniform(-.0005,.0005,RATE).astype(np.float32)
        source[::4000]=.006 # Peaks below the -40 dBFS threshold.
        out,_=self.run_audio(source)
        np.testing.assert_array_equal(out,np.zeros_like(out))

    def test_lookahead_preserves_first_loud_consonant_exactly(self):
        source=np.zeros(RATE,np.float32);source[1200:1220]=np.linspace(.02,.04,20)
        out,p=self.run_audio(source)
        np.testing.assert_allclose(out[240:],source[:-240],atol=1e-7)
        self.assertEqual(p.lib.cm_latency(p.state),240)

    def test_gate_bypass_has_no_extra_delay_or_change(self):
        source=np.random.default_rng(82).uniform(-.2,.2,FRAME*10).astype(np.float32)
        out,p=self.run_audio(source,gate=0)
        np.testing.assert_allclose(out,source,atol=1e-7)
        self.assertEqual(p.lib.cm_latency(p.state),0)

    def test_hold_keeps_brief_quiet_speech_gaps_open(self):
        source=np.full(RATE,.002,np.float32);source[4800:9600]=.03
        out,_=self.run_audio(source,gate_hold_ms=150,gate_release_ms=120)
        np.testing.assert_allclose(out[10000:16000],.002,atol=1e-7)
        self.assertEqual(float(out[-1]),0)

    def test_release_is_smooth_and_finishes_at_zero(self):
        source=np.full(RATE,.002,np.float32);source[4800:9600]=.03
        out,_=self.run_audio(source,gate_hold_ms=50,gate_release_ms=100)
        tail=out[13000:18000]
        self.assertTrue(np.all(np.diff(tail)<=1e-8))
        self.assertLess(float(np.max(np.abs(np.diff(tail)))),1e-6)
        self.assertEqual(float(out[-1]),0)

    def test_hysteresis_keeps_sustained_quieter_voice_after_opening(self):
        source=np.full(RATE,.006,np.float32);source[1000:2000]=.02
        out,_=self.run_audio(source)
        np.testing.assert_allclose(out[3000:],source[3000-240:-240],atol=1e-7)

    def test_gate_closes_before_output_boost(self):
        source=np.full(RATE,.003,np.float32)
        out,_=self.run_audio(source,output_db=6,auto_level=1)
        np.testing.assert_array_equal(out,np.zeros_like(out))

    def test_threshold_adjustment_actually_changes_which_clicks_pass(self):
        source=np.zeros(RATE,np.float32);source[RATE//2]=.006
        blocked,_=self.run_audio(source,gate_threshold_db=-40)
        passed,_=self.run_audio(source,gate_threshold_db=-50)
        self.assertEqual(float(np.max(np.abs(blocked))),0)
        self.assertAlmostEqual(float(np.max(np.abs(passed))),.006,places=6)

    def test_preview_keeps_length_and_corrects_gate_delay(self):
        source=np.zeros(RATE+17,np.float32);source[RATE//2]=.03
        out=process_clip(source,self.voice(limiter=1))
        self.assertEqual(len(out),len(source))
        np.testing.assert_allclose(out,source,atol=1e-7)

    def test_old_settings_leave_gate_disabled_and_invalid_thresholds_are_rejected(self):
        self.assertEqual(voice_from({'noise':0}).gate,0)
        for values in ({'gate_threshold_db':-90},{'gate_threshold_db':float('nan')},{'gate_hold_ms':0},{'gate_release_ms':1000}):
            with self.assertRaises(ValueError):voice_from(values)
