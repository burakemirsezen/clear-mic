import json, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'vendor' / 'ClearMicDeviceSetup.exe'
PACKAGE = ROOT / 'vendor' / 'vbcable'


@unittest.skipUnless(HELPER.exists() and PACKAGE.exists(), 'Build the device helper and fetch its driver package first')
class DeviceSetupTests(unittest.TestCase):
    def run_helper(self, *args):
        result = subprocess.run([str(HELPER), *map(str, args)], capture_output=True, text=True, timeout=20)
        return result.returncode, json.loads(result.stdout)

    def test_original_driver_package_is_accepted(self):
        code, result = self.run_helper('--verify', PACKAGE)
        self.assertEqual(code, 0)
        self.assertTrue(result['package_verified'])

    def test_modified_driver_is_rejected_without_installation(self):
        lock = json.loads((ROOT / 'vbcable.lock.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            for name in lock['files']:
                shutil.copy2(PACKAGE / name, Path(folder) / name)
            with (Path(folder) / 'vbMmeCable64_win10.inf').open('ab') as file:
                file.write(b'\nmodified')
            code, result = self.run_helper('--verify', folder)
            self.assertNotEqual(code, 0)
            self.assertIn('checksum mismatch', result['error'])

    def test_missing_package_fails_before_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            code, result = self.run_helper('--verify', folder)
            self.assertNotEqual(code, 0)
            self.assertIn('missing', result['error'])

    def test_status_exposes_only_owned_audio_pair(self):
        code, result = self.run_helper('--status')
        self.assertEqual(code, 0)
        self.assertIsInstance(result['installed'], bool)
        self.assertIsInstance(result['foreign_vbcable'], bool)
        self.assertIsInstance(result['buffer_samples'], int)
        for endpoint in result['endpoints']:
            self.assertIn('Clear Mic (VB-Audio Virtual Cable)', endpoint['name'])
            self.assertNotIn('16 Ch', endpoint['name'])
            self.assertIn(endpoint['flow'], ['input', 'output'])

    def test_unknown_setup_action_is_rejected(self):
        code, result = self.run_helper('--install-arbitrary-driver')
        self.assertNotEqual(code, 0)
        self.assertIn('Unsupported', result['error'])
