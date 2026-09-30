"""Local Apple speech recognition and saved wording corrections."""

import json, os, re, subprocess
import paths
from render_support import ensure_native

BASE = paths.BASE
EXE = os.path.join(BASE, ".transcribe")
DEFAULT_LOCALE = "en-US"
MAX_WORDS = 3
MAX_CHARS = 22
MAX_SECS = 1.5


def ensure_exe():
    ensure_native("transcribe")
    return True


def engine():
    return "apple"


def _cache():
    return os.path.join(paths.WORK, "speech")


def _fixes():
    return paths.data("caption_fixes.csv")


def _vocab():
    return paths.data("caption_vocab.txt")


def _ffmpeg():
    for b in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.exists(b):
            return b
    return "ffmpeg"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _key(path):
    from media_identity import source_fingerprint

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(path))
    return safe + "__" + source_fingerprint(path)


def _wav(path):
    """A 16kHz mono wav, made once and kept.

    The recogniser takes a plain audio file rather than a container, so the video handling
    stays on this side - the Swift only ever does the part only macOS can do. 16k mono is what
    the speech models want; handing them 48kHz stereo just makes them downmix it themselves.
    """
    os.makedirs(_cache(), exist_ok=True)
    out = os.path.join(_cache(), _key(path) + ".wav")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    r = run(
        [
            _ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            out,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(
            "could not read the sound out of %s: %s"
            % (os.path.basename(path), (r.stderr or "").strip()[:200])
        )
    return out


def read_fixes():
    """word-or-phrase -> what it should have been. Longest first, so a two-word fix wins over
    a one-word fix that is inside it."""
    out = []
    if not os.path.exists(_fixes()):
        return out
    try:
        import csvfile

        rows, _ = csvfile.read(_fixes())
    except Exception:
        return out
    for r in rows:
        a = (r.get("heard") or "").strip()
        b = (r.get("correct") or "").strip()
        if a:
            out.append((a, b))
    out.sort(key=lambda p: -len(p[0].split()))
    return out


def read_vocab():
    """Words to prime the recogniser with - brand names, mostly. One per line."""
    if not os.path.exists(_vocab()):
        return []
    try:
        body = open(_vocab(), encoding="utf-8").read()
    except Exception:
        return []
    return [
        l.strip()
        for l in body.splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]


def _norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def apply_fixes(words, fixes=None):
    """Replace known mishearings, keeping the timings.

    A multi-word fix collapses onto the span of the words it replaced, so "continent farm" ->
    "content farm" keeps the same start and end. Replacing two words with three would otherwise
    have to invent a timing, and an invented timing is exactly what this whole file is against.
    """
    if fixes is None:
        fixes = read_fixes()
    if not fixes or not words:
        return words, 0
    out = list(words)
    n_fixed = 0
    for heard, correct in fixes:
        want = [_norm(x) for x in heard.split()]
        if not want:
            continue
        i = 0
        while i + len(want) <= len(out):
            if [_norm(out[j]["text"]) for j in range(i, i + len(want))] == want:
                span = out[i : i + len(want)]
                rep = correct.split()
                start, end = span[0]["start"], span[-1]["end"]
                conf = min([w.get("confidence") or 0 for w in span] or [0])
                if not rep:  # empty correction = delete the words
                    out[i : i + len(want)] = []
                    n_fixed += 1
                    continue
                step = (end - start) / len(rep)
                new = [
                    {
                        "text": rep[k],
                        "start": start + k * step,
                        "end": start + (k + 1) * step,
                        "confidence": conf,
                        "fixed": True,
                    }
                    for k in range(len(rep))
                ]
                out[i : i + len(want)] = new
                n_fixed += 1
                i += len(new)
            else:
                i += 1
    return out, n_fixed


def _apple(path, locale, cache, refresh):
    """Apple's engine, through `.transcribe`. The words arrive already onset-corrected."""
    if not ensure_exe():
        raise RuntimeError(
            "could not build the speech recogniser (needs Xcode's swiftc)"
        )
    raw = _cached(cache, refresh)
    if raw is not None:
        return raw
    wav = _wav(path)
    cmd = [EXE, wav, "--locale", locale]
    vocab = read_vocab()
    if vocab:
        # Sent, and demonstrably ignored - see the note at the top. Kept because it costs
        # nothing and Apple may wire it up one day; it is NOT why the word list works.
        cmd += ["--context", ",".join(vocab)]
    r = run(cmd)
    try:
        raw = json.loads(r.stdout or "{}")
    except Exception:
        raise RuntimeError(
            (r.stderr or r.stdout or "the recogniser said nothing")[:300]
        )
    if not raw.get("ok"):
        raise RuntimeError(raw.get("error") or "recognition failed")
    _store(cache, raw)
    return raw


def _cached(cache, refresh):
    if not cache or refresh or not os.path.exists(cache):
        return None
    try:
        return json.load(open(cache, encoding="utf-8"))
    except Exception:
        return None


def _store(cache, raw):
    try:
        json.dump(raw, open(cache, "w", encoding="utf-8"))
    except Exception:
        pass


def chunk(words, max_words=MAX_WORDS, max_chars=MAX_CHARS, max_secs=MAX_SECS, fps=30):
    """Group words into the short bursts that go on screen, the way he does it.

    Three rules, all measured off his own projects:

    - Three words, and never more than about 22 characters. The character cap is what stops a
      chunk wrapping onto a second line, which he has essentially never done - 4 of 9,259.
    - **No gap.** 97.7% of his consecutive chunks butt up exactly, and none ever overlap. So a
      chunk runs until the next one starts rather than until its last word ends: a caption that
      disappears during a pause and comes back flickers, and he never does that.
    - Every boundary lands on a whole frame. A boundary between frames means the caption changes
      a frame early or late depending on which way the encoder rounds, and which way it rounds
      is not something to leave to chance.

    A long pause still breaks a chunk - a caption held across two seconds of silence reads as
    the video having lagged.
    """
    if not words:
        return []
    groups, cur = [], []
    for w in words:
        if cur:
            txt = " ".join(x["text"] for x in cur)
            gap = w["start"] - cur[-1]["end"]
            if (
                len(cur) >= max_words
                or len(txt) + 1 + len(w["text"]) > max_chars
                or (w["end"] - cur[0]["start"]) > max_secs
                or gap >= 0.6
            ):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    def snap(t):
        return round(t * fps) / float(fps)

    out = []
    for i, g in enumerate(groups):
        start = snap(g[0]["start"])
        if i + 1 < len(groups):
            nxt = snap(groups[i + 1][0]["start"])
            # Butt up to the next chunk unless there is a real silence between them, in which
            # case stop at the last word and leave the screen clean.
            gap = groups[i + 1][0]["start"] - g[-1]["end"]
            end = nxt if gap < 0.6 else snap(g[-1]["end"])
        else:
            end = snap(g[-1]["end"])
        if end <= start:
            end = start + 1.0 / fps
        out.append(
            {
                "text": " ".join(x["text"] for x in g),
                "start": start,
                "end": end,
                "words": g,
            }
        )
    return out


def find_phrase(words, phrase):
    """Where a phrase is spoken: (start, end), or None.

    Used to put a cutaway over the words it belongs to rather than at a fixed offset. Matching
    is on normalised words so punctuation and case do not decide it, and the FIRST occurrence
    wins - a phrase said twice is Steven's to disambiguate, not this function's to guess at.
    """
    want = [_norm(x) for x in phrase.split() if _norm(x)]
    if not want or not words:
        return None
    have = [_norm(w["text"]) for w in words]
    for i in range(len(have) - len(want) + 1):
        if have[i : i + len(want)] == want:
            return (words[i]["start"], words[i + len(want) - 1]["end"])
    return None


def transcribe(path, locale=DEFAULT_LOCALE, use_fixes=True, refresh=False, which=None):
    if which not in (None, "apple"):
        raise ValueError("Silver Goose uses local Apple speech recognition.")
    try:
        os.makedirs(_cache(), exist_ok=True)
        raw = _apple(
            path,
            locale,
            os.path.join(_cache(), _key(path) + "." + locale + ".json"),
            refresh,
        )
        words = raw.get("words") or []
        fixed = 0
        if use_fixes:
            words, fixed = apply_fixes(words)
        return dict(
            ok=True,
            words=words,
            text=" ".join(w["text"] for w in words),
            raw_text=raw.get("text", ""),
            locale=raw.get("locale"),
            duration=raw.get("duration"),
            fixed=fixed,
            engine="apple",
            note="",
        )
    except Exception as error:
        return dict(ok=False, error=str(error), engine="apple", note="")
