"""Media inspection and the existing cached native HDR-to-SDR conversion.

This move preserves the legacy first-import cache location. Importing paths still seeds
installation data; use a disposable install for verification. See docs/areas/production.md.
"""
import os
import re
import paths
from render_support import run

BASE = os.path.dirname(os.path.abspath(__file__))
# Existing binding, moved from make_farm. Do not change cache scope as part of extraction.
SDR_CACHE = os.path.join(paths.WORK, "sdr")

def is_hdr(path):
    """True for a clip straight off the phone: 10-bit, BT.2020, HLG.

    Steven's iPhone films in HDR. CapCut tone-maps it on export, so anything that came out of
    CapCut is fine - but a raw clip dropped into a pool is not, and mixing the two makes every
    shot after the first look pale and washed out. Measured on a real frame: brightness 119
    against 98 for the same moment in his own finished video, with the green channel 24 points
    high. It is not subtle and it is not a grade; it is the wrong transfer curve.
    """
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=color_transfer,color_primaries", "-of", "csv=p=0", path])
    t = (r.stdout or "").lower()
    return ("arib-std-b67" in t) or ("smpte2084" in t) or ("bt2020" in t)

def ensure_sdr(path):
    """An ordinary version of a clip, converting it once and keeping the result.

    ffmpeg cannot do this on this Mac - the tone-mapping filters need `zscale` and the Homebrew
    build has no libzimg, `colorspace` refuses HLG outright, and `tonemap` without a linearising
    step comes out far too dark. macOS does it properly, so `to_sdr.swift` does it, the same way
    the captions and the cover reader are done here.

    Cached on name, size and date: converting a 30-second clip is not free and the pools are
    used over and over.
    """
    if not is_hdr(path):
        return path
    try:
        st = os.stat(path)
        key = "%s__%d_%d.mp4" % (re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(path)),
                                 st.st_size, int(st.st_mtime))
    except Exception:
        return path
    os.makedirs(SDR_CACHE, exist_ok=True)
    out = os.path.join(SDR_CACHE, key)
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    exe = os.path.join(BASE, ".to_sdr")
    src = os.path.join(BASE, "to_sdr.swift")
    if (not os.path.exists(exe) or (os.path.exists(src) and
                                   os.path.getmtime(exe) < os.path.getmtime(src))):
        b = run(["swiftc", "-O", src, "-o", exe])
        if b.returncode != 0:
            print("  could not build the colour converter; leaving %s as it is"
                  % os.path.basename(path))
            return path
    print("  converting %s out of HDR (once)" % os.path.basename(path))
    r = run([exe, path, out])
    if r.returncode != 0 or not os.path.exists(out):
        print("  colour conversion failed for %s: %s"
              % (os.path.basename(path), (r.stderr or "")[:120]))
        return path
    return out

def dur(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path])
    try:
        return float((r.stdout or "0").strip())
    except Exception:
        return 0.0
