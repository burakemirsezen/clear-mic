import unittest
from unittest.mock import patch
import backend

OWN = 'Speakers (Clear Mic (VB-Audio Virtual Cable))'


class CreatedRoutingTests(unittest.TestCase):
    def create(self, migrated, extra=None):
        stored = {'input':'Physical mic','output':'Existing cable input','listen':'Speakers','created_device_selected':migrated}
        stored.update(extra or {})
        inventory = {'input':[('Physical mic',0)],'output':[('Existing cable input',1),(OWN,2),('Speakers',3)]}
        with patch.object(backend,'load',return_value=stored), patch.object(backend,'devices',return_value=inventory), patch.object(backend.sd,'stop'), patch.object(backend.sd,'_terminate'), patch.object(backend.sd,'_initialize'):
            return backend.Backend()

    def test_new_device_is_selected_on_first_available_boot(self):
        service = self.create(False)
        self.assertEqual(service.settings['output'],OWN)
        self.assertTrue(service.settings['created_device_selected'])

    def test_later_explicit_virtual_output_choice_is_preserved(self):
        service = self.create(True)
        self.assertEqual(service.settings['output'],'Existing cable input')

    def test_creation_can_select_own_device_again_after_removal(self):
        service = self.create(True)
        inventory = {'input':[('Physical mic',0)],'output':[('Existing cable input',1),(OWN,2),('Speakers',3)]}
        with patch.object(backend,'devices',return_value=inventory), patch.object(backend.sd,'stop'), patch.object(backend.sd,'_terminate'), patch.object(backend.sd,'_initialize'):
            service.refresh(prefer_created=True)
        self.assertEqual(service.settings['output'],OWN)

    def test_old_custom_voice_keeps_previous_noise_strength(self):
        service=self.create(True,{'preset':'Custom','voice':{'auto_level':0,'input_db':3}})
        self.assertEqual(service.settings['voice']['noise_strength'],100)
        self.assertEqual(service.settings['voice']['input_db'],3)
        self.assertEqual(service.settings['voice']['auto_level'],0)

    def test_old_natural_preset_gets_gentler_noise_strength(self):
        service=self.create(True,{'preset':'Natural speech','voice':{'auto_level':1}})
        self.assertEqual(service.settings['voice']['noise_strength'],90)
