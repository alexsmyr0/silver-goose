"""Reentrant ledger transactions across threads and processes.

The caller supplies the ledger path at entry. This module does not import application
paths, read campaign settings or migrate data. Use manifest.locked() in app code.
"""
import contextlib
import os
import threading

try:
    import fcntl
except ImportError:  # Retains the existing in-process fallback on non-POSIX systems.
    fcntl = None

# ------------------------------------------------------------------- one writer at a time
#
# THE LEDGER IS READ WHOLE, CHANGED, AND WRITTEN WHOLE, EVERYWHERE. That is fine on its own
# and unsafe the moment two things do it at once: both read the same file, each changes its
# own copy, and the second one to write wipes the first one's change. There is no version
# number and no merge - the last writer simply wins the whole file.
#
# TWO KINDS OF "AT ONCE" AND THEY NEED DIFFERENT ANSWERS:
#   * two THREADS - the panel's scan thread rolling the day over while a request thread
#     deletes a video. A plain lock object covers that.
#   * two PROCESSES - the panel and a builder, which is a separate `python3` entirely. A lock
#     object in memory means nothing to it; that needs a lock the operating system holds, so
#     it is `flock` on a small file beside the ledger.
# Both are taken, in that order, because holding only one of them closes only half of it.
#
# REENTRANT ON PURPOSE, and this is the part that would deadlock if it were not. A span that
# holds the lock goes on to call `write_rows`, which takes it again. `threading.RLock` allows
# that by itself, but `flock` does NOT: a second `open()` of the lock file is a new open file
# description, and asking for LOCK_EX on it would block against the lock this very thread is
# already holding. So the depth is counted per thread AND per ledger, and only the outermost
# span touches `flock` at all.
#
# PER LEDGER, NOT ONE FOR THE WHOLE TOOL. One process serves two campaigns and each has its
# own ledger; a single lock would make one campaign's build wait on the other's for no reason.
_GATES = {}                                   # ledger path -> threading.RLock
_GATES_LOCK = threading.Lock()
_HELD = threading.local()                     # per thread: ledger path -> how deep we are


def _gate(path):
    with _GATES_LOCK:
        g = _GATES.get(path)
        if g is None:
            g = _GATES[path] = threading.RLock()
        return g


@contextlib.contextmanager
def locked(path):
    """Hold the ledger for the whole of a read-change-write, across threads AND processes.

        with M.locked():
            rows = M.read_rows()
            ...change them...
            M.write_rows(rows)

    Wrap the READ as well as the write. Wrapping only the write serialises the writing and
    changes nothing about the losing: both readers still started from the same copy.

    Nothing here makes READING slow - `read_rows` does not take it, so the panel's four-second
    poll is untouched. Only writers wait, and only for each other.
    """
    held = getattr(_HELD, "depth", None)
    if held is None:
        held = _HELD.depth = {}
    if held.get(path):
        # Already ours, further up this same thread's stack. Count in and do nothing else.
        held[path] += 1
        try:
            yield
        finally:
            held[path] -= 1
        return
    gate = _gate(path)
    gate.acquire()
    f = None
    try:
        if fcntl is not None:
            try:
                d = os.path.dirname(path)
                if d:
                    os.makedirs(d, exist_ok=True)
                f = open(path + ".lock", "a+")
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError:
                if f is not None:
                    f.close()
                    f = None
                raise
        held[path] = 1
        yield
    finally:
        held[path] = 0
        if f is not None:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            f.close()
        gate.release()
