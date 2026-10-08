"""Check VM launcher display choices without booting or requiring QEMU."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class QemuHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'build' / 'output').mkdir(parents=True)
        self.iso = self.root / 'build' / 'output' / 'ascii-linux-amd64.iso'
        self.iso.write_bytes(b'argument-test fixture, not a bootable ISO')
        source = Path(__file__).resolve().parents[1] / 'build' / 'test-qemu.sh'
        self.script = self.root / 'build' / 'test-qemu.sh'
        shutil.copyfile(source, self.script)
        binary = self.root / 'bin'
        binary.mkdir()
        fake_qemu = binary / 'qemu-system-x86_64'
        fake_qemu.write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, sys\n'
            'with open(os.environ["ASCII_TEST_QEMU_RECORD"], "w") as handle:\n'
            '    json.dump(sys.argv[1:], handle)\n'
        )
        fake_qemu.chmod(0o755)
        self.record = self.root / 'qemu-arguments.json'
        self.env = dict(os.environ,
                        PATH=f'{binary}{os.pathsep}{os.environ.get("PATH", os.defpath)}',
                        ASCII_TEST_QEMU_RECORD=str(self.record))

    def run_helper(self, *options):
        return subprocess.run(['/bin/bash', str(self.script), *options],
                              env=self.env, text=True, capture_output=True,
                              timeout=10)

    def test_default_uses_graphical_display_for_x11(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(self.record.read_text())
        self.assertEqual(arguments[arguments.index('-display') + 1], 'gtk')
        self.assertEqual(arguments[arguments.index('-cdrom') + 1], str(self.iso))
        self.assertIn(arguments[arguments.index('-accel') + 1], ('kvm', 'tcg'))

    def test_console_selects_curses_and_explains_kernel_override(self):
        result = self.run_helper('--console')
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(self.record.read_text())
        self.assertEqual(arguments[arguments.index('-display') + 1], 'curses')
        self.assertIn('append ascii.console', result.stderr)

    def test_unknown_option_does_not_start_qemu(self):
        result = self.run_helper('--console', '--unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Usage:', result.stderr)
        self.assertFalse(self.record.exists())

    def test_help_works_before_building_iso(self):
        self.iso.unlink()
        result = self.run_helper('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[--uefi] [--console]', result.stdout)
        self.assertFalse(self.record.exists())


if __name__ == '__main__':
    unittest.main()
