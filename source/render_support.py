"""Native render helpers and strict font checks."""

import math, os, subprocess, sys
from pathlib import Path

BASE = str(Path(__file__).resolve().parent)
FONT_NAME = "TikTok Display Medium"
CAPCUT_FONT = ""


def clip_frames(seconds, fps=30):
    """Retain the complete selected speech when a cut falls between output frames.

    Ignore only microsecond serialization noise at a frame boundary. The prepared
    picture may hold for the fractional frame; the selected sound is never cut short.
    """
    return max(2, int(math.ceil(seconds * fps - 0.0001)))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def die(msg):
    print("\n" + msg + "\n")
    sys.exit(1)


def font_name(path):
    """The name the font file gives for itself, read out of the file. "" if it cannot be read.

    Worth the thirty lines: on 27 Aug 2026 a whole batch of pump.fun videos was built in the
    macOS system font and every part of the tool called it a success. `os.path.exists` was the
    only check anything made, and a path that exists is not the same question as a font that
    loads - on that day the path was another Mac's home folder and existed nowhere at all.
    The renderers now refuse outright rather than substituting, so this is not what catches
    that any more; what this catches is the quieter version, a font.ttf that is there and is
    the WRONG font or a half-copied one. Same wrong videos, and no error either way.

    Reads name ID 4 (the full name) out of the `name` table. The table directory is laid out
    identically in TrueType and OpenType/CFF files, so it does not matter which this is.
    """
    import struct

    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12:
                return ""
            n_tables = struct.unpack(">H", head[4:6])[0]
            entries = f.read(16 * n_tables)
            off = length = None
            for i in range(n_tables):
                tag, _sum, o, l = struct.unpack(">4sIII", entries[16 * i : 16 * i + 16])
                if tag == b"name":
                    off, length = o, l
                    break
            if off is None:
                return ""
            f.seek(off)
            tbl = f.read(length)
            count, str_off = struct.unpack(">HH", tbl[2:6])
            for i in range(count):
                rec = tbl[6 + 12 * i : 18 + 12 * i]
                if len(rec) < 12:
                    break
                pid, _eid, _lid, nid, ln, o = struct.unpack(">HHHHHH", rec)
                if nid != 4:  # 4 is the full name
                    continue
                raw = tbl[str_off + o : str_off + o + ln]
                try:
                    s = raw.decode("utf-16-be" if pid == 3 else "latin-1")
                except Exception:
                    continue
                s = s.replace("\x00", "").strip()
                if s:
                    return s
    except Exception:
        pass
    return ""


def ensure_font(assets):
    import paths

    font = paths.asset("font.ttf", assets)
    if not os.path.isfile(font) or font_name(font) != FONT_NAME:
        raise ValueError(
            "Add the Classic font (TikTok Display Medium) in Assets before building."
        )
    return font


def ensure_renderer():
    return ensure_native("render_hook")


def ensure_native(name):
    source = os.path.join(BASE, name + ".swift")
    exe = os.path.join(BASE, "." + name)
    if not os.path.isfile(exe) or os.path.getmtime(exe) < os.path.getmtime(source):
        result = run(["swiftc", "-O", source, "-o", exe])
        if result.returncode:
            raise RuntimeError(
                "Could not compile " + name + ": " + result.stderr[-1500:]
            )
    return exe
