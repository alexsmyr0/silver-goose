#!/usr/bin/env python3
"""Content farm: full-take starting scene, speaking A, tutorial, speaking B.

The speaking pair stays together around an independently chosen tutorial. Each scene is
worth speaking pairs x tutorials x repeats (default 3), subject to unique
cover marks. Starting scenes retain their own recorded sound. Titles cover only the opening;
a song runs under all four clips. Per-clip levels, HDR conversion and frame rounding apply
to each segment. The former finished-rest pool is preserved but no longer used.

Pools: farm/scenes, farm/speaking (NAME-a / NAME-b), farm/tutorials, farm/songs.
Old opening halves remain excluded. Cutaways, floating logos, inserted robot answers,
manual timing and colour matching remain retired. This change was requested 10 Sep 2026.
"""
import argparse, math, json, os, random, re, shutil, sys, time

import csvfile
import wording_allowances as WA
import video_encode as VE
import encode as E
import formula as FM
import builder_support as BS
from media_source import ensure_sdr, dur
import render_support as RS
import manifest as M
import poolpick as PP
import openart_repurpose as RP
from media_identity import source_fingerprint

import paths
import tutorial_libraries as TL

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = paths.WORK
FARM_VARIANTS = {
    "farm": {"folder": "farm", "hooks": "farm_hooks.csv", "songs": "farm_songs.csv",
             "levels": "farm_levels.csv", "label": "content farm"},
    "mcp_farm": {"folder": "mcp content farm", "hooks": "mcp_farm_hooks.csv",
                 "songs": "mcp_farm_songs.csv", "levels": "mcp_farm_levels.csv",
                 "label": "MCP content farm"},
}
FARM_FORMAT = os.environ.get("SG_FARM_FORMAT", "farm")
if FARM_FORMAT not in FARM_VARIANTS:
    FARM_FORMAT = "farm"
HOOKS_CSV = paths.data(FARM_VARIANTS[FARM_FORMAT]["hooks"])


def variant(fmt=None):
    return FARM_VARIANTS.get(fmt or FARM_FORMAT, FARM_VARIANTS["farm"])


def asset_root(fmt=None):
    return variant(fmt)["folder"]


def hooks_path(fmt=None):
    return paths.data(variant(fmt)["hooks"])

W, H, FPS = 1080, 1920, 30
FADE_OUT = 0.35

# A title wording is retired like a hook line, but there are far fewer of these and they are
# far less interchangeable, so the ceiling is higher.
HOOK_RETIRE_AT = 40


def frames(seconds):
    """Seconds -> whole frames of the FINISHED video. Always the same way, in one place.

    THIS IS THE FIX FOR THE ONE-FRAME FLASH, and the fault it replaces is worth stating plainly
    because it looks like nothing. `int(round(x))` is BANKER'S rounding: Python rounds a half
    to the nearest EVEN number, so 26.5 goes DOWN to 26 and 27.5 goes UP to 28. Every length
    and every window in this builder went through it, and halves are not rare here - they are
    the normal case, because the pools are filmed at 60fps and the video is 30:

      * **6 of his 9 partner clips are an exact half frame long** (26.5, 27.5, 28.5 …), and the
        partner's length is part of `open_f`, the frame speaking A starts on. Every hand-set
        window is measured from there. So the SAME typed window landed on a different frame
        depending on which opening the video happened to use - 26.5 rounding down, 27.5 up.
      * **A window typed on a 60fps clip lands on a half frame whenever the frame number is
        odd**, and those halves were resolved by parity too. On his own `blue lights1` the logo
        start (175.5) rounded UP and the logo end (226.5) rounded DOWN - two identical cases,
        opposite directions, in the same window.

    Half-up, always. `math.floor(x + 0.5)` rather than `round()`, so nothing depends on whether
    a number happens to be odd. Rounding UP at a half is safe here because `norm_v` pads with
    `stop_mode=clone` - a cloned frame at a cut, not a black one.
    """
    return int(math.floor(seconds * FPS + 0.5))


SONG_FROM, MUSIC_GAIN = 0.25, 0.1412


def songs_csv(fmt=None):
    """Where the per-song settings live.

    A function and not a constant, deliberately: the dashboard imports this module and serves
    every campaign from one process, so a path bound at import time pins all of them to
    whichever campaign happened to be active first.
    """
    return paths.data(variant(fmt)["songs"])


def db_to_gain(db):
    """Decibels to the number ffmpeg wants. -17 dB is 0.1413, -15 dB is 0.1778."""
    try:
        return 10 ** (float(str(db).strip()) / 20.0)
    except Exception:
        return MUSIC_GAIN


def read_song_settings():
    """{filename: {"start": seconds, "gain": linear, "chance": percent or None}}

    Every column is optional and so is the whole file: a song with no row of its own starts at
    SONG_FROM, plays at MUSIC_GAIN, and shares whatever chance the named songs leave behind.
    That is what keeps adding a song to the folder enough on its own.
    """
    out = {}
    try:
        rows, _ = csvfile.read(songs_csv())
    except Exception:
        return out
    for r in rows:
        n = (r.get("song") or "").strip()
        if not n:
            continue
        start, db, chance = ((r.get("start") or "").strip(), (r.get("gain_db") or "").strip(),
                             (r.get("chance") or "").strip())
        try:
            start = float(start) if start else SONG_FROM
        except ValueError:
            start = SONG_FROM
        try:
            chance = float(chance) if chance else None
        except ValueError:
            chance = None
        out[n] = {"start": max(0.0, start),
                  "gain": db_to_gain(db) if db else MUSIC_GAIN,
                  "db": db, "chance": chance}
    return out


def read_song_settings_for(fmt):
    """Read another farm variant without changing current builder process."""
    out = {}
    try:
        rows, _ = csvfile.read(songs_csv(fmt))
    except Exception:
        return out
    for r in rows:
        n = (r.get("song") or "").strip()
        if not n:
            continue
        start = (r.get("start") or "").strip()
        db = (r.get("gain_db") or "").strip()
        chance = (r.get("chance") or "").strip()
        try: start = float(start) if start else SONG_FROM
        except ValueError: start = SONG_FROM
        try: chance = float(chance) if chance else None
        except ValueError: chance = None
        out[n] = {"start": max(0.0, start), "gain": db_to_gain(db) if db else MUSIC_GAIN,
                  "db": db, "chance": chance}
    return out


def pick_song(songs, settings, used):
    """Which song this video gets.

    Every other pool is SPREAD - handed out as evenly as the batch allows - but Steven asked
    for these by CHANCE: *"I want back in black to have only a 10% chance to be selected."* So
    a song with a chance gets exactly that chance and the ones without share what is left,
    equally. Over a short batch the count wobbles, because that is what a chance is - 10% of
    six videos is usually none, sometimes one, occasionally two.

    Falls back to the old even spread when no song has a chance set, so a folder with no
    settings file behaves exactly as it did before this existed.
    """
    if not songs:
        return None
    named = [x for x in songs if (settings.get(x) or {}).get("chance") is not None]
    if not named:
        return BS.pick_spread(songs, used)
    rest = [x for x in songs if x not in named]
    weights = {x: max(0.0, settings[x]["chance"]) for x in named}
    left = 100.0 - sum(weights.values())
    if rest:
        share = max(0.0, left) / len(rest)     # over 100% named leaves the rest on nothing
        for x in rest:
            weights[x] = share
    total = sum(weights.values())
    if total <= 0:                             # every chance was zero - nothing to choose from
        return BS.pick_spread(songs, used)
    r = random.uniform(0, total)
    acc = 0.0
    for x in songs:
        acc += weights.get(x, 0.0)
        if r <= acc:
            return x
    return songs[-1]


# ---- how many videos one starting scene is worth ---------------------------------------------
# THE x3 AT THE END OF HIS FORMULA, and it is the only number in this file that is his to move:
# a box on the panel's Settings tab, `formula.num("farm_repeats")`. Everything else in the
# formula is counted off what he has filmed.
#
# WHAT PAYS FOR THE SECOND ONE. Two videos off the same starting scene and the same title
# wording are the same picture for the first twenty seconds and carry the same words over it -
# so on the cover they are the same video, and the day one of them is posted the tool could not
# say which. What separates them is the MARK: the 2-3% zoom and few-pixel pan on the composed
# frame, applied after the caption, which this format has worn since 6 Sep 2026. That is the
# same thing that pays for CR7 saying one wording twice, and the measurement is the same one -
# six videos differing only by their mark were read back off a simulated Instagram cover 6 of 6
# right, gaps of 0.51 to 0.66 against a bar of 0.20, where a 1-5px nudge alone managed 0.211.
# See `repurpose.py`, and `make_pump.title_repeats()` for the same argument written out.
#
# So raising this past the number of marks available would be a real problem and nothing here
# would notice; `taken_marks` in `main()` is what actually holds the line, by refusing to give
# one (scene, wording) the same mark twice.
def repeats(path=None):
    """How many videos each (starting scene, speaking pair, tutorial) combination is worth."""
    return FM.num("farm_repeats", path)


def scene_cap(n_speaking, n_tutorials, path=None):
    """Lifetime allowance for a scene, shared by the builder and panel."""
    return max(0, int(n_speaking) * int(n_tutorials) * repeats(path))


PAIR_RE = re.compile(r"^(.*)-([ab])\.[^.]+$", re.I)


def old_half(name):
    """True for a file left over from the two-clip opening - `NAME-a.mp4` / `NAME-b.mp4`.

    Every scene Steven filmed between 26 Aug and 6 Sep 2026 is one of these, and NEITHER HALF
    IS A FULL TAKE: the `-a` half stops and leaves about ten seconds of silence for an mp3 that
    is not dropped in any more, and the `-b` half is the one line "better than yesterday". Used
    as starting scenes they would build forty videos that all break in the middle.

    Named and skipped, never silently included - a folder that looks full while nothing in it
    can be used is the thing that wastes an afternoon, and the fix here is a rename, not code.
    """
    return bool(PAIR_RE.match(os.path.basename(name or "")))


def live_wordings(path=None, fmt=None):
    """The title wordings still in play, as rows. ONE definition, because the formula counts
    them and the run spends them - the panel asking a slightly different question (a different
    default `retire_at`, say) would put a number on the Builder tab the run then misses.
    """
    rows, _ = WA.read(path or hooks_path(fmt))
    return [r for r in rows
            if BS.int_or(r.get(csvfile.USES_COL), 0)
            < BS.int_or(r.get("retire_at"), HOOK_RETIRE_AT)]


def die(msg):
    print("\n" + msg + "\n"); sys.exit(1)


def pool(folder, exts=(".mp4", ".mov", ".m4v")):
    try:
        return sorted(f for f in os.listdir(folder)
                      if f.lower().endswith(exts) and not f.startswith("."))
    except Exception:
        return []


def scenes_in(folder):
    """(the starting scenes, the old halves that were skipped)."""
    every = pool(folder)
    return [f for f in every if not old_half(f)], [f for f in every if old_half(f)]


def speaking_in(folder):
    """Complete A/B pairs and files that need fixing. Never guess between duplicate halves."""
    grouped, unused = {}, []
    for name in pool(folder):
        match = PAIR_RE.match(name)
        if not match:
            unused.append(name)
            continue
        key, side = match.group(1), match.group(2).lower()
        grouped.setdefault(key, {}).setdefault(side, []).append(name)
    pairs = {}
    for key, sides in grouped.items():
        if len(sides.get("a", [])) == len(sides.get("b", [])) == 1:
            pairs[key] = {side: names[0] for side, names in sides.items()}
        else:
            unused.extend(n for names in sides.values() for n in names)
    return pairs, sorted(unused)


def wording_signature(row):
    import cover_match as CM
    return CM.line_signature(BS.wrap((row.get("hook_text") or "").strip())
                             .replace("\n", " / "), "")


def recipe_history(ledger, assets=None, *, fmt=None):
    """Successful combinations and cover marks, including marks on historical farm videos."""
    import cover_match as CM
    counts, marks = {}, {}
    fmt = fmt or FARM_FORMAT
    library = TL.library_for("farm", assets) if fmt == "farm" else None
    for row in ledger:
        if row.get("status") != "ok" or row.get("format") != fmt:
            continue
        scene = M.scene_key(row.get("scene") or "")
        sig = CM.line_signature(row.get("hook_line") or "", row.get("emoji") or "")
        marks.setdefault((scene, sig), set()).add(
            (row.get("frame_mark") or "").strip() or RP.NORMAL_MARK)
        if library is not None and TL.row_library(row) != library:
            continue
        key = (scene, (row.get("speaking") or "").strip(),
               (row.get("tutorial") or "").strip())
        counts[key] = counts.get(key, 0) + 1
    return counts, marks


def remaining_by_scene(scenes, speaking, tutorials, wordings, ledger, fmt=None, *, assets=None):
    """Count actual remaining combinations, limited by scene allowance and distinct covers."""
    fmt = fmt or FARM_FORMAT
    counts, marks = recipe_history(ledger, assets, fmt=fmt)
    uses = M.scene_uses(ledger)
    cap = scene_cap(len(speaking), len(tutorials))
    rep, all_marks = repeats(), set(RP.marks())
    left = {}
    for filename in scenes:
        scene = M.scene_key(filename)
        # All title wordings share the same three uses of a speaking/tutorial combination.
        # They provide distinct covers, but do not multiply the scene's allowance.
        combos = sum(max(0, rep - counts.get((scene, sp, tut), 0))
                     for sp in speaking for tut in tutorials)
        covers = sum(len(all_marks - marks.get((scene, sig), set()))
                     for sig in {wording_signature(w) for w in wordings})
        available = min(combos, covers)
        left[scene] = min(available, max(0, cap - M.uses_of(uses, scene, fmt)))
    return left


def norm_v(i, want_frames):
    """Every pool is filmed on a phone and exported by hand, so nothing can be assumed about
    size, rotation or frame rate. Normalise before anything is joined, or the concat silently
    drops to the first clip's settings and the rest stretch.

    IT COMES OUT EXACTLY `want_frames` LONG, and that is the point rather than a detail. The
    builder works out where the cutaway and the logo go by adding clip lengths together; the
    finished video is whole frames; and until 26 Aug 2026 those two things were allowed to
    disagree. His partner clips are the clearest case - cut on a 60fps grid, 0.9167s long,
    which is **27.5 frames** at 30. The join has to emit 27 or 28 and the arithmetic went on
    believing 27.5, so every overlay after it was up to a frame out of step with the picture.
    A frame is all it takes: it showed as a flash of the wrong clip.

    `tpad` first so there is always something to trim, then `trim` by FRAME NUMBER, which has
    no rounding left in it. The pad is only ever reached when a clip is a hair short of its own
    rounded length, and then it is a single cloned frame at a cut - invisible.
    """
    return ("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
            "setsar=1,fps=%d,tpad=stop_mode=clone:stop_duration=0.5,"
            "trim=start_frame=0:end_frame=%d,setpts=PTS-STARTPTS,format=yuv420p[v%d]"
            % (i, W, H, W, H, FPS, want_frames, i))


def levels_csv(fmt=None):
    return paths.data(variant(fmt)["levels"])


LEVEL_COLS = ["pool", "clip", "gain_db", "measured_lufs", "measured_peak", "note"]


def read_levels():
    """{(pool, clip): gain in dB} - how much each clip's own sound is moved so that every video
    comes out at the same loudness as every other one.

    Steven, 26 Aug 2026: *"I need to adjust the volume on some of the tutorials ... so that the
    videos are all at good, consistent volumes."* He was right, and the measurement said which:
    his four tutorials ran -10.3, -11.1, -14.3 and **-20.5 LUFS**, so a video that drew the last
    one came out at half the loudness of a video that drew the first. Same story, smaller, in
    the scenes and the speaking parts.

    **THIS IS THE ONLY LEVELLING IN THE PROJECT AND IT IS PER CLIP, NOT PER VIDEO.** There is
    still no compressor, no limiter and no `loudnorm` anywhere - a clip is multiplied by one
    number and nothing about its shape changes. That matters because the alternative, running
    the finished mix through a normaliser, would pump the song up under the quiet parts.

    **EVERY GAIN IS A CUT, and that was forced by the material rather than chosen.** His clips
    come off a phone through CapCut and are already peak-limited: nearly all of them touch or
    exceed 0 dBFS true peak, and `connector.mp4` measures **+6.7**. Nothing here can be made
    LOUDER without distorting it, so the common level has to be one that everything can come
    DOWN to. -17.0 LUFS is the highest target that needs no clip boosted past its own headroom.

    Two clips cannot reach it and the file records what they got: `shison-01-a` is 0.2 dB short,
    which is nothing, and `tutorial3.mp4` is **2.0 dB** short even after the 1.5 dB its headroom
    allows. That one wants re-exporting louder; no amount of arithmetic here can fix a recording
    that quiet without clipping it.

    A missing file, a missing row or a bad number means a gain of 0 - the clip's own sound,
    untouched, exactly as it was before any of this existed. **That is also how to revert it:
    delete `farm_levels.csv`.**
    """
    out = {}
    try:
        rows, _ = csvfile.read(levels_csv())
    except Exception:
        return out
    for r in rows:
        pool = (r.get("pool") or "").strip()
        clip = (r.get("clip") or "").strip()
        if not pool or not clip:
            continue
        try:
            out[(pool, clip)] = float(r.get("gain_db") or 0)
        except (TypeError, ValueError):
            continue
    return out


def norm_a(i, want_frames, gain_db=0.0):
    """The same clip's sound, to exactly the same length. `apad` then `atrim`, in that order,
    for the same reason: the pad guarantees there is something to cut.

    `gain_db` is this clip's own levelling - see `read_levels`. It is applied BEFORE the pad and
    the trim so the padding is silence at the new level rather than at the old one."""
    secs = want_frames / float(FPS)
    vol = ("volume=%.4f," % (10 ** (gain_db / 20.0))) if abs(gain_db) > 0.05 else ""
    return ("[%d:a]aresample=%d,%sapad=pad_dur=0.5,atrim=0:%.6f,asetpts=PTS-STARTPTS[a%d]"
            % (i, E.AUDIO_RATE, vol, secs, i))


def build_one(out_path, scene, speaking_a, tutorial, speaking_b, song, caption_png,
              song_from=SONG_FROM, music_gain=MUSIC_GAIN, look="plain", mark="", assets=None):
    """Join scene, speaking A, tutorial, speaking B at their full lengths.

    The opening title disappears on the first speaking frame. Every clip keeps its audio,
    with silence supplied for clips without an audio stream, and music under the whole video.
    """
    from storage_guard import require_space
    require_space(os.path.dirname(out_path))
    tutorial_library = TL.library_for("farm", assets) if FARM_FORMAT == "farm" else None
    # Remember what each clip is CALLED before the colour conversion renames it: the per-clip
    # levelling is looked up by the pool file's own name, and `ensure_sdr` hands back a cache
    # file called something like "desk.mp4__12345_1690000000.mp4", which matches nothing.
    originals = [scene, speaking_a, tutorial, speaking_b]
    # Anything filmed on the phone and not passed through CapCut is HDR, and joining HDR to SDR
    # makes everything after the first clip look washed out. Convert once, cache, carry on.
    parts = [ensure_sdr(x) for x in originals]
    lens = [dur(p) for p in parts]
    if min(lens) <= 0:
        return False, "one of the clips has no length", {}

    # ---- EVERYTHING FROM HERE IS COUNTED IN FRAMES ----------------------------------------
    # Seconds are what the pools are measured in and frames are what a video is made of, and
    # the two must not be mixed. Every length is rounded to whole frames ONCE, here, and each
    # clip is then forced to exactly that many by `norm_v` - so the arithmetic below and the
    # picture on screen cannot drift apart.
    nf = [max(1, frames(x)) for x in lens]
    scene_f = nf[0]                                      # where speaking A begins
    total_f = sum(nf)
    total = total_f / float(FPS)

    # Which pool each clip came from, so its levelling can be looked up. Keyed on the ORIGINAL
    # name, captured before ensure_sdr renamed it.
    levels = read_levels()
    part_pools = list(zip(("scenes", "speaking", "tutorials", "speaking"), originals))
    ins, fv, fa = [], [], []
    for i, p in enumerate(parts):
        ins += ["-i", p]
        pl, nm = part_pools[i]
        level_name = os.path.basename(nm or "")
        if pl == "tutorials" and tutorial_library and tutorial_library != "farm":
            level_name = tutorial_library + "/" + level_name
        g = levels.get((pl, level_name), 0.0)
        fv.append(norm_v(i, nf[i]))
        audio = RS.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=index", "-of", "csv=p=0", p])
        if (audio.stdout or "").strip():
            fa.append(norm_a(i, nf[i], g))
        else:
            fa.append("anullsrc=r=%d:cl=stereo,atrim=0:%.6f,asetpts=PTS-STARTPTS[a%d]"
                      % (E.AUDIO_RATE, nf[i] / float(FPS), i))
    graph = fv + fa
    graph.append("".join("[v%d][a%d]" % (i, i) for i in range(len(parts))) +
                 "concat=n=%d:v=1:a=1[cvraw][ca]" % len(parts))
    # THE JOINED PICTURE IS PUT BACK ON A 30ths CLOCK. `concat` hands its output back in
    # MICROSECONDS - ffmpeg's own AV_TIME_BASE - and a thirtieth of a second is not a whole
    # number of them, so the stream drifts a microsecond or two under where it should be.
    # Measured on the old seven-pool build, that drift made an overlay on a clean 1/30 clock
    # hold a frame and then skip one, ten times a second, on one video in five. There is only
    # the caption overlaid now and it is switched by frame number, but the fix costs nothing
    # and the fault it prevents took two days to find - see git for the frame-by-frame trace.
    graph.append("[cvraw]settb=1/%d,setpts=N[cv]" % FPS)

    nxt = len(parts)
    # THE TITLE WORDING, over the starting scene and off at the cut.
    #
    # `lt`, never `between` - `between` includes its end, and that end is the first frame of
    # speaking A. Both the caption and the cut are counted in whole frames, so there
    # is no rounding left to put the wording one frame into his own edit.
    ins += ["-i", caption_png]
    graph.append("[cv][%d:v]overlay=0:0:enable='lt(n,%d)'[vcap]" % (nxt, scene_f))
    nxt += 1
    # THE MARK AND THE LOOK GO LAST, on the composed frame - the same two levers CR7 wears and
    # the same function (`repurpose.tail_vf`). AFTER the caption, deliberately: the mark is what
    # makes two videos off one scene and one wording different pictures on the cover, so it has
    # to be applied to the thing a cover reader actually sees, wording included. `null` when
    # there is neither, so the graph always ends on the same label.
    graph.append("[vcap]%s[vout]" % (RP.tail_vf(mark, look, W, H) or "null"))

    # -ss BEFORE -i, so ffmpeg seeks the song rather than decoding and throwing away the front
    # of it. Per song: these are records, and where the riff starts is not the same place in
    # two of them.
    ins += ["-ss", "%.3f" % song_from, "-i", song]
    graph.append("[%d:a]aresample=%d,atrim=0:%.3f,asetpts=PTS-STARTPTS,volume=%.4f,"
                 "afade=t=out:st=%.3f:d=%.2f[mus]"
                 % (nxt, E.AUDIO_RATE, total, music_gain, max(total - FADE_OUT, 0), FADE_OUT))
    nxt += 1
    # normalize=0 or amix quietly divides everything by the number of inputs, which would drop
    # his voice by half the moment the song is mixed in.
    graph.append("[ca][mus]amix=inputs=2:duration=first:normalize=0[aout]")

    cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + ins +
           ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
            # encode.audio_args(), not spelled out here - see encode.AUDIO_RATE.
            ] + E.audio_args() + ["-movflags", "+faststart",
            "-t", "%.3f" % total, out_path])
    r = VE.run(cmd, runner=RS.run, label='Content Farm')
    # What actually happened, for the ledger and the log.
    note = {"song_from": song_from, "song_gain": music_gain,
            "scene_len": round(scene_f / float(FPS), 3),
            "speaking_a_len": round(nf[1] / float(FPS), 3),
            "tutorial_len": round(nf[2] / float(FPS), 3),
            "speaking_b_len": round(nf[3] / float(FPS), 3),
            "total_len": round(total, 3)}
    if r.returncode != 0 or not os.path.exists(out_path):
        return False, ("ffmpeg failed: " + (r.stderr or "")[-400:]).strip(), note
    return True, "", note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", type=int, default=1, help="how many videos to build")
    ap.add_argument("--assets", default=paths.ASSETS)
    ap.add_argument("--out", default=paths.output(FARM_FORMAT))
    a = ap.parse_args()

    A = os.path.abspath(a.assets)
    testing = A != paths.ASSETS
    if not testing:
        import catalog as CP
        if FARM_FORMAT not in CP.formats(paths.product()):
            die("Content farm is not enabled for this content type.")
    OUT = os.path.abspath(a.out)
    os.makedirs(OUT, exist_ok=True)

    STATE = os.path.join(OUT, "state") if testing else WORK
    fmt = FARM_FORMAT
    root = asset_root(fmt)
    hooks_file = HOOKS_CSV
    if testing:
        os.makedirs(STATE, exist_ok=True)
        M.MANIFEST = os.path.join(STATE, "manifest.csv")
        M.VIDEOS = OUT
        hooks_file = os.path.join(STATE, variant(fmt)["hooks"])
        if not os.path.exists(hooks_file) and os.path.exists(HOOKS_CSV):
            shutil.copy2(HOOKS_CSV, hooks_file)
        print("  test run - ledger, counts and wordings kept in %s" % STATE)

    scenes, halves = scenes_in(paths.asset(root + "/scenes", A))
    speaking, unused_speaking = speaking_in(paths.asset(root + "/speaking", A))
    tutorial_folder = TL.folder_for("farm", A) if fmt == "farm" else paths.asset(root + "/tutorials", A)
    tutorials = pool(tutorial_folder, TL.EXTENSIONS)
    if fmt == "farm":
        tutorials = TL.eligible_names("farm", tutorials, assets=A)
    songs = pool(paths.asset(root + "/songs", A), (".m4a", ".mp3", ".wav", ".aac"))

    # NAMED, NOT SILENTLY DROPPED. Every scene filmed between 26 Aug and 6 Sep 2026 is half of
    # an old pair and none of them is a full take - see `old_half()`. A folder that looks full
    # while nothing in it can be used is exactly the thing that wastes an afternoon, and the
    # fix here is a rename.
    if halves:
        print("  not used, filmed for the old two-clip opening: %s" % ", ".join(halves))
        print("  a starting scene is ONE file now, one full take with the robot answering in "
              "its own sound. Rename one to use it.")

    if unused_speaking:
        print("  speaking files not used (need one A and one B per pair): "
              + ", ".join(unused_speaking))
    missing = [n for n, p in (("starting scenes", scenes), ("complete speaking pairs", speaking),
                              ("tutorials", tutorials),
                              ("songs", songs)) if not p]
    if missing:
        die("Nothing to build with - these are empty:\n  %s\n\nAdd them on the Assets tab."
            % "\n  ".join(missing))

    # Read once, before the batch, and SAID OUT LOUD - a song at 10% can be absent from a whole
    # run of six, and "where did Back in Black go" is a much worse question than a line of log.
    song_set = read_song_settings()
    named = [x for x in songs if (song_set.get(x) or {}).get("chance") is not None]
    if named:
        share = max(0.0, 100.0 - sum(song_set[x]["chance"] for x in named))
        rest_songs = [x for x in songs if x not in named]
        bits = ["%s %g%%" % (x, song_set[x]["chance"]) for x in named]
        bits += ["%s %g%%" % (x, share / len(rest_songs)) for x in rest_songs]
        print("  songs by chance: " + ", ".join(bits))
        if rest_songs and share <= 0:
            print("  WARNING: the named songs take 100%% or more, so %s can never be picked"
                  % ", ".join(rest_songs))

    rows, fields = WA.read(hooks_file)
    ucol = csvfile.USES_COL
    if rows and ucol not in fields:
        fields = list(fields) + [ucol]
    live = [r for r in rows
            if BS.int_or(r.get(ucol), 0) < BS.int_or(r.get("retire_at"), HOOK_RETIRE_AT)]
    if not live:
        die("No title wordings left in %s.\nAdd one, or bring a retired one back."
            % os.path.basename(hooks_file))

    font = RS.ensure_font(A)
    renderer = RS.ensure_renderer()
    tmp = os.path.join(STATE, "farm_tmp")
    os.makedirs(tmp, exist_ok=True)
    batch = time.strftime("%m%d-%H%M")

    # Same rule as everywhere else here: least-used in THIS batch first, then least-used ever,
    # ties at random. One scene is meant to make several videos, so the levers either side of
    # it have to move every single time or they are not levers.
    used = {k: {} for k in ("scene", "speaking", "tutorial", "song", "hook", "look", "mark")}
    # THE GRADE AND THE ZOOM, counted off the ledger like every other pool so they level over
    # time and never repeat back to back - `poolpick.pick`'s three counters. Farm rows only.
    look_life, mark_life, look_recent, mark_recent = {}, {}, [], []
    for _r in M.read_rows():
        if _r.get("status") != "ok" or (_r.get("format") or "").strip() != fmt:
            continue
        for _col, _life, _recent in (("look", look_life, look_recent),
                                     ("frame_mark", mark_life, mark_recent)):
            _v = (_r.get(_col) or "").strip()
            if _v:
                _life[_v] = _life.get(_v, 0) + 1
                _recent.append(_v)

    # THE SCENE COUNTER STARTS FROM WHAT EACH SCENE HAS ALREADY SPENT, not from zero. Every
    # other counter here is per-batch and that is right for them, but a starting scene has a
    # LIFETIME limit, and a counter that forgets is a counter that cannot enforce one. Counted
    # off the ledger, not kept in a file of its own - Steven overturned a separate counter on
    # 26 Aug 2026, because deleting a video is MEANT to hand its use back, and once that is so
    # a counter file is only a second copy of a fact the ledger already holds.
    # Fresh rows rather than the cached answer: this run is about to spend what it says.
    ledger = M.read_rows()
    scene_uses = {k: v.get(fmt, 0) for k, v in M.scene_uses(ledger).items() if v.get(fmt)}
    used["scene"] = dict(scene_uses)

    combinations, taken_marks = recipe_history(ledger, A, fmt=fmt)
    rep = repeats()
    by_key = {M.scene_key(s): s for s in scenes}

    def sig_of(row):
        return wording_signature(row)

    def free_marks(scene, sig):
        return [m for m in RP.marks() if m not in taken_marks.get((scene, sig), ())]

    remaining = remaining_by_scene(scenes, speaking, tutorials, live, ledger, fmt, assets=A)
    print("  %d starting scenes x (%d speaking pairs x %d tutorials x %d)"
          " = %d possible, %d left after previous uses and cover limits"
          % (len(scenes), len(speaking), len(tutorials), rep,
             len(scenes) * scene_cap(len(speaking), len(tutorials)),
             sum(remaining.values())))
    if not any(remaining.values()):
        die("Every starting scene has made all it may. Add a scene, speaking pair, "
            "or tutorial. If the cover limit is reached, add a scene or wording.")

    made, delta = 0, {}
    for _ in range(max(1, a.make)):
        live = [r for r in rows
                if BS.int_or(r.get(ucol), 0) < BS.int_or(r.get("retire_at"), HOOK_RETIRE_AT)]
        if not live:
            print("  (out of title wordings - stopping)"); break

        # Only choose scenes that still have an actual combination and a distinct cover.
        avail = [key for key in by_key if remaining.get(key, 0) > 0]
        options = {}
        for key in avail:
            choices = [(sp, tut, w) for sp in speaking for tut in tutorials for w in live
                       if combinations.get((key, sp, tut), 0) < rep
                       and free_marks(key, sig_of(w))]
            if choices:
                options[key] = choices
        if not options:
            print("  (no combinations with distinct covers left - stopping)"); break
        scene = BS.pick_spread(sorted(options), used["scene"])
        scene_file = by_key[scene]
        used["scene"][scene] = used["scene"].get(scene, 0) + 1
        open_pairs = options[scene]
        speaking_key = BS.pick_spread(sorted({sp for sp, _, _ in open_pairs}), used["speaking"])
        tutorial_file = BS.pick_spread(sorted({t for sp, t, _ in open_pairs
                                               if sp == speaking_key}), used["tutorial"])
        used["speaking"][speaking_key] = used["speaking"].get(speaking_key, 0) + 1
        used["tutorial"][tutorial_file] = used["tutorial"].get(tutorial_file, 0) + 1
        available_words = [w for sp, t, w in open_pairs
                           if sp == speaking_key and t == tutorial_file]
        hook = sorted(available_words, key=lambda r: (used["hook"].get(str(r.get("id")), 0),
                                                     BS.int_or(r.get(ucol), 0), random.random()))[0]
        text = BS.wrap((hook.get("hook_text") or "").strip())
        sig = sig_of(hook)
        hid = str(hook.get("id"))
        used["hook"][hid] = used["hook"].get(hid, 0) + 1

        song = pick_song(songs, song_set, used["song"])
        used["song"][song] = used["song"].get(song, 0) + 1
        ss = song_set.get(song) or {}
        # The look and the mark - see the note above `scene_cap`. The mark is picked from the
        # ones this (scene, wording) has NOT worn, which is the guard, and then spread across
        # the batch and the ledger like every other pool.
        look = PP.pick(list(RP.LOOK_NAMES), look_life, used["look"], look_recent)
        used["look"][look] = used["look"].get(look, 0) + 1; look_recent.append(look)
        mark = PP.pick(free_marks(scene, sig), mark_life, used["mark"], mark_recent)
        used["mark"][mark] = used["mark"].get(mark, 0) + 1; mark_recent.append(mark)

        spec = {"out_dir": tmp, "line": text, "money": "", "font": font, "format": fmt,
                "claude_logo": "", "shorts_logo": "",
                "jitter_line": [random.uniform(-3, 3), random.uniform(-3, 3)],
                "jitter_cards": [0, 0], "jitter_money": [0, 0]}
        sp_path = os.path.join(tmp, "spec.json")
        with open(sp_path, "w") as spec_file:
            json.dump(spec, spec_file, ensure_ascii=False)
        r = RS.run([renderer, sp_path])
        if r.returncode != 0:
            die("The caption renderer failed:\n" + (r.stderr or "")[:400])

        scene_path = os.path.join(paths.asset(root + "/scenes", A), scene_file)
        scene_sha256 = source_fingerprint(scene_path)
        idx, out = M.claim_id(OUT)
        name = os.path.basename(out)
        ok, err, note = build_one(
            out, scene_path,
            os.path.join(paths.asset(root + "/speaking", A), speaking[speaking_key]["a"]),
            os.path.join(tutorial_folder, tutorial_file),
            os.path.join(paths.asset(root + "/speaking", A), speaking[speaking_key]["b"]),
            os.path.join(paths.asset(root + "/songs", A), song),
            os.path.join(tmp, "line.png"),
            song_from=ss.get("start", SONG_FROM), music_gain=ss.get("gain", MUSIC_GAIN),
            look=look, mark=mark, assets=A)

        if ok:
            try:
                if source_fingerprint(scene_path) != scene_sha256:
                    raise ValueError('The starting scene changed during rendering. Rebuild this video.')
            except (OSError, ValueError) as error:
                ok, err = False, str(error)

        recipe = " | ".join(["format: " + variant(fmt)["label"],
                             "scene: " + scene_file,
                             "speaking: " + speaking_key,
                             "tutorial: " + tutorial_file,
                             "song: %s from %.3fs at %s" % (
                                 song, ss.get("start", SONG_FROM),
                                 ("%s dB" % ss["db"]) if ss.get("db") else "-17 dB"),
                             "look: " + look, "mark: " + mark,
                             "scene %.2fs + speaking A %.2fs + tutorial %.2fs + speaking B %.2fs = %.2fs"
                             % tuple(note.get(k, 0) for k in ("scene_len", "speaking_a_len",
                                                             "tutorial_len", "speaking_b_len", "total_len")),
                             "wording: " + text.replace("\n", " / ")])
        # Recorded as the run goes, not only read at the start - two videos a cover cannot tell
        # apart inside ONE batch is exactly how `final_0147` and `final_0152` happened under the
        # old format. Only on SUCCESS: a failed build writes a FAIL row and costs nothing, so it
        # must not spend the pairing or the mark either.
        if ok:
            taken_marks.setdefault((scene, sig), set()).add(mark)
            combo = (scene, speaking_key, tutorial_file)
            combinations[combo] = combinations.get(combo, 0) + 1
            remaining[scene] -= 1
        M.record_result(M.blank_row(
            video_id="final_%04d" % idx, file=name if ok else "", source=scene,
            recipe=recipe, batch=batch, status="ok" if ok else "FAIL",
            post_status="queued" if ok else "", error=err or "",
            # `scene` is the file's key, extension stripped - what the day's spread weighs and
            # what `scene_uses` counts against the cap.
            format=fmt, scene=scene, source_sha256=scene_sha256, farm_rest="",
            hook_line=text.replace("\n", " / "), wording_id=hid,
            song=song, look=look, frame_mark=mark,
            tutorial=tutorial_file, tutorial_library=TL.library_for("farm", A) if fmt == "farm" else "", speaking=speaking_key, pan="", overlay="",
            money="", logo_pair="", caption=""), out)

        if ok:
            made += 1
            delta[hid] = delta.get(hid, 0) + 1
            hook[ucol] = BS.int_or(hook.get(ucol), 0) + 1
            # Spent only when a video actually came out. `used["scene"]` counted the ATTEMPT a
            # moment ago, which is right for spreading the rest of the batch - a scene that just
            # failed should not be tried again immediately - but a failure must not cost it one
            # of its allowance.
            scene_uses[scene] = BS.int_or(scene_uses.get(scene), 0) + 1
            print("  ok   final_%04d  %-22s %-22s %-16s %s"
                  % (idx, scene[:22], speaking_key[:22], song[:16],
                     text.replace("\n", " / ")[:30]))
        else:
            print("  FAIL final_%04d  %s" % (idx, err[:120]))

    # Successful ledger rows are the only allowance counters.
    print("\nmade %d of %d requested (batch %s) -> %s" % (made, a.make, batch, OUT))
    final_left = remaining_by_scene(scenes, speaking, tutorials,
                                    live_wordings(hooks_file, fmt), M.read_rows(), fmt, assets=A)
    still = sum(final_left.values())
    spent = [scene for scene, left in final_left.items() if not left]
    print("  %d video%s left across the %d starting scene%s%s"
          % (still, "" if still == 1 else "s", len(scenes), "" if len(scenes) == 1 else "s",
             ("; finished: " + ", ".join(spent)) if spent else ""))


if __name__ == "__main__":
    main()
