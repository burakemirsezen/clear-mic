import unittest
from unittest.mock import patch
import numpy as np
from clear_mic.neural import NeuralEngine
from clear_mic.settings import Voice
from clear_mic.audio_service import process_clip
from clear_mic.processor import FRAME,RATE
from scripts.measure_echo_quality import scenario
from scripts.measure_neural import score


class NeuralTests(unittest.TestCase):
    def test_real_speech_over_music_improves_with_both_neural_engines(self):
        target,reference,acoustic=scenario('music')
        voice=Voice(noise=0,highpass=0,auto_level=0,compressor=0,limiter=0)
        for engine,minimum in [('neural_clean',8),('neural_echo',12)]:
            output=process_clip(target+acoustic,voice,reference,engine=engine)
            self.assertEqual(len(output),len(target));self.assertTrue(np.isfinite(output).all())
            self.assertGreater(score(target,output)['si_sdr_db'],minimum)

    def test_neural_full_cleanup_does_not_stack_rnnoise_on_voice(self):
        voice=Voice(noise=1,limiter=0,auto_level=0,compressor=0,highpass=0)
        raw=np.zeros(FRAME*5,np.float32)
        with patch('clear_mic.audio_service.NeuralEngine') as engine,patch('clear_mic.audio_service.Processor') as processor:
            engine.return_value.latency_samples=1728;processor.return_value.latency_samples=0
            processor.return_value.process.side_effect=lambda x,y:y.fill(0)
            engine.return_value.process.side_effect=lambda x,r,y:y.fill(0)
            process_clip(raw,voice,engine='neural_clean')
        self.assertEqual(processor.call_args.args[0].noise,0)
        self.assertEqual(voice.noise,1)

    def test_streaming_queue_handles_long_silence_without_underruns(self):
        engine=NeuralEngine('neural_echo');self.addCleanup(engine.close)
        mic=np.zeros(FRAME,np.float32);far=np.zeros((FRAME,2),np.float32);out=np.empty_like(mic)
        for _ in range(120):engine.process(mic,far,out);self.assertTrue(np.isfinite(out).all())
        self.assertEqual(engine.latency_samples,1728)

    def test_bad_frames_and_nonfinite_audio_are_rejected(self):
        engine=NeuralEngine('neural_echo');self.addCleanup(engine.close)
        mic=np.zeros(FRAME,np.float32);far=np.zeros((FRAME,2),np.float32);out=np.empty_like(mic)
        with self.assertRaises(ValueError):engine.process(mic[:-1],far,out)
        mic[0]=np.nan
        with self.assertRaisesRegex(RuntimeError,'Invalid'):engine.process(mic,far,out)

    def test_neural_and_gate_preview_keeps_partial_tail_length(self):
        raw=np.zeros(RATE+17,np.float32);raw[RATE//2:RATE//2+100]=.1
        out=process_clip(raw,Voice(noise=0,gate=1),engine='neural_echo')
        self.assertEqual(len(out),len(raw));self.assertTrue(np.isfinite(out).all())
