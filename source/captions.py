#!/usr/bin/env python3
"""captions.py - word-by-word captions, burned onto a clip.

Replaces the old version of this file, which used a downloaded Whisper model and was never in
use. Everything is on this Mac now: `speech.py` says which words were said and when, this draws
them and hands them to ffmpeg.

The look is not invented. It was measured across 173 of Steven's own CapCut projects and 9,259
caption chunks - see `render_hook.swift` for the numbers and where each came from. Two of those
measurements are worth repeating here because they contradict what "word by word" sounds like:

  - They are THREE-WORD chunks, not one word at a time. Half are three words, a quarter two,
    and only 2.8% are a single word.
  - Consecutive chunks BUTT UP with no gap, 97.7% of the time, and never overlap. A caption
    that blinks off between words reads as the video stuttering.

  python3 captions.py clip.mp4                  # what it would say, with timings
  python3 captions.py clip.mp4 out.mp4          # burn them on
"""
import json, os, re, subprocess, sys, tempfile

import paths

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import speech as SP

FPS = 30
W, H = 1080, 1920
RENDER = os.path.join(BASE, ".render_hook")
RENDER_SRC = os.path.join(BASE, "render_hook.swift")

# His captions carry no sentence punctuation - 97.8% of 9,259 chunks have none at all. But
# apostrophes are kept (don't, I'm, who's), and so are $ and %. Stripping those too would turn
# "$15,000" into "15000".
_DROP = re.compile(u"[.,!?;:\u2026\u2014\"\u201c\u201d]")


def clean(text, keep_caps=None):
    """His own captions the way they actually read: no sentence punctuation, and lower case.

    85% of his chunks are entirely lower case and only 6.8% start with a capital - that is what
    CapCut's transcriber produces and it is what his videos look like. Apple's recogniser
    writes proper sentences instead, so it is folded down to match. Brand names keep their
    capitals, because "claude" and "openart" written small look like a mistake rather than a
    style, and "I" stays a capital.
    """
    keep = {k.lower(): k for k in (keep_caps or [])}
    out = []
    for w in text.split():
        w = _DROP.sub("", w)
        if not w:
            continue
        bare = re.sub(r"[^A-Za-z0-9']", "", w).lower()
        if bare in keep:
            out.append(w if w.isupper() else keep[bare])
        elif bare in ("i", "i'm", "i've", "i'll", "i'd"):
            out.append(w[0].upper() + w[1:].lower())
        elif w.isupper() and len(w) <= 4:
            out.append(w)                      # AI, MCP - an acronym, not a shout
        else:
            out.append(w.lower())
    return " ".join(out)


def ensure_render():
    if os.path.exists(RENDER) and (not os.path.exists(RENDER_SRC)
                                   or os.path.getmtime(RENDER) >= os.path.getmtime(RENDER_SRC)):
        return True
    r = subprocess.run(["swiftc", "-O", RENDER_SRC, "-o", RENDER], capture_output=True, text=True)
    return r.returncode == 0


def caption_chunks(path, fps=FPS, vocab=None):
    """The chunks for a clip: text, start and end, ready to draw."""
    d = SP.transcribe(path)
    if not d.get("ok"):
        return None, d.get("error")
    if vocab is None:
        vocab = SP.read_vocab()
    keep = [v for v in vocab if not v.startswith("#")]
    out = []
    for c in SP.chunk(d["words"], fps=fps):
        t = clean(c["text"], keep_caps=keep)
        if t:
            out.append({"text": t, "start": c["start"], "end": c["end"]})
    return out, None


def font():
    """The Classic font for whichever campaign is asking, RIGHT NOW.

    This was `FONT = os.path.join(paths.ASSETS, "font.ttf")` at the top of the file until
    27 Aug 2026, which froze it at import - and the dashboard is one process serving two
    campaigns, so whichever campaign happened to import this module first handed its folder to
    the other one for the life of the panel. That is the exact fault `paths.__getattr__` exists
    to prevent, and CLAUDE.md lists it as a tripwire.

    It went through `render_support.ensure_font` at the same time rather than just building the
    path: that is the one place that knows where CapCut keeps the file, copies it per campaign,
    and checks the file really is TikTok Display Medium instead of only checking that
    something is there.
    """
    import render_support as RS
    return RS.ensure_font(paths.ASSETS)


def draw(chunks, out_dir, size=None, baseline=None):
    """One PNG per chunk, all in one run of the renderer."""
    if not ensure_render():
        raise RuntimeError("could not build the caption renderer (needs Xcode's swiftc)")
    spec = {"out_dir": out_dir, "font": font(),
            "chunks": [{"text": c["text"]} for c in chunks]}
    if size:
        spec["caption_size"] = size
    if baseline:
        spec["caption_baseline"] = baseline
    sp = os.path.join(out_dir, "capspec.json")
    json.dump(spec, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run([RENDER, sp], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("the renderer failed: %s" % (r.stderr or "")[:200])
    return [os.path.join(out_dir, "cap", "c%04d.png" % i) for i in range(len(chunks))]


def overlay_graph(chunks, pngs, first_input, base_label="0:v", fps=FPS, offset=0.0):
    """The ffmpeg filter chain that puts each chunk on screen for its own frames.

    Switched on by FRAME NUMBER, not by time. `enable='lt(t,X)'` looks equivalent and is not:
    X is written into the filter string rounded to a few decimals, and a frame whose own
    timestamp sits within that rounding lands on the wrong side of the test. That is a real
    one-frame error, and with a caption changing every 20 frames a one-frame error is visible
    as a stutter. Frame numbers are integers and cannot round.
    """
    graph, ins = [], []
    lab = base_label
    for i, c in enumerate(chunks):
        a = int(round((c["start"] + offset) * fps))
        b = int(round((c["end"] + offset) * fps))
        if b <= a:
            b = a + 1
        ins += ["-i", pngs[i]]
        nxt = first_input + i
        out = "cv%d" % i
        graph.append("[%s][%d:v]overlay=0:0:enable='gte(n,%d)*lt(n,%d)'[%s]"
                     % (lab, nxt, a, b, out))
        lab = out
    return ins, graph, lab


def burn(src, dst, chunks=None, fps=FPS):
    """A copy of the clip with the captions on it."""
    if chunks is None:
        chunks, err = caption_chunks(src, fps=fps)
        if chunks is None:
            raise RuntimeError(err)
    if not chunks:
        raise RuntimeError("nothing was said in that clip, so there is nothing to caption")
    tmp = tempfile.mkdtemp(prefix="caps_")
    pngs = draw(chunks, tmp)
    ins, graph, lab = overlay_graph(chunks, pngs, first_input=1, fps=fps)
    cmd = ([SP._ffmpeg(), "-y", "-loglevel", "error", "-i", src] + ins
           + ["-filter_complex", ";".join(graph), "-map", "[%s]" % lab, "-map", "0:a?",
              "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k", dst])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg refused: %s" % (r.stderr or "")[-400:])
    return dst


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[-3])
        sys.exit(1)
    src = args[0]
    chunks, err = caption_chunks(src)
    if chunks is None:
        print("could not do it:", err)
        sys.exit(1)
    if len(args) > 1:
        burn(src, args[1], chunks)
        print("wrote %s  (%d captions)" % (args[1], len(chunks)))
    else:
        print("%s - %d captions" % (os.path.basename(src), len(chunks)))
        for c in chunks:
            print("  %6.2f - %6.2f  %s" % (c["start"], c["end"], c["text"]))
