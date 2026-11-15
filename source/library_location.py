"""Where a person's library lives, and the one-time move out of an app folder.

A delivered Silver Goose keeps its library outside the app folder, in
~/Movies/Silver Goose Library, so updating means replacing the Silver Goose folder and
nothing else. Movies rather than Documents: Documents is often synced to iCloud, and
footage that iCloud offloads would read as missing.

A Git checkout (a developer's copy) keeps `library/` beside `source/`, as before:
`scripts/package.py` reads the starter ingredients from there.

The launcher runs this before the panel starts. It prints the chosen folder on stdout
and explains anything it moved on stderr. It never deletes a library: a library on
another disk is copied and the original kept under a name that is never picked again.
"""

import argparse
import errno
import fcntl
import os
from pathlib import Path
import shutil
import sys

FOLDER_NAME = "Silver Goose Library"
STARTER = "starter-library"          # shipped in the ZIP; copied, never used in place
LOCKS = ("server.lock", "build.lock")  # held by a running panel / a running build


def say(message):
    print(message, file=sys.stderr, flush=True)


def home_library(home=None):
    return Path(home or Path.home()) / "Movies" / FOLDER_NAME


def developer_checkout(root):
    return (Path(root) / ".git").exists()


def is_library(path):
    path = Path(path)
    return path.is_dir() and ((path / "assets").is_dir() or (path / "data").is_dir())


def in_use(library):
    """True while a Silver Goose panel or build holds this library's locks."""
    for name in LOCKS:
        lock = Path(library) / "work" / name
        if not lock.is_file():
            continue
        with lock.open("a+") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream, fcntl.LOCK_UN)
    return False


def _unused_name(path):
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name("%s %d" % (path.name, n))
        n += 1
    return candidate


def _copy(source, target):
    """Copy into a temporary sibling first, so a half-finished copy is never the library."""
    partial = target.with_name(target.name + " (copying)")
    if partial.exists():
        shutil.rmtree(partial)          # only ever an earlier interrupted copy of ours
    shutil.copytree(source, partial, symlinks=True)
    os.rename(partial, target)


def move(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(source, target)       # same disk: instant, nothing copied
        say("Moved your Silver Goose library to: %s" % target)
        return
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
    _copy(source, target)
    kept = _unused_name(source.with_name("library (copied to %s)" % FOLDER_NAME))
    os.rename(source, kept)
    say("Copied your Silver Goose library to: %s\nThe original is kept at %s; "
        "delete it once you have checked your videos are there." % (target, kept))


def choose(root, previous=None, home=None, environ=None):
    """The library folder to use for the Silver Goose folder `root`.

    `previous` is the Silver Goose folder the launcher last ran from (its pointer file),
    so an older copy that kept its library inside its own folder is found even when the
    new version was unzipped somewhere else.
    """
    environ = os.environ if environ is None else environ
    root = Path(root).resolve()
    if environ.get("SG_LIBRARY"):
        return Path(environ["SG_LIBRARY"]).expanduser()
    if developer_checkout(root):
        return root / "library"
    target = home_library(home)
    older = [root / "library"]
    if previous and Path(previous).resolve() != root and not developer_checkout(previous):
        older.append(Path(previous).resolve() / "library")
    older = [path for path in older if is_library(path)]
    if target.exists():
        for path in older:
            say("Note: an older library is still at %s and is not used. "
                "Silver Goose uses %s." % (path, target))
        return target
    if older:
        if in_use(older[0]):
            raise SystemExit("Silver Goose is still open from %s. Close that Terminal window "
                             "(or wait for its build to finish), then start again."
                             % older[0].parent)
        move(older[0], target)
        return target
    if (root / STARTER).is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy(root / STARTER, target)
        say("Created your Silver Goose library at: %s" % target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--previous", default="")
    args = parser.parse_args()
    print(choose(args.root, args.previous or None))


if __name__ == "__main__":
    main()
