import unittest
from unittest.mock import patch
import backend

OWN = 'Speakers (Clear Mic (VB-Audio Virtual Cable))'


class CreatedRoutingTests(unittest.TestCase):
    def create(self, migrated):
        stored = {'input':'Physical mic','output':'Existing cable input','listen':'Speakers','created_device_selected':migrated}
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
