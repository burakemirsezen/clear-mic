import unittest
from unittest.mock import patch
import numpy as np
from clear_mic.audio_service import resolve,process_clip,AudioService
from clear_mic.settings import Voice

class ServiceTests(unittest.TestCase):
    def test_saved_names_resolve_after_indices_change(self):
        with patch('clear_mic.audio_service.devices',return_value={'input':[('USB microphone',51)],'output':[]}):self.assertEqual(resolve('USB microphone','input'),51)
    def test_missing_device_gives_actionable_error(self):
        with patch('clear_mic.audio_service.devices',return_value={'input':[],'output':[]}):
            with self.assertRaisesRegex(RuntimeError,'Refresh devices'):resolve('Disconnected mic','input')
    def test_virtual_input_is_rejected_before_opening_audio(self):
        service=AudioService()
        with self.assertRaisesRegex(ValueError,'physical microphone'):service.start('Microphone (Steam Streaming Microphone)','CABLE Input',Voice())
    def test_preview_preserves_length_and_handles_final_partial_frame(self):
        source=np.random.default_rng(4).uniform(-.1,.1,4813).astype(np.float32)
        voice=Voice(noise=0,highpass=0,compressor=0,limiter=1,makeup_db=0)
        out=process_clip(source,voice)
        self.assertEqual(len(source),len(out));np.testing.assert_allclose(out,source,atol=1e-7)

if __name__=='__main__':unittest.main()
