"""Preview comparisons must use the captured source and matching playback reference."""
import queue,unittest
from dataclasses import asdict
from unittest.mock import MagicMock,patch
import numpy as np
import backend
from clear_mic.settings import Voice


class PreviewControlTests(unittest.TestCase):
    def create(self,echo=False):
        service=backend.Backend.__new__(backend.Backend)
        service.service=MagicMock();service.service.active=False
        service.settings={'input':'USB mic','output':'CABLE Input','listen':'Headphones','speakers':'Speakers A','echo_cancel':echo,'echo_mode':'natural','engine':'fullband','preview_match':True,'voice':asdict(Voice())}
        service.preview=np.zeros(480,np.float32);service.preview_reference=np.zeros((480,2),np.float32) if echo else None
        service.preview_info={'input':'USB mic','speakers':'Speakers A' if echo else None,'has_reference':echo}
        service.preview_stamp=None;service.preview_cache=None;service.requests=queue.Queue();service.busy=False;service.emit=MagicMock()
        service.inventory={'input':[],'output':[]};service.notice=''
        return service

    def test_changing_speakers_rejects_old_reference_before_reprocessing(self):
        service=self.create(True);service.settings['speakers']='Speakers B'
        with patch.object(backend,'process_clip') as process,patch.object(backend.sd,'stop'),patch.object(backend.sd,'play') as play:
            for mode in ('processed','original'):
                with self.assertRaisesRegex(ValueError,'different speakers'):service.handle({'action':'play','value':mode})
        process.assert_not_called();play.assert_not_called()

    def test_original_without_volume_matching_can_still_play_after_route_change(self):
        service=self.create(True);service.settings.update(speakers='Speakers B',preview_match=False)
        with patch.object(backend,'process_clip') as process,patch.object(backend,'resolve',return_value=1),patch.object(backend.sd,'stop'),patch.object(backend.sd,'play') as play:
            service.handle({'action':'play','value':'original'})
        process.assert_not_called();self.assertIs(play.call_args.args[0],service.preview)

    def test_comparisons_reuse_processing_until_audio_settings_change(self):
        service=self.create();audio=np.full(480,.02,np.float32)
        with patch.object(backend,'process_clip',return_value=audio) as process:
            self.assertIs(service.processed_preview(),audio)
            service.settings['listen']='Different headphones';self.assertIs(service.processed_preview(),audio)
            service.settings['preview_match']=False;self.assertIs(service.processed_preview(),audio)
            self.assertEqual(process.call_count,1)
            service.settings['voice']['fullband_strength']=35;service.processed_preview()
            self.assertEqual(process.call_count,2)
            service.settings['engine']='classic';service.processed_preview();self.assertEqual(process.call_count,3)

    def test_old_playback_stops_before_new_audio_is_prepared(self):
        service=self.create();events=[]
        with patch.object(backend.sd,'stop',side_effect=lambda:events.append('stop')),patch.object(backend,'process_clip',side_effect=lambda *a:(events.append('process') or service.preview)),patch.object(backend,'resolve',return_value=1),patch.object(backend.sd,'play',side_effect=lambda *a,**kw:events.append('play')):
            service.handle({'action':'play','value':'processed'})
        self.assertEqual(events,['stop','process','play'])

    def test_failed_new_recording_cannot_leave_an_old_preview_labeled_ready(self):
        service=self.create(True);service.preview_cache=('old',service.preview.copy())
        with patch.object(backend.sd,'stop'),patch.object(backend.threading,'Thread') as thread,patch.object(backend,'record_preview',side_effect=RuntimeError('Device disconnected')):
            service.record();thread.call_args.kwargs['target']()
        self.assertFalse(service.snapshot()['preview_ready']);self.assertIsNone(service.preview_reference);self.assertIsNone(service.preview_info);self.assertIsNone(service.preview_cache)
        service.handle(service.requests.get_nowait())
        self.assertFalse(service.busy);self.assertFalse(service.snapshot()['preview_ready'])
        self.assertEqual(service.emit.call_args.args[0]['message'],'Device disconnected')

    def test_record_completion_keeps_source_identity_and_already_processed_audio(self):
        service=self.create(True);processed=np.full(480,.03,np.float32)
        captured=dict(service.settings);captured['voice']=dict(service.settings['voice'])
        service.settings={**service.settings,'voice':asdict(Voice(fullband_strength=35))}
        service.handle({'internal':'preview','raw':service.preview,'reference':service.preview_reference,'stamp':'123','settings':captured,'processed':processed})
        self.assertEqual(service.snapshot()['preview_info'],{'input':'USB mic','speakers':'Speakers A','has_reference':True})
        with patch.object(backend,'process_clip',return_value=processed) as process:
            service.processed_preview()
        self.assertEqual(process.call_args.args[1].fullband_strength,35)

    def test_enabling_echo_after_plain_preview_requires_new_recording_even_with_cache(self):
        service=self.create();service.preview_cache=(service.preview_key(service.settings),service.preview.copy());service.settings['echo_cancel']=True
        with patch.object(backend,'process_clip') as process:
            with self.assertRaisesRegex(ValueError,'new preview'):service.processed_preview()
        process.assert_not_called()
