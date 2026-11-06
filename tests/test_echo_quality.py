"""Fidelity regressions using real speech over simulated music/speech echo."""
import unittest
from scripts.measure_echo_quality import scenario,run,score,fullband_scenario,band_scores
from scripts.measure_voice import rms,db
import scripts.measure_playback as playback
import numpy as np
from clear_mic.echo import EchoCanceller
from clear_mic.processor import RATE,FRAME


class EchoQualityTests(unittest.TestCase):
    def test_natural_mode_preserves_spoken_voice_over_music(self):
        target,reference,acoustic=scenario('music')
        natural,_=run(target+acoustic,reference,True)
        strong,_=run(target+acoustic,reference,False)
        after=score(target,natural);before=score(target,strong)
        self.assertGreater(after['si_sdr_db'],before['si_sdr_db']+5)
        self.assertGreater(after['voice_gain_db'],-3)
        self.assertGreater(after['correlation'],.89)

    def test_quiet_voice_is_not_lost_under_music(self):
        target,reference,acoustic=scenario('music',.3)
        natural,_=run(target+acoustic,reference)
        result=score(target,natural)
        self.assertGreater(result['voice_gain_db'],-4)
        self.assertGreater(result['si_sdr_db'],3)

    def test_natural_mode_retains_voice_during_competing_speech(self):
        target,reference,acoustic=scenario('speech')
        natural,_=run(target+acoustic,reference,True)
        strong,_=run(target+acoustic,reference,False)
        self.assertGreater(score(target,natural)['si_sdr_db'],score(target,strong)['si_sdr_db']+2)

    def test_voice_protection_still_cancels_correlated_music_echo(self):
        _,reference,acoustic=scenario('music')
        residual,_=run(acoustic,reference)
        self.assertGreater(db(rms(acoustic[RATE*6:])/rms(residual[RATE*6:])),25)

    def test_upper_voice_bands_survive_low_frequency_speaker_music(self):
        # The original real-speech fixture was 16 kHz and could not expose an
        # accidental upper-band cutoff or overly aggressive AEC high-band mask.
        target,reference,acoustic=fullband_scenario()
        natural,_=run(target+acoustic,reference,True)
        strong,_=run(target+acoustic,reference,False)
        # Both modes now run separate AEC3 instances on the 8-16/16-24 kHz bands
        # instead of AEC3's single upper-band gain, so neither mode removes the
        # upper voice merely because low-frequency music is playing.
        for output in (natural,strong):
            scores=band_scores(target,output)
            for band in ('8500-12000','12000-18000'):
                self.assertGreater(scores[band]['output_power_change_db'],-3)

    def test_split_upper_bands_beat_single_upstream_upper_gain(self):
        # Broadband music (hi-hats/cymbals to 16 kHz) through a reverberant,
        # mildly distorting speaker path: upstream AEC3 then pulls all 8-24 kHz
        # voice down with its deepest 4-8 kHz gain. Real songs showed ~20 dB.
        target=playback.voice();reference=playback.music();echo=playback.room(reference);mic=target+echo
        outputs=[]
        for tuning in ((13,0,0),(13,1,1)):
            canceller=EchoCanceller(True,tuning);y=np.empty_like(mic)
            try:
                for i in range(0,len(mic),FRAME):canceller.process(mic[i:i+FRAME],reference[i:i+FRAME],y[i:i+FRAME])
            finally:canceller.close()
            outputs.append(playback.scores(target,echo,y,EchoCanceller.latency_samples))
        legacy,split=outputs
        for band in ('8500-12000','12000-18000'):
            self.assertGreater(split['band_voice_gain_db'][band],legacy['band_voice_gain_db'][band]+2.5)
            self.assertGreater(split['band_voice_gain_db'][band],-3)
        self.assertLessEqual(split['music_left_in_pauses_db'],legacy['music_left_in_pauses_db']+1)
