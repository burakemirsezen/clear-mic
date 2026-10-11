import unittest
import numpy as np
from clear_mic.processor import Processor,FRAME,RATE
from clear_mic.settings import Voice,voice_from

class SpeechTests(unittest.TestCase):
    def processor(self,**values):
        config=Voice(noise=0,highpass=0,compressor=0,limiter=0,makeup_db=0)
        for k,v in values.items():setattr(config,k,v)
        p=Processor(config);self.addCleanup(p.close);return p
    def frames(self,p,signal):
        signal=np.asarray(signal,np.float32);out=np.empty_like(signal)
        for i in range(0,len(signal),FRAME):p.process(signal[i:i+FRAME],out[i:i+FRAME])
        return out
    def test_bypass_is_transparent(self):
        source=np.random.default_rng(1).uniform(-.5,.5,FRAME).astype(np.float32)
        np.testing.assert_allclose(self.frames(self.processor(),source),source,atol=1e-7)
    def test_limiter_ceiling_survives_impulses_and_gain(self):
        source=np.random.default_rng(2).uniform(-2,2,FRAME*20).astype(np.float32);source[0]=10
        out=self.frames(self.processor(limiter=1),source)
        self.assertLessEqual(float(np.max(np.abs(out))),10**(-1/20)+1e-6)
        self.assertTrue(np.isfinite(out).all())
    def test_limiter_has_two_ms_lookahead(self):
        source=np.zeros(FRAME,np.float32);source[0]=.2
        out=self.frames(self.processor(limiter=1),source)
        self.assertEqual(int(np.argmax(np.abs(out))),96)
        self.assertAlmostEqual(float(out[96]),.2,places=6)
    def test_highpass_cuts_rumble_and_keeps_speech_band(self):
        t=np.arange(RATE)/RATE
        ratios=[]
        for frequency in (20,1000):
            source=(.1*np.sin(2*np.pi*frequency*t)).astype(np.float32);out=self.frames(self.processor(highpass=1),source)
            ratios.append(float(np.sqrt(np.mean(out[RATE//2:]**2)/np.mean(source[RATE//2:]**2))))
        self.assertLess(ratios[0],.1);self.assertGreater(ratios[1],.98)
    def test_soft_compression_reduces_loud_steady_voice(self):
        source=(.316*np.sin(2*np.pi*1000*np.arange(RATE*2)/RATE)).astype(np.float32)
        out=self.frames(self.processor(compressor=1,threshold_db=-20,ratio=2),source)
        change=20*np.log10(np.sqrt(np.mean(out[RATE:]**2)/np.mean(source[RATE:]**2)))
        self.assertGreater(change,-5);self.assertLess(change,-2)
    def test_nonfinite_audio_is_rejected(self):
        p=self.processor();source=np.zeros(FRAME,np.float32);source[10]=np.nan
        with self.assertRaises(RuntimeError):p.process(source,np.empty_like(source))
    def test_settings_reject_nonfinite_parameters(self):
        with self.assertRaises(ValueError):voice_from({'ratio':float('nan')})

if __name__=='__main__':unittest.main()
