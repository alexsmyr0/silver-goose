"""Where the launcher puts each person's library, in temporary home and app folders."""

import errno, fcntl, os, pathlib, subprocess, sys, tempfile, unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
import library_location as LL


def make_library(path, marker="mine"):
    (path / "assets" / "openart").mkdir(parents=True)
    (path / "data" / "openart").mkdir(parents=True)
    (path / "data" / "openart" / "manifest.csv").write_text(marker)
    return path


class LibraryLocation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="silver goose home ")
        base = pathlib.Path(self.temporary.name)
        self.home = base / "home"
        self.home.mkdir()
        self.target = self.home / "Movies" / "Silver Goose Library"

    def tearDown(self):
        self.temporary.cleanup()

    def app(self, name="Silver Goose"):
        root = pathlib.Path(self.temporary.name) / name
        (root / "source").mkdir(parents=True)
        return root

    def choose(self, root, previous=None):
        return LL.choose(root, previous, home=self.home, environ={})

    def history(self, library):
        return (library / "data" / "openart" / "manifest.csv").read_text()

    def test_fresh_install_copies_the_starter_library_out(self):
        root = self.app()
        make_library(root / "starter-library", "starter")
        self.assertEqual(self.choose(root), self.target)
        self.assertEqual(self.history(self.target), "starter")
        self.assertTrue((root / "starter-library").is_dir())     # copied, not used in place

    def test_older_copy_moves_its_library_out_of_the_app_folder(self):
        root = self.app()
        make_library(root / "library")
        self.assertEqual(self.choose(root), self.target)
        self.assertEqual(self.history(self.target), "mine")
        self.assertFalse((root / "library").exists())

    def test_new_version_unzipped_elsewhere_finds_the_old_library(self):
        old = self.app("Silver Goose old")
        make_library(old / "library")
        new = self.app("Silver Goose 2")
        make_library(new / "starter-library", "starter")
        self.assertEqual(self.choose(new, previous=old), self.target)
        self.assertEqual(self.history(self.target), "mine")      # not the starter

    def test_existing_library_wins_and_nothing_is_moved(self):
        make_library(self.target, "current")
        root = self.app()
        make_library(root / "library", "older")
        self.assertEqual(self.choose(root), self.target)
        self.assertEqual(self.history(self.target), "current")
        self.assertEqual(self.history(root / "library"), "older")

    def test_developer_checkout_keeps_library_beside_source(self):
        root = self.app()
        (root / ".git").mkdir()
        make_library(root / "library")
        self.assertEqual(self.choose(root), root.resolve() / "library")
        self.assertFalse(self.target.exists())

    def test_a_developer_checkout_is_never_emptied_by_a_delivered_copy(self):
        checkout = self.app("checkout")
        (checkout / ".git").mkdir()
        make_library(checkout / "library")
        delivered = self.app()
        self.choose(delivered, previous=checkout)
        self.assertTrue((checkout / "library").is_dir())

    def test_refuses_to_move_a_library_that_is_open(self):
        root = self.app()
        library = make_library(root / "library")
        (library / "work").mkdir()
        with open(library / "work" / "server.lock", "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(SystemExit) as stop:
                self.choose(root)
        self.assertIn("still open", str(stop.exception.code))
        self.assertTrue((root / "library").is_dir())
        self.assertFalse(self.target.exists())

    def test_another_disk_copies_and_keeps_the_original(self):
        root = self.app()
        make_library(root / "library")
        real_rename = os.rename

        def rename(source, target):
            if pathlib.Path(source) == root.resolve() / "library" and pathlib.Path(target) == self.target:
                raise OSError(errno.EXDEV, "Cross-device link")
            return real_rename(source, target)
        with patch.object(LL.os, "rename", side_effect=rename):
            self.assertEqual(self.choose(root), self.target)
        self.assertEqual(self.history(self.target), "mine")
        kept = root / "library (copied to Silver Goose Library)"
        self.assertEqual(self.history(kept), "mine")

    def test_launcher_entry_point_prints_only_the_folder(self):
        root = self.app()
        make_library(root / "library")
        result = subprocess.run(
            [sys.executable, str(ROOT / "source/library_location.py"), "--root", str(root)],
            env={k: v for k, v in dict(os.environ, HOME=str(self.home)).items() if k != "SG_LIBRARY"},
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), str(self.target))
        self.assertIn("Moved your Silver Goose library", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
