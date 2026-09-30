"""Normalized visible wording used to avoid duplicate covers."""
import re

def _norm(t):
    t = (t or "").lower()
    t = t.replace("|", " ")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()

def line_signature(hook_line, emoji=""):
    """WHAT A COVER CAN ACTUALLY TELL APART: the wording, with the emoji taken out.

    Public, and the single definition of it. `make_videos.py` uses this to refuse to build two
    videos that would be indistinguishable once posted, and it has to mean exactly the same
    thing there as it does here - a maker guarding against one definition while the reader works
    to another is a guard that does not guard.

    The emoji goes because Vision does not read it: it has its own column, and `_norm` strips
    whatever is left of it anyway. So "getting a job?? 😭" and "getting a job?? 🤓" are the SAME
    line as far as any cover is concerned, even though the ledger stores two different strings.
    """
    line = hook_line or ""
    e = (emoji or "").strip()
    if e:
        line = line.replace(e, "")
    return _norm(line)
