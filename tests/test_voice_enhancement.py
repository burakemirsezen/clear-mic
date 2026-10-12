import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import sounddevice as sd
import soundfile as sf
from clear_mic.audio_service import open_route,process_clip,match_preview_level
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
        voice=np.random.default_rng(34).uniform(-.1,.1,RATE*3).astype(np.float32)
        output,_=echo_run(voice,np.zeros((len(voice),2),np.float32))
        np.testing.assert_array_equal(output[430:],voice[:-430])
        self.assertTrue(np.all(output[:430]==0))
    def test_echo_returns_to_transparent_voice_after_playback_tail(self):
        rng=np.random.default_rng(35);voice=speech(4)*.1
        reference=np.zeros((len(voice),2),np.float32);reference[:RATE*2]=rng.normal(0,.04,(RATE*2,2))
        output,_=echo_run(voice,reference)
        np.testing.assert_array_equal(output[RATE*3:],voice[RATE*3-430:-430])
    def test_inaudibly_quiet_playback_does_not_process_voice(self):
        voice=speech(2)*.1;reference=np.full((len(voice),2),.002,np.float32)
        output,_=echo_run(voice,reference)
        np.testing.assert_array_equal(output[430:],voice[:-430])
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
        self.assertFalse(physical_speaker('Speakers (Steam Streaming Speakers)'))
        self.assertTrue(physical_speaker('Speakers (USB Audio)'))
    def test_zero_noise_strength_keeps_voice_and_its_fixed_timeline(self):
        raw=np.random.default_rng(36).uniform(-.1,.1,RATE).astype(np.float32)
        voice=Voice(highpass=0,compressor=0,limiter=0,auto_level=0,noise_strength=0)
        output=process_clip(raw,voice)
        np.testing.assert_allclose(output,raw,atol=1e-7)
    def test_natural_strength_still_reduces_stationary_background_noise(self):
        raw=np.random.default_rng(37).normal(0,.006,RATE*4).astype(np.float32)
        voice=Voice(highpass=0,compressor=0,limiter=0,auto_level=0,noise_strength=90)
        output=process_clip(raw,voice)
        self.assertGreater(db(rms(raw[-RATE:])/rms(output[-RATE:])),12)
    def test_voice_detail_control_does_not_shift_consonant_timing(self):
        raw=np.zeros(RATE,np.float32);raw[RATE//2:RATE//2+12]=.1
        for strength in (0,75,90,100):
            voice=Voice(highpass=0,compressor=0,limiter=0,auto_level=0,noise_strength=strength)
            output=process_clip(raw,voice)
            self.assertTrue(np.isfinite(output).all())
            if strength<100:self.assertLess(abs(int(np.argmax(np.abs(output)))-RATE//2),12)
    def test_noise_strength_rejects_invalid_values(self):
        for value in (-1,101,float('nan')):
            with self.assertRaises(ValueError):Voice(noise_strength=value).validate()
    def test_preview_matching_uses_speech_not_suppressed_background(self):
        raw=np.full(RATE*3,.0005,np.float32);raw[RATE:RATE*2]=speech(1)*.04
        processed=raw.copy();processed[:RATE]=0;processed[RATE*2:]=0;processed[RATE:RATE*2]*=2
        matched=match_preview_level(raw,processed)
        self.assertAlmostEqual(rms(matched[RATE:RATE*2])/rms(processed[RATE:RATE*2]),1,places=5)
        np.testing.assert_array_equal(processed[:RATE],np.zeros(RATE,np.float32))
    def test_preview_matching_respects_peak_ceiling(self):
        raw=np.full(RATE,.001,np.float32);raw[RATE//2]=.9
        matched=match_preview_level(raw,raw*8)
        self.assertLessEqual(float(np.max(np.abs(matched))),10**(-1/20)+1e-6)
    def test_preview_matching_keeps_silence_and_final_partial_frame(self):
        for count in (17,FRAME+17):
            raw=np.zeros(count,np.float32)
            np.testing.assert_array_equal(match_preview_level(raw,raw),raw)
    def test_singing_does_not_depend_on_speech_detection(self):
        voice=PRESETS['Singing']
        self.assertEqual((voice.noise,voice.auto_level,voice.compressor,voice.limiter),(0,0,0,1))
    def test_singing_retains_low_and_high_held_notes(self):
        for frequency in (65,110,440,880):
            raw=(.1*np.sin(2*np.pi*frequency*np.arange(RATE*2)/RATE)).astype(np.float32)
            output=process_clip(raw,PRESETS['Singing'])
            change=db(rms(output[RATE:-FRAME])/rms(raw[RATE:-FRAME]))
            self.assertGreater(change,-.8);self.assertLess(abs(change),.8)
    def test_singing_keeps_vibrato_and_deliberate_volume_changes(self):
        t=np.arange(RATE*4)/RATE;frequency=220+5*np.sin(2*np.pi*5*t)
        raw=np.asarray(np.sin(np.cumsum(2*np.pi*frequency/RATE)),np.float32)
        raw[:RATE*2]*=.04;raw[RATE*2:]*=.1
        output=process_clip(raw,PRESETS['Singing'])
        self.assertGreater(float(np.corrcoef(raw[RATE:-FRAME],output[RATE:-FRAME])[0,1]),.96)
        ratio=rms(output[RATE*3:-FRAME])/rms(output[RATE:RATE*2-FRAME])
        self.assertAlmostEqual(ratio,2.5,delta=.05)
    def test_singing_preview_keeps_consonant_onset_without_rnnoise_delay(self):
        raw=np.zeros(RATE,np.float32);raw[RATE//2]=.1
        output=process_clip(raw,PRESETS['Singing'])
        self.assertEqual(int(np.argmax(np.abs(output))),RATE//2)
    def test_singing_over_referenced_backing_chords_retains_vocal(self):
        # Deterministic musical double-talk stress case, not a perceptual score.
        t=np.arange(RATE*12)/RATE;reference=np.empty((len(t),2),np.float32)
        reference[:,0]=.02*sum(np.sin(2*np.pi*f*t) for f in (261.63,329.63,392))
        reference[:,1]=.02*sum(np.sin(2*np.pi*f*t) for f in (196,246.94,293.66))
        echo=np.zeros(len(t),np.float32);echo[2400:]=reference[:-2400,0]*.5;echo[3100:]+=reference[:-3100,1]*.2
        phase=np.cumsum(2*np.pi*(220+5*np.sin(2*np.pi*5*t))/RATE)
        near=np.asarray(.07*np.sin(phase)+.02*np.sin(phase*2)+.01*np.sin(phase*3),np.float32);near[:RATE*4]=0
        residual,_=echo_run(echo,reference);mixed,_=echo_run(echo+near,reference)
        baseline,_=echo_run(near,np.zeros_like(reference));a=baseline[-RATE*2:];b=(mixed-residual)[-RATE*2:]
        self.assertGreater(db(rms(echo[-RATE*2:])/rms(residual[-RATE*2:])),20)
        self.assertGreater(db(rms(b)/rms(a)),-3)
        self.assertGreater(float(np.corrcoef(a,b)[0,1]),.9)
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
