import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import sounddevice as sd
import soundfile as sf
from clear_mic.audio_service import open_route,process_clip
from clear_mic.echo import EchoCanceller,physical_speaker
from clear_mic.processor import Processor,FRAME,RATE
from clear_mic.settings import Voice,PRESETS
from scripts.measure_voice import echo_run,rms,db,speech,frames
ROOT=Path(__file__).resolve().parents[1]

class EnhancementTests(unittest.TestCase):
    def test_speech_leveler_equalizes_quiet_spoken_sample_without_clipping(self):
        # Immutable upstream test fixture downloaded with the pinned source ZIP.
        clip,rate=sf.read(ROOT/'vendor/webrtc-aec3/tests/near.wav',dtype='float32')
        self.assertEqual(rate,16000)
        clip=np.interp(np.arange(len(clip)*3)/3,np.arange(len(clip)),clip).astype(np.float32)
        clip=np.tile(clip,4);clip=clip[:len(clip)//FRAME*FRAME]
        levels=[]
        for trim in (-18,-6,0):
            processor=Processor(Voice(compressor=0))
            try:output,_,_=frames(processor,clip*10**(trim/20))
            finally:processor.close()
            levels.append(db(rms(output[-RATE*3:])))
            self.assertLessEqual(np.max(np.abs(output)),10**(-1/20)+1e-6)
        self.assertLess(max(levels)-min(levels),1.5)
    def test_leveler_does_not_keep_raising_stationary_noise(self):
        rng=np.random.default_rng(5);noise=rng.normal(0,10**(-52/20),RATE*12).astype(np.float32)
        p=Processor(Voice(noise=0,highpass=0,compressor=0,limiter=1))
        try:output,_,gain=frames(p,noise)
        finally:p.close()
        self.assertLess(db(rms(output[-RATE*3:])),-48)
        self.assertLess(gain[-1],4)
    def test_leveler_off_restores_transparent_signal(self):
        p=Processor(Voice(noise=0,highpass=0,compressor=0,limiter=0));self.addCleanup(p.close)
        p.configure(Voice(noise=0,highpass=0,compressor=0,limiter=0,auto_level=0))
        x=np.random.default_rng(2).uniform(-.1,.1,FRAME).astype(np.float32);y=np.empty_like(x);p.process(x,y)
        np.testing.assert_allclose(x,y,atol=1e-7)
    def test_echo_canceller_removes_delayed_stereo_playback(self):
        rng=np.random.default_rng(6);reference=rng.normal(0,.04,(RATE*9,2)).astype(np.float32)
        mic=np.zeros(RATE*9,np.float32);mic[2400:]=reference[:-2400,0]*.5;mic[3300:]+=reference[:-3300,1]*.2
        output,_=echo_run(mic,reference)
        self.assertGreater(db(rms(mic[-RATE*2:])/rms(output[-RATE*2:])),20)
        self.assertTrue(np.isfinite(output).all())
    def test_echo_canceller_preserves_near_end_without_playback(self):
        voice=speech(3)*.1;output,_=echo_run(voice,np.zeros((len(voice),2),np.float32))
        self.assertGreater(db(rms(output[RATE:])/rms(voice[RATE:])), -2)
        self.assertLess(db(rms(output[RATE:])/rms(voice[RATE:])),2)
    def test_double_talk_retains_near_end_during_playback(self):
        rng=np.random.default_rng(7);reference=rng.normal(0,.04,(RATE*10,2)).astype(np.float32)
        echo=np.zeros(RATE*10,np.float32);echo[2400:]=.5*reference[:-2400,0]
        near=speech(10)*.08;near[:RATE*4]=0
        mixed,_=echo_run(echo+near,reference);baseline,_=echo_run(near,np.zeros_like(reference))
        a=baseline[-RATE*2:];b=mixed[-RATE*2:]
        self.assertGreater(db(rms(b)/rms(a)),-6)
        self.assertGreater(float(np.corrcoef(a,b)[0,1]),.7)
    def test_echo_preview_aligns_added_frame_delay(self):
        voice=Voice(noise=0,highpass=0,compressor=0,limiter=0,auto_level=0)
        raw=np.zeros(RATE,np.float32);raw[RATE//2]=.1
        processed=process_clip(raw,voice,np.zeros((RATE,2),np.float32))
        self.assertEqual(len(processed),len(raw));self.assertEqual(int(np.argmax(np.abs(processed))),RATE//2)
    def test_echo_rejects_invalid_frames(self):
        p=EchoCanceller();self.addCleanup(p.close)
        mic=np.zeros(FRAME,np.float32);reference=np.zeros((FRAME,2),np.float32);mic[0]=np.nan
        with self.assertRaises(ValueError):p.process(mic,reference,np.empty_like(mic))
    def test_virtual_playback_is_not_a_speaker_reference(self):
        self.assertFalse(physical_speaker('Speakers (Clear Mic (VB-Audio Virtual Cable))'))
        self.assertTrue(physical_speaker('Speakers (USB Audio)'))
    def test_noise_only_preset_has_no_automatic_gain(self):
        self.assertEqual(PRESETS['Noise removal only'].auto_level,0)
    def test_owned_cable_can_use_compatible_feed(self):
        with patch('clear_mic.audio_service.sd.query_devices',return_value={'max_output_channels':2}),patch('clear_mic.audio_service.sd.Stream',side_effect=[sd.PortAudioError('Unavailable'), 'stream']),patch('clear_mic.audio_service.resolve',return_value=23):
            stream,note=open_route(28,24,None,'Speakers (Clear Mic (VB-Audio Virtual Cable))')
            self.assertEqual(stream,'stream');self.assertIn('compatible',note)
    def test_foreign_route_is_not_replaced_after_failure(self):
        with patch('clear_mic.audio_service.sd.query_devices',return_value={'max_output_channels':2}),patch('clear_mic.audio_service.sd.Stream',side_effect=sd.PortAudioError('Unavailable')),patch('clear_mic.audio_service.resolve') as resolve:
            with self.assertRaises(sd.PortAudioError):open_route(28,24,None,'CABLE Input')
            resolve.assert_not_called()
