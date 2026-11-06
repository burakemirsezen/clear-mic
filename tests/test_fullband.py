"""Full-band regressions: real model, timing, bandwidth and preview tails."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import backend
from clear_mic.audio_service import process_clip
from clear_mic.fullband import FullbandDenoiser,FullbandEngine,MODEL_DELAY
from clear_mic.settings import Voice,voice_from
from clear_mic.processor import FRAME,RATE,Config

def transparent(**extra):
    return Voice(noise=1,highpass=0,auto_level=0,compressor=0,limiter=0,**extra)

class FullbandTests(unittest.TestCase):
    def test_zero_strength_is_aligned_transparent_even_at_partial_tail(self):
        raw=np.random.default_rng(14).uniform(-.1,.1,RATE+17).astype(np.float32)
        out=process_clip(raw,transparent(fullband_strength=0),engine='fullband')
        self.assertEqual(len(out),len(raw));np.testing.assert_array_equal(out,raw)

    def test_default_strength_retains_band_above_8khz(self):
        rng=np.random.default_rng(2);raw=rng.normal(0,.025,RATE*2).astype(np.float32)
        out=process_clip(raw,transparent(),engine='fullband')
        a=np.fft.rfft(raw[RATE//2:]);b=np.fft.rfft(out[RATE//2:]);hz=np.fft.rfftfreq(len(raw)-RATE//2,1/RATE)
        for low,high in ((8000,12000),(12000,20000)):
            band=(hz>=low)&(hz<high)
            loss=10*np.log10(np.sum(abs(b[band])**2)/np.sum(abs(a[band])**2))
            self.assertGreater(loss,-12,'Upper frequencies must survive; the old 16 kHz path lost >80 dB')

    def test_delay_and_blend_follow_same_input_timeline(self):
        raw=np.random.default_rng(4).normal(0,.03,RATE).astype(np.float32)
        wet=process_clip(raw,transparent(fullband_strength=100),engine='fullband')
        mixed=process_clip(raw,transparent(fullband_strength=65),engine='fullband')
        np.testing.assert_allclose(mixed,.35*raw+.65*wet,atol=3e-8,rtol=0)
        engine=FullbandEngine();self.addCleanup(engine.close);self.assertEqual(engine.latency_samples,MODEL_DELAY)

    def test_gate_limiter_echo_flush_preserves_short_preview_end(self):
        raw=np.zeros(117,np.float32);raw[-1]=.2
        voice=Voice(noise=1,highpass=0,auto_level=0,compressor=0,gate=1,gate_threshold_db=-75,fullband_strength=0)
        out=process_clip(raw,voice,np.zeros((len(raw),2),np.float32),engine='fullband')
        self.assertEqual(len(out),len(raw));self.assertTrue(np.isfinite(out).all());self.assertGreater(np.max(abs(out[-20:])),.02)

    def test_bad_strength_and_frames_are_rejected_without_changing_native_abi(self):
        for value in (-1,101,np.nan):
            with self.assertRaises(ValueError):FullbandEngine(value)
            with self.assertRaises(ValueError):voice_from({'fullband_strength':value})
        self.assertNotIn('fullband_strength',dict(Config._fields_))
        core=FullbandDenoiser();self.addCleanup(core.close);out=np.zeros(FRAME,np.float32)
        with self.assertRaises(ValueError):core.process(out[:-1],out)
        with self.assertRaises(ValueError):core.process(np.full(FRAME,np.nan,np.float32),out)
        with self.assertRaises(ValueError):core.process(out,out[:-1])

    def test_rejected_frame_does_not_poison_or_advance_the_next_voice(self):
        engine=FullbandEngine();control=FullbandEngine()
        self.addCleanup(engine.close);self.addCleanup(control.close)
        frames=np.random.default_rng(23).normal(0,.04,(12,FRAME)).astype(np.float32)
        actual=np.empty(FRAME,np.float32);expected=np.empty_like(actual)
        for i,frame in enumerate(frames):
            if i==6:
                bad=frame.copy();bad[0]=np.nan
                with self.assertRaises(ValueError):engine.process(bad,None,actual)
                readonly=actual.copy();readonly.flags.writeable=False
                with self.assertRaises(ValueError):engine.process(frame,None,readonly)
                with self.assertRaises(ValueError):engine.process(frame,None,actual[:-1])
            engine.process(frame,None,actual);control.process(frame,None,expected)
            np.testing.assert_allclose(actual,expected,atol=3e-8,rtol=0)

    def test_live_strength_changes_do_not_make_a_frame_boundary_click(self):
        # A silent enhanced path makes the loudest possible blend difference.
        # Constant dry audio exposes a discontinuity as a click directly.
        with patch('clear_mic.fullband.FullbandDenoiser') as core:
            core.return_value.process.side_effect=lambda source,out:out.fill(0)
            engine=FullbandEngine(0);self.addCleanup(engine.close)
        mic=np.full(FRAME,.1,np.float32);out=np.empty_like(mic)
        for _ in range(MODEL_DELAY//FRAME+1):engine.process(mic,None,out)
        parts=[out.copy()]
        for strength in (100,0,100,100,0,0,65):
            engine.configure(strength);engine.process(mic,None,out);parts.append(out.copy())
        delta=np.diff(np.concatenate(parts))
        self.assertLessEqual(np.max(abs(delta)),.00011)
        self.assertTrue(np.isfinite(delta).all())

    def test_closed_engine_fails_before_touching_output(self):
        engine=FullbandEngine();engine.close();output=np.full(FRAME,.125,np.float32)
        with self.assertRaisesRegex(RuntimeError,'closed'):engine.process(np.zeros_like(output),None,output)
        np.testing.assert_array_equal(output,np.full(FRAME,.125,np.float32))

    def test_live_nonfinite_input_is_rejected_before_echo_or_reference_reads(self):
        engine=FullbandEngine(echo_enabled=True);self.addCleanup(engine.close)
        output=np.full(FRAME,.125,np.float32)
        with patch.object(engine.echo,'process_live') as echo:
            for bad_value in (np.nan,np.inf,-np.inf):
                mic=np.zeros(FRAME,np.float32);mic[0]=bad_value
                with self.assertRaisesRegex(ValueError,'finite'):engine.process_live(mic,None,output)
            echo.assert_not_called()
        np.testing.assert_array_equal(output,np.full(FRAME,.125,np.float32))

    def test_processed_replay_saves_current_audio_and_settings_without_reference(self):
        service=backend.Backend.__new__(backend.Backend)
        service.preview=np.zeros(FRAME,np.float32);service.preview_reference=np.zeros((FRAME,2),np.float32)
        service.preview_stamp='test';service.busy=False;service.service=type('Stopped',(),{'active':False})()
        service.settings={'listen':'Headphones','voice':vars(Voice(fullband_strength=42)),'echo_cancel':True,'echo_mode':'natural','engine':'fullband','preview_match':True}
        service.emit=lambda value:None
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'previews').mkdir();metadata=root/'previews/test-preview.json'
            metadata.write_text(json.dumps({'recorded_settings':{'engine':'fullband'},'reference_in_memory':True}))
            with patch.object(backend,'DATA',root),patch.object(backend,'process_clip',return_value=np.ones(FRAME,np.float32)*.1),patch.object(backend.sf,'write') as write,patch.object(backend,'resolve',return_value=1),patch.object(backend.sd,'stop'),patch.object(backend.sd,'play'):
                service.handle({'action':'play','value':'processed'})
            details=json.loads(metadata.read_text())
            self.assertEqual(details['processed_settings']['voice']['fullband_strength'],42)
            self.assertEqual(write.call_args.args[0].name,'test-processed.wav')
            self.assertEqual(sorted(p.name for p in (root/'previews').iterdir()),['test-preview.json'])
