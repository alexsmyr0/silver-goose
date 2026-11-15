"""Run the launcher's real environment setup with offline, temporary Mac folders."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
import venv


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "Start Silver Goose.command").read_text()
# Exercise only environment setup: no Homebrew, desktop pointer, native tools or panel.
SETUP = LAUNCHER.split("# A copied or interrupted environment", 1)[1].split(
    'SG_ENV_PYTHON=', 1
)[0]
SETUP = "# A copied or interrupted environment" + SETUP


class LauncherEnvironment(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="silver goose setup ")
        self.root = Path(self.temporary.name)
        self.env = self.root / ".venv"
        self.library = self.root / "library"
        self.library.mkdir()
        (self.library / "keep.txt").write_text("private ingredients")

    def tearDown(self):
        self.temporary.cleanup()

    def launch_setup(self):
        result = subprocess.run(
            ["/bin/bash", "-c", "set -euo pipefail\n" + SETUP],
            cwd=self.root,
            env=dict(os.environ, SG_ROOT=str(self.root), SG_PYTHON=sys._base_executable),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        subprocess.run(
            [str(self.env / "bin/python"), "-c",
             "import pathlib,pip,sys; assert pathlib.Path(sys.prefix)==pathlib.Path.cwd()/'.venv'"],
            cwd=self.root,
            check=True,
        )
        self.assertEqual((self.library / "keep.txt").read_text(), "private ingredients")

    def test_fresh_folder_and_repeated_launch(self):
        self.launch_setup()
        marker = self.env / "keep-installed-packages"
        marker.touch()
        self.launch_setup()
        self.assertTrue(marker.exists())
        self.assertEqual(list(self.root.glob(".venv-old-*")), [])

    def test_copied_broken_interpreter_links(self):
        bin_dir = self.env / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python3.12").symlink_to("/missing/other-mac/python3.12")
        (bin_dir / "python").symlink_to("python3.12")
        self.launch_setup()
        backups = list(self.root.glob(".venv-old-*/environment/bin/python3.12"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(os.readlink(backups[0]), "/missing/other-mac/python3.12")

    def test_interrupted_environment_without_pip(self):
        venv.EnvBuilder(with_pip=False).create(self.env)
        self.launch_setup()
        self.assertEqual(len(list(self.root.glob(".venv-old-*/environment"))), 1)

    def test_dangling_environment_directory_link(self):
        self.env.symlink_to(self.root / "missing-folder", target_is_directory=True)
        self.launch_setup()
        backups = list(self.root.glob(".venv-old-*/environment"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_symlink())


if __name__ == "__main__":
    unittest.main(verbosity=2)
