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


def block(start, end):
    """One launcher block, from the line starting `start` to the line `end`, inclusive."""
    head = LAUNCHER.index(start)
    return LAUNCHER[head:LAUNCHER.index(end, head) + len(end)]


class LauncherInstallSteps(unittest.TestCase):
    """The Apple-tools wait and the one-password Homebrew install, with stand-in tools."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="silver goose steps ")
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "log.txt"
        self.log.write_text("")

    def tearDown(self):
        self.temporary.cleanup()

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    def run_block(self, script):
        prelude = 'fail() { echo "FAIL: $*"; exit 1; }\nsleep() { :; }\n'
        return subprocess.run(
            ["/bin/bash", "-c", "set -euo pipefail\n" + prelude + script],
            env=dict(os.environ, PATH=str(self.bin) + ":/usr/bin:/bin", LOG=str(self.log),
                     COUNT=str(self.root / "count")),
            capture_output=True, text=True, timeout=60)

    def apple_tools(self, ready_after):
        self.tool("xcode-select", 'if [ "${1:-}" = --install ]; then echo install >> "$LOG"; exit 0; fi\n'
                  'n=$(( $(cat "$COUNT" 2>/dev/null || echo 0) + 1 )); echo $n > "$COUNT"\n'
                  '[ "$n" -ge %d ]\n' % ready_after)
        self.tool("xcrun", "exit 0\n")
        return self.run_block(block("sg_has_swift()", 'echo "Apple\'s Command Line Tools are installed."\nfi'))

    def test_waits_for_apple_tools_then_carries_on(self):
        result = self.apple_tools(ready_after=4)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("carries on by itself", result.stdout)
        self.assertIn("are installed", result.stdout)
        self.assertEqual(self.log.read_text().split(), ["install"])

    def test_gives_up_with_a_sentence_if_apple_tools_never_arrive(self):
        result = self.apple_tools(ready_after=10 ** 6)
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not finish installing", result.stdout)

    def test_homebrew_asks_for_the_password_once_and_runs_unattended(self):
        self.tool("sudo", 'echo "sudo $*" >> "$LOG"\n')
        self.tool("curl", 'while [ "$1" != -o ]; do shift; done\n'
                  'printf \'echo "installer NONINTERACTIVE=${NONINTERACTIVE:-}" >> "$LOG"\\n\' > "$2"\n')
        result = self.run_block(block("  if ! command -v brew", '    kill "$SG_SUDO_KEEPALIVE" 2>/dev/null || true\n  fi'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines.count("sudo -v"), 1)
        self.assertIn("installer NONINTERACTIVE=1", lines)
        self.assertIn("Type your Mac password", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
