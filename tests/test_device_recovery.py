"""Routing regressions without opening microphones or changing Windows devices."""
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock,patch
import numpy as np
import backend
from clear_mic.audio_service import AudioService,record_preview


class DeviceRecoveryTests(unittest.TestCase):
    def create(self,stored,inventory,default=9):
        with patch.object(backend,'load',return_value=stored),patch.object(backend,'devices',return_value=inventory),patch.object(backend.sd,'stop'),patch.object(backend.sd,'_terminate'),patch.object(backend.sd,'_initialize'),patch.object(backend.sd,'query_hostapis',return_value=[{'name':'Windows WASAPI','default_output_device':default}]):
            return backend.Backend()

    def test_missing_saved_routes_are_preserved_even_with_other_devices_present(self):
        stored={'input':'My USB mic','output':'My virtual cable','listen':'My headphones','speakers':'My speakers'}
        inventory={'input':[('Webcam mic',1)],'output':[('Speakers',9),('CABLE Input',4),('Speakers (Clear Mic (VB-Audio Virtual Cable))',5)]}
        service=self.create(stored,inventory)
        for key,value in stored.items():self.assertEqual(service.settings[key],value)
        # Reconnecting the same endpoints makes the saved selections usable again.
        inventory['input'].append(('My USB mic',7));inventory['output'] += [(stored[k],20+i) for i,k in enumerate(('output','listen','speakers'))]
        with patch.object(backend,'devices',return_value=inventory),patch.object(backend.sd,'stop'),patch.object(backend.sd,'_terminate'),patch.object(backend.sd,'_initialize'):
            snapshot=service.refresh()
        self.assertIn('My USB mic',snapshot['devices']['input'])
        self.assertEqual(snapshot['settings']['input'],'My USB mic')

    def test_first_run_uses_physical_preview_even_when_windows_default_is_virtual(self):
        inventory={'input':[('VoiceMeeter Output',0),('USB mic',1)],'output':[('CABLE Input',9),('Headphones',10)]}
        service=self.create({},inventory)
        self.assertEqual(service.settings['input'],'USB mic')
        self.assertEqual(service.settings['listen'],'Headphones')
        self.assertEqual(service.settings['speakers'],'Headphones')

    def test_upgrade_turns_echo_cancellation_on_once(self):
        inventory={'input':[('USB mic',1)],'output':[('Monitor speakers',9),('CABLE Input',4)]}
        stored={'input':'USB mic','output':'CABLE Input','listen':'Monitor speakers','speakers':'Monitor speakers','echo_cancel':False}
        with patch.object(backend,'save') as save:
            service=self.create(stored,inventory)
        self.assertTrue(service.settings['echo_cancel']);self.assertTrue(service.settings['echo_v2'])
        save.assert_called_once();self.assertIn('echo cancellation is now on',service.notice)
        # After the upgrade, an explicit choice to turn it off is respected.
        with patch.object(backend,'save') as save:
            service=self.create({**stored,'echo_v2':True},inventory)
        self.assertFalse(service.settings['echo_cancel']);save.assert_not_called()

    def test_first_run_enables_echo_cancellation_only_with_physical_speakers(self):
        self.assertTrue(self.create({},{'input':[('USB mic',1)],'output':[('Headphones',9)]}).settings['echo_cancel'])
        self.assertFalse(self.create({},{'input':[('USB mic',1)],'output':[('CABLE Input',9)]}).settings['echo_cancel'])

    def test_saved_virtual_preview_device_is_replaced_with_physical_default(self):
        # Older versions could save a virtual cable for preview playback, which
        # left Play permanently disabled with a misleading "reconnect" message.
        inventory={'input':[('USB mic',1)],'output':[('CABLE Input',4),('Speakers (Focusrite USB Audio)',9),('Monitor',10)]}
        stored={'input':'USB mic','output':'CABLE Input','listen':'CABLE Input','speakers':'CABLE Input','echo_v2':True}
        service=self.create(stored,inventory,default=9)
        self.assertEqual(service.settings['listen'],'Speakers (Focusrite USB Audio)')
        self.assertEqual(service.settings['speakers'],'Speakers (Focusrite USB Audio)')
        # Unplugged physical choices are still preserved.
        service=self.create({**stored,'listen':'Headphones','speakers':'Headphones'},inventory,default=9)
        self.assertEqual(service.settings['listen'],'Headphones');self.assertEqual(service.settings['speakers'],'Headphones')

    def test_first_run_with_only_virtual_endpoints_leaves_physical_choices_empty(self):
        inventory={'input':[('VoiceMeeter Output',0)],'output':[('CABLE Input',9)]}
        service=self.create({},inventory)
        self.assertEqual(service.settings['input'],'')
        self.assertEqual(service.settings['listen'],'')

    def test_preview_cannot_capture_a_virtual_microphone(self):
        with patch('clear_mic.audio_service.sd.rec') as capture:
            with self.assertRaisesRegex(ValueError,'physical microphone'):record_preview('CABLE Output')
        capture.assert_not_called()

    def test_preview_cannot_play_into_virtual_feed(self):
        service=self.create({'listen':'CABLE Input'},{'input':[],'output':[('CABLE Input',9)]})
        service.preview=np.zeros(480,np.float32)
        with patch.object(backend.sd,'play') as play:
            with self.assertRaisesRegex(ValueError,'speakers or headphones'):service.handle({'action':'play','value':'original'})
        play.assert_not_called()

    def test_non_echo_preview_reports_dropped_samples(self):
        with patch('clear_mic.audio_service.com_apartment',return_value=nullcontext()),patch('clear_mic.audio_service.resolve',return_value=1),patch('clear_mic.audio_service.sd.rec',return_value=np.zeros((480,1),np.float32)),patch('clear_mic.audio_service.sd.wait',return_value=True),patch('clear_mic.audio_service.sd.stop'):
            with self.assertRaisesRegex(RuntimeError,'dropped samples'):record_preview('USB mic',.01)

    def run_stream(self,requested_stop):
        service=AudioService();stream=MagicMock();stream.active=False
        if requested_stop:stream.__enter__.side_effect=lambda:service.stop_event.set()
        with patch('clear_mic.audio_service.com_apartment',return_value=nullcontext()),patch('clear_mic.audio_service.resolve',return_value=1),patch('clear_mic.audio_service.Processor'),patch('clear_mic.audio_service.open_route',return_value=(stream,'')):
            service._run('USB mic','CABLE Input',None)
        return service.stats

    def test_unexpected_stream_end_reports_reconnection_instructions(self):
        stats=self.run_stream(False)
        self.assertEqual(stats['status'],'error')
        self.assertIn('Reconnect',stats['error'])

    def test_requested_stop_remains_a_normal_stop(self):
        self.assertEqual(self.run_stream(True)['status'],'stopped')

    def test_existing_settings_get_natural_echo_mode(self):
        service=self.create({'echo_cancel':True},{'input':[],'output':[]})
        self.assertEqual(service.settings['echo_mode'],'natural')

    def test_defaults_and_legacy_neural_upgrade_to_full_band_but_classic_is_preserved(self):
        service=self.create({'preset':'Singing'},{'input':[],'output':[]})
        self.assertEqual(service.settings['engine'],'fullband')
        self.assertEqual(self.create({'engine':'classic'},{'input':[],'output':[]}).settings['engine'],'classic')
        for engine in ('neural_clean','neural_echo'):
            service=self.create({'engine':engine},{'input':[],'output':[]})
            self.assertEqual(service.settings['engine'],'fullband')
            self.assertIn('16 kHz',service.snapshot()['notice'])

    def test_engine_is_validated_persisted_and_locked_during_live_audio(self):
        service=self.create({},{'input':[],'output':[]})
        with patch.object(backend,'save'):
            self.assertEqual(service.configure({'engine':'fullband'})['engine'],'fullband')
        with self.assertRaisesRegex(ValueError,'supported audio engine'):service.configure({'engine':'unknown'})
        with patch.object(type(service.service),'active',property(lambda _:True)):
            with self.assertRaisesRegex(ValueError,'Stop the microphone'):service.configure({'engine':'classic'})
        self.assertEqual(service.settings['engine'],'fullband')

    def test_echo_mode_is_validated_and_cannot_change_mid_stream(self):
        service=self.create({},{'input':[],'output':[]})
        with patch.object(backend,'save'):
            self.assertEqual(service.configure({'echo_mode':'strong'})['echo_mode'],'strong')
        with self.assertRaisesRegex(ValueError,'Natural voice'):service.configure({'echo_mode':'unknown'})
        with patch.object(type(service.service),'active',property(lambda _:True)):
            with self.assertRaisesRegex(ValueError,'Stop the microphone'):service.configure({'echo_mode':'natural'})
        self.assertEqual(service.settings['echo_mode'],'strong')
