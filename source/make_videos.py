#!/usr/bin/env python3
"""
make_videos.py - builds the videos.

THREE formats, all measured off reference reels rather than guessed at. All three are a
silent hook clip of yours, then a hard cut to a tutorial exactly on the song's drop. What
differs is only what is drawn over the hook:

  line     (the original) an opening line of text, then the money card assembling piece by
           piece over the last five beats. Needs a hook of at least 4.2s for the build-up.

  card     the whole money card from the FIRST FRAME, and no opening line at all. Nothing
           appears, nothing moves. Works with a hook of any length. Uses no hook line, so it
           does not spend the pool.

  compare  two fixed lines from the first frame - the bad option with a cross, the good one
           with a tick - and no money card at any point. Lines come from compare_lines.csv.

The two static formats were measured off four reference reels: same song, same drop landing
on the cut within one frame, same font at the same size. The only real differences are that
the overlay is up from frame one and the block sits a little higher. See render_hook.swift.

Everything is timed off ONE anchor: the drop in the song, at 20.644s. The song is always
the same song, so the beat is not something we have to find at build time - it is a known
number, 94.0 BPM, one beat every 0.6385s. We slide where the song STARTS so its drop lands
on the cut, then count backwards from the drop in whole beats to place every caption:

  the line      from 0 until 5 beats before the cut
  Shorts        from 5 beats before the cut, on the LEFT
  + OpenArt     from 3 beats before, to the right of it
  = $XXX/day    from 1 beat before
  the cut       on the drop

The two swapped both their order and their sides on 7 Sep 2026, at Steven's ask: the picture
that arrives first is the leftmost one, so the build-up assembles the way the frame is read.
The "+" follows whichever arrives second, or it would hang in an empty gap for two beats.
See `beat_grid` / `plus_with`, and the slot maths in `render_hook.swift`.

That is why hook clips can be any length. A longer clip just means the song starts earlier
and the line is on screen longer; the build-up is always the same five beats.

  python3 make_videos.py --make 6
  python3 make_videos.py --make 3 --assets /some/test/assets --out /some/test/out

SILVER GOOSE PORT, 15 Nov 2026. This is Golden Goose's builder as of commit 3aec2164, with
the parts that belong to Golden Goose's accounts, campaigns, footage locks and tutorial
caption system left out. Every tutorial is treated as already carrying burned-in captions:
it is fitted inside the frame rather than cropped (`PRESERVE_TUTORIAL_PICTURE`), and the
zoom and shift still cover the whole video, as Golden Goose does for such tutorials.
"""
import argparse, json, os, random, shutil, time

import csvfile
from builder_support import int_or, wrap
import builder_variation as BV
import wording_allowances as WA
import video_encode as VE
import encode as E
from render_support import ensure_font, ensure_renderer, run, die

# HOW MANY VIDEOS A SCENE IS WORTH, and the sentence that says so. It is a setting on the
# panel's Settings tab since 6 Sep 2026 rather than a constant here - see formula.py.
import formula as FM

import catalog
import manifest as M

import paths
import tutorial_libraries as TL

# OpenArt's settings live in one profile shared with the farm. It delegates filter building
# and frame-rate safety to repurpose.py, while keeping Pump's existing settings separate.
import poolpick as PP
import openart_repurpose as RP
# The four changes every video carries, and their ranges - see micro_repurpose.py.
import micro_repurpose as MR

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = paths.WORK

# Silver Goose tutorials arrive with their captions burned in, so the picture is fitted inside
# the 1080x1920 canvas and padded rather than cropped: cropping could cut off the lettering.
# Golden Goose does the same for a tutorial reviewed as already captioned. A 9:16 tutorial
# fills the frame either way; only another shape shows the difference, as bars.
PRESERVE_TUTORIAL_PICTURE = True

# The hook lines and the money amounts live in CSVs you can open and edit. hook_lines.csv is
# also where each line's use count is KEPT - the tool reads it, counts up, and writes it back
# for selection balance and history. Hook lines and comparison pairs never retire by usage.
LINES_CSV = paths.data("hook_lines.csv")
# The Instagram caption, chosen when the video is BUILT rather than when it is posted, so
# the day's batch can spread captions the same way it spreads everything else and Steven
# never has to think of one. Captions are spread without retirement.
CAPTIONS_CSV = paths.data("captions.csv")
MONEY_CSV = paths.data("money_cards.csv")

# The comparison format's line PAIRS - the bad option and the good one. Its own file, with
# its own use counts, because a pair is not interchangeable with a single hook line and
# mixing them in one file would make both harder to read and edit.
COMPARE_CSV = paths.data("compare_lines.csv")

# The three formats, and the order they are offered in.
FORMATS = ("line", "card", "compare")
FORMAT_NAMES = {"line": "line then card", "card": "card only", "compare": "tick and cross"}

# Which folder of scenes each format draws from, and which song it uses.
#
# "card" is a different animal from the other two and the study is why. Of the reference
# account's 451 reels, 113 cut at exactly 2.30s - his second most-used format - and they run a
# DIFFERENT track from the 4-6s ones. Building a card video out of a 5-second scene set to
# solitude is not the format he runs, so the tool does not pretend it is: card takes its own
# short scenes and its own song.
FORMAT_SOURCE = {"line": "hooks", "card": "hooks_short", "compare": "hooks"}
FORMAT_SONG   = {"line": "song.m4a", "card": "song_short.m4a", "compare": "song.m4a"}

# The point in each song the cut is anchored to, and both were MEASURED, not chosen.
#
#   song.m4a       solitude, drop at 20.644s - matched against Steven's own reels.
#   song_short.m4a Mist, hit at 2.468s - the track the reference account runs under the
#                  card-only format. Confirmed by matching the audio of one of his 2s reels
#                  against the file: 0.989 correlation, so it is definitely this song. Mist
#                  goes silent from 2.278s and slams back at 2.468s, and his cut lands in that
#                  gap so the tutorial starts as the music returns - the same trick solitude's
#                  drop plays, just three seconds in instead of twenty.
SONG_DROP = {"song.m4a": 20.644, "song_short.m4a": 2.468}

# Mist's hit is only 2.468s into the track, so there is that much run-up and no more: a scene
# longer than this cannot have the song start before zero. That is not a limitation to work
# around, it IS the format - his cut at 2.13s sits just inside it.
SHORT_MAX = SONG_DROP["song_short.m4a"]

# How often the money figure is one of the proven amounts from money_cards.csv, rather than a
# small variation on one. Set to 1.0 to only ever use the proven amounts.
MONEY_FROM_CSV = 0.8

# ---- the song, measured ------------------------------------------------------
BEAT = 0.6385           # 94.0 BPM
# solitude.m4a has SEVERAL drops. This is the one Steven actually uses, and it was not
# chosen by ear or by looking for the loudest jump - an earlier guess picked the drop at
# 123.081s and the run-up into it was the wrong part of the song. It was found by matching
# the audio of his own reels against the track: both land on the reel starting ~15.1s in,
# which puts their cut here. If this ever needs re-checking, match his audio again rather
# than hunting for a drop.
DROP_IN_SONG = 20.644
BUILD_BEATS = 5         # the money card starts assembling 5 beats before the cut
MIN_LINE_TIME = 1.0     # a line shorter than this on screen cannot be read
FPS = 30                # everything is rendered at this, so the cut must land on a whole frame

# The static formats have no build-up to fit, so the 4.2s floor the "line" format needs does
# not apply to them - it exists only because five beats of assembling plus a readable second
# adds up to 4.2s. They still need long enough to READ, and the shortest of the reference
# reels was 2.13s, so this is a floor with room under the measured one rather than a guess.
MIN_STATIC_HOOK = 1.5

# ---- the money figure --------------------------------------------------------
MONEY_MIN, MONEY_MAX = 420, 540

# ---- how many videos one hook clip is allowed to make ------------------------
# Each gets a different line, a different colour grade, and a different tutorial once there are
# enough. Steven raised this from 2 to 4 on 1 Sep 2026, after the same raise on the humbled
# format: *"I want you to make it so that we get four videos per scene per format."*
#
# WHAT PAYS FOR VIDEOS THREE AND FOUR, because a number like this is only ever as good as the
# difference underneath it. Alex's rule, 26 Aug 2026, is the one that decides it: *"pixel drift
# and the volume nudge are not that guarantee - they change the pixels while leaving a video a
# viewer would call the same"*. So JITTER and the saturation nudge below do not count, and never
# did. What counts, per video off one scene:
#
#   the hook line     ALREADY GUARANTEED, and it is the biggest thing on the screen. No scene
#                     may ever carry the same wording twice - `pick_unused_line` checks it
#                     against the whole ledger, not just the batch, and the run refuses rather
#                     than repeating. 7 live lines and 6 live comparison pairs against 4 slots.
#   the colour grade  NEW, and it is the one that arrived with this raise - the gentle tints
#                     in `openart_repurpose`. On the whole video since 26 Oct 2026 (see
#                     `micro_repurpose`); the drawn text and cards are never tinted.
#   the tutorial      Two of them, alternated, so a scene's four go A B A B.
#   the money figure  and the logo pair, both spread least-used-first.
#
# So the four differ in their headline text, their grade, their tutorial and their card - which
# is everything a viewer of a 20-second reel actually looks at. Take the grade away and this
# number should go back to 2, exactly as `make_humbled.REPEAT_PER_CLIP` says of its own.
#
# THE CARD FORMAT IS THE WEAK ONE and it is worth knowing: it draws no hook line at all, so its
# four differ only by grade, tutorial, money and logos. `seen_recipes` in `main` is what stops
# that becoming four of the same video; it is a real guard and not a formality.
#
# SINCE 6 SEP 2026 IT IS A SETTING, NOT A CONSTANT - `formula.num("per_clip")`, a box on the
# panel's Settings tab. The 4 above is still the number and still the argument for it; what
# changed is that Steven can move it without anyone editing Python, which is the whole point
# of that tab. The default lives in `formula.py` and only there, so the box and the builder
# cannot disagree about what "unset" means.
def per_clip_n():
    """How many videos one short scene is worth - see the argument above."""
    return FM.num("per_clip")


# ...EXCEPT THE LINE FORMAT, where a hook scene is worth THREE VIDEOS PER TUTORIAL, since
# 6 Sep 2026. Steven: *"for the line, then card format I want each hook scene to make as many
# tutorials are there are times 3."* And it is PER (SCENE, TUTORIAL), not per scene: *"I JUST
# added that tutorial and I am 100% sure that no hook scene has ever used that tutorial, so
# with 11 hook scenes currently at my disposal I should be able to make 33 videos now."* A
# scene that made four videos with the old tutorials has made NONE with a new one, so a new
# tutorial is worth three fresh videos on every scene whatever the scene has spent before. The
# first version counted per scene and told him 6; that is the reading this comment exists to
# stop coming back. Card and compare stay at the flat per-scene number.
#
# `per_clip(fmt)` is what a scene is worth IN ALL today; `left_for(name, fmt, ...)` is what it
# has LEFT, and for the line format that is counted on the ledger's `tutorial` column against
# the tutorials in the folder now - a tutorial that has left the folder counts for nothing, and
# an old row with no tutorial written on it consumes nobody's allowance. ONE place for each,
# read by the builder, the used-up store and the panel; a second copy of either is a copy that
# is corrected once (see `dashboard._per_clip`).
#
# TICK AND CROSS FOLLOWS THE SAME RULE, later the same day: *"it says 12 left but it should say
# 96 BECAUSE THE TUTORIAL IS NEW... make it so that the tick and cross format can make as many
# videos as there are hook scenes times tutorials times 3 like the line then card format."*
# Card only stays at the flat number: it has no tutorial on screen to be new. The spend is counted
# PER FORMAT as well as per (scene, tutorial), so a line video does not eat a compare slot.
#
# A SETTING TOO since 6 Sep 2026, and the SAME setting for both formats - one box on Settings,
# which says so. Two boxes secretly writing one row would be worse than one box that is honest
# about what it moves.
def line_per_tutorial():
    """How many videos one hook scene is worth per tutorial, on line and tick-and-cross."""
    return FM.num("line_per_tutorial")


PER_TUTORIAL_FORMATS = ("line", "compare")


def tutorial_names(assets=None, fmt="line"):
    """The tutorials in the folder now, by file name - what the line format's allowance is
    counted against. Read fresh: the folder is his to add to."""
    names = [os.path.basename(p) for p in clips_in(TL.folder_for(fmt, assets), TL.EXTENSIONS)]
    return TL.eligible_names(fmt, names, assets=assets)


def compare_ids():
    """The ids in compare_lines.csv now, as strings.

    READ AT CALL TIME, not off `COMPARE_CSV`. That constant is bound at import, which is right
    for this file - a build is one campaign in one process - and wrong for the PANEL, which
    imports this module once and serves both campaigns. `paths.data` answers for whichever
    campaign is active at the moment of the call, so the allowance the Assets tab draws is the
    allowance the build would use.
    """
    try:
        rows, _ = csvfile.read(paths.data("compare_lines.csv"))
    except Exception:
        return []
    return [str(r.get("id", "")).strip() for r in rows if str(r.get("id", "")).strip()]


def pools_now(assets=None):
    """Everything the per-tutorial allowance is counted against, read fresh, ONCE.

    `left_for` is asked per scene per format - twenty-odd scenes on the Assets tab, and again
    on the Builder tab - and every call needs the same ingredient inventories. Passing this
    in avoids repeated folder reads per scene. It is
    optional everywhere: leave it out and each call reads for itself, which is what the CLI
    does and what keeps a caller that forgets it correct rather than stale.
    """
    A = assets or paths.ASSETS
    return {"tutorials": tutorial_names(A),
            "tutorials_by_format": {f: tutorial_names(A, f) for f in FORMATS},
            "library_by_format": {f: TL.library_for(f, A) for f in FORMATS},
            "logos": [p["key"] for p in logo_pairs(A)[0]],
            "compare": compare_ids()}


def usable_tutorials(fmt, assets=None, pools=None):
    """Tutorials assigned to the selected content type, without ingredient restrictions."""
    p = pools or pools_now(assets)
    return list(p.get("tutorials_by_format", {}).get(fmt, p["tutorials"]))


def per_clip(fmt, assets=None, pools=None):
    """How many videos one hook scene is worth IN ALL in `fmt`, today.

    Count only tutorials eligible for this format and content type.
    Logo and wording choices do not narrow the tutorial pool.
    """
    if fmt in PER_TUTORIAL_FORMATS:
        return line_per_tutorial() * len(usable_tutorials(fmt, assets, pools))
    return per_clip_n() if usable_tutorials(fmt, assets, pools) else 0


def tutorial_uses(rows=None, assets=None):
    """{(format, scene key, tutorial file): how many successful builds} off the `ok` rows - the
    per-tutorial formats' own spend, per pair and per format. Counted off the build history,
    never kept separately; deleting an output does not refund it (see manifest.py)."""
    out = {}
    libraries = {fmt: TL.library_for(fmt, assets) for fmt in PER_TUTORIAL_FORMATS}
    for r in (M.read_rows() if rows is None else rows):
        fmt = (r.get("format") or "").strip()
        if r.get("status") != "ok" or fmt not in PER_TUTORIAL_FORMATS:
            continue
        if TL.row_library(r) != libraries[fmt]:
            continue
        key = M.scene_key((r.get("scene") or "").strip())
        tut = (r.get("tutorial") or "").strip()
        if key and tut:
            out[(fmt, key, tut)] = out.get((fmt, key, tut), 0) + 1
    return out


def left_for(name, fmt, uses=None, tut_uses=None, assets=None, pools=None):
    """How many videos this scene has LEFT in `fmt`. Line and compare: three per tutorial it
    may be built with, less what this scene has made with that tutorial in this format. Card:
    Its per-scene allowance less what it has made.

    THE TUTORIALS COUNTED ARE `usable_tutorials`, not the folder listing - so this and
    `per_clip` above are counting the same set, which is what makes "in all minus left" the
    number of videos actually made (see `plan_slots`). Both must use the same eligible pool.
    """
    if fmt in PER_TUTORIAL_FORMATS:
        tu = tutorial_uses(assets=assets) if tut_uses is None else tut_uses
        key = M.scene_key(name)
        return sum(max(0, line_per_tutorial() - tu.get((fmt, key, t), 0))
                   for t in usable_tutorials(fmt, assets, pools))
    if not usable_tutorials(fmt, assets, pools):
        return 0
    u = M.scene_uses() if uses is None else uses
    return max(0, per_clip_n() - M.uses_of(u, name, fmt))


def comparison_text(row):
    return "%s ❌\n%s ✅" % (row.get("bad", "").strip(), row.get("good", "").strip())


def supporting_blockers(assets, pools, money_rows, emoji=None):
    """Required supporting assets, shared by build admission and availability."""
    emoji = read_emoji(paths.asset('emoji.txt', assets)) if emoji is None else emoji
    common = ("No complete logo pair. Add a matching pair under Assets." if not pools['logos'] else
              "No money amounts. Add a money card under Assets." if not money_rows else
              "No emoji. Add an emoji under Assets." if not emoji else '')
    return {fmt: (common or ('' if os.path.isfile(paths.asset(song_for(fmt), assets)) else
                            'Missing the song for %s: %s.' % (FORMAT_NAMES[fmt], song_for(fmt))))
            for fmt in FORMATS}


def money_options(rows):
    """Every amount pick_money can render, including its existing small variations."""
    out = []
    for row in rows:
        amount = row.get('amount', '').strip()
        per = (row.get('per') or 'day').strip()
        out.append('%s/%s' % (amount, per))
        n = int_or(amount.lstrip('$'), 0)
        if n and MONEY_FROM_CSV < 1:
            out.extend('$%d/%s' % (max(50, n + delta), per)
                       for delta in range(-25, 26) if delta)
    return list(dict.fromkeys(out))


def build_plan(rows=None, *, assets=None, pools=None, line_rows=None, cmp_rows=None,
               money_rows=None, emoji=None):
    """The exact combination owner used by the Builder tab's counts and the real picks.

    left_for remains the theoretical footage allowance, including for archive/restore.
    This snapshot also checks visible-cover history, campaign wording and support assets.
    Nothing is written and every scoped path is resolved at call time.
    """
    from silent_build_plan import SilentBuildPlan
    import cover_match
    assets = assets or paths.ASSETS
    pools = pools if pools is not None else pools_now(assets)
    rows = M.read_rows() if rows is None else rows

    def live_wording(name):
        # Only rows John has left switched on; the use count never retires these two pools.
        path = paths.data(name)
        return WA.live(WA.read(path)[0], path=path)
    line_rows = live_wording('hook_lines.csv') if line_rows is None else line_rows
    cmp_rows = live_wording('compare_lines.csv') if cmp_rows is None else cmp_rows
    money_rows = csvfile.read(paths.data('money_cards.csv'))[0] if money_rows is None else money_rows
    libraries = pools.get('library_by_format') or {fmt: TL.library_for(fmt, assets) for fmt in FORMATS}
    tutorials = {fmt: list(pools.get('tutorials_by_format', {}).get(fmt, pools['tutorials']))
                 for fmt in FORMATS}
    logos, wordings = {}, {}
    for fmt in FORMATS:
        for tutorial in tutorials[fmt]:
            logos[fmt, tutorial] = list(pools['logos'])
            if fmt == 'line':
                wordings[fmt, tutorial] = [(row, cover_match.line_signature(wrap(row.get('hook_text', '')).replace('\n', ' / ')))
                                           for row in line_rows if row.get('hook_text', '').strip()]
            elif fmt == 'compare':
                wordings[fmt, tutorial] = [(row, cover_match.line_signature(comparison_text(row), '❌/✅'))
                                           for row in cmp_rows
                                           if row.get('bad', '').strip() and row.get('good', '').strip()]
    blockers = supporting_blockers(assets, pools, money_rows, emoji)
    for fmt in FORMATS:
        if not blockers[fmt] and not tutorials[fmt]:
            blockers[fmt] = 'No tutorials assigned to this content type. Assign one in Assets.'
        if fmt in ('line', 'compare') and not blockers[fmt] and not any(wordings.get((fmt, t)) for t in tutorials[fmt]):
            blockers[fmt] = ('No opening lines. Add one under Assets.' if fmt == 'line' else
                             'No tick-and-cross wording. Add one under Assets.')
    return SilentBuildPlan(rows=rows, tutorials=tutorials, logos=logos, wordings=wordings,
                           libraries=libraries, scene_key=M.scene_key, signature=cover_match.line_signature,
                           row_library=TL.row_library, per_tutorial=line_per_tutorial(), per_scene=per_clip_n(),
                           money=money_options(money_rows), looks=MR.LOOKS, blockers=blockers)

# ---- how far things drift between videos -------------------------------------
# A few pixels, different every video. Each block moves as ONE piece so the layout never
# changes - it just means no two videos are pixel-identical, which matters when the same
# tutorial and the same two logos go out hundreds of times.
JITTER = 3

# ---- how much the colour shifts between videos -------------------------------
# The hook and tutorial receive independent gentle saturation nudges. Reduced 8 Sep 2026
# from 2-5% to 0.5-1%: stacking the old nudge on the old rich look could reach +17.6%.
#
# It is a nudge AWAY from 1.0 in one direction or the other, never a plain random number
# around 1.0 - draws that land on 0.998 change nothing at all once the pixels are rounded
# back to whole numbers, which defeats the point on the videos that happen to draw them.
#
# **THIS IS NOT WHAT PAYS FOR A SECOND VIDEO OFF A SCENE, and it never was** - see the note
# beside `per_clip_n()`. It is invisible on purpose, `tests/test_pool.py` strips it back off the
# recipe before asking whether two videos are the same one, and the pair that started all of
# this (final_0040 / final_0051) differed by exactly this and nothing else. It stays because
# "no two files are bit-identical" is still worth having; it just is not an argument.
SAT_MIN, SAT_MAX = 0.005, 0.01

# ---- how many videos one hook clip makes IN EACH FORMAT ----------------------
# The per-scene allowance is per clip PER FORMAT, not per clip overall. A card-only video and a tick-and-cross
# video off the same footage share nothing you can see - no common text, no common structure -
# so they are not the same video twice over in the way two "line" videos with different lines
# would be. It does mean turning a format on gives every clip you already have more videos in
# it; the run says so plainly rather than quietly tripling the output.

def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path])
    try: return float(r.stdout.strip())
    except Exception: return 0.0


# A clip's frame rate. The third builder needed it on 6 Sep 2026, so all three read encode's.
clip_fps = E.clip_fps


def draw_hook_speed(hook, fmt, raw_len=None):
    """This hook clip's speed for one video, drawn by `micro_repurpose` (1-3% either way).

    TWO SEPARATE TESTS, and both are needed.

    **No frame may be held.** `micro_repurpose.floor_for_fps` is the whole of that rule and the
    measurement behind it: a clip may only be SLOWED while `speed >= FPS / src_fps`, so a 60fps
    scene may go either way and a 30fps one only faster. Speeding up costs nothing on any
    source - it takes a different set of frames rather than repeating one.

    **The clip must still be a legal length for the format afterwards**, which is the half that
    did not apply on the retired Humbled format and does here. Speed changes the hook's PLAYED length, and the
    hook's played length is the cut, the song's start and the whole beat grid:

      line     needs `hook_len - 5 beats` to leave room for the line, so speeding up too far
               makes a scene that used to build stop building.
      card     must stay under Mist's 2.468s run-up, so SLOWING is what breaks that one.
      both     `song_start` is `drop - hook_len` and may not go negative.

    Rather than let a build fail on a speed the draw chose, the illegal ones are simply not
    drawn. `hook_wrong_length` is asked, so there is one answer to "may this clip be this
    long" and this function does not hold a second copy of the three rules. Only a clip with
    no legal speed in range at all (a 30fps scene right at its format's length limit) keeps
    1.00x.
    """
    if raw_len is None:
        raw_len = duration(hook)
    if raw_len <= 0:
        return 1.0

    def legal(v):
        played = raw_len / v
        return (not hook_wrong_length(played, fmt)
                and drop_for(fmt) - round(played * FPS) / FPS >= 0)
    return MR.draw_speed("opening", floor=MR.floor_for_fps(clip_fps(hook), FPS), legal=legal)


def head_trim_frames(hook_len, fmt, song_shift):
    """How many frames to take off the front of the hook so the song starts later.

    The drop must land on the cut, and the song starts at (drop - cut), so the only way to
    start the song later without moving the drop is to start the scene later: every frame
    taken off the front moves the song's start 1/30s further in. Fewer frames are taken when
    the full amount would make the hook too short for its format."""
    frames = max(0, int(round(float(song_shift or 0) * FPS)))
    while frames and hook_wrong_length(round(hook_len * FPS - frames) / FPS, fmt):
        frames -= 1
    return frames


def clips_in(folder, exts=(".mp4", ".mov", ".m4v")):
    if not os.path.isdir(folder): return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(exts) and not f.startswith("."))


def usable_scenes(files):
    """The scenes in `files` to build with, in the same order, one per scene.

    Silver Goose has no accounts, so no footage is locked away (Golden Goose's footage locks
    are not part of it); the builder and the Builder tab's counts both ask this function.
    """
    files = list(files)
    # A .mov and .mp4 with the same scene key share every allowance and cover.
    # Offering both would count that one allowance twice before the first render.
    distinct = {}
    for path in files:
        distinct.setdefault(M.scene_key(os.path.basename(path)), path)
    return list(distinct.values())


def read_lines(path):
    try: raw = open(path, encoding="utf-8").read().splitlines()
    except Exception: return []
    return [l.strip() for l in raw if l.strip() and not l.strip().startswith("#")]


def read_emoji(path):
    """One per line: the emoji, a space, then how likely it is. e.g.  'X 50'"""
    out = []
    for l in read_lines(path):
        bits = l.split()
        if not bits: continue
        w = 1.0
        if len(bits) > 1:
            try: w = float(bits[-1])
            except Exception: w = 1.0
        out.append((bits[0], w))
    return out


LOGO_EXT = (".png", ".jpg", ".jpeg", ".webp")

# The two halves of a logo pair, by filename prefix. LEFT is Steven's own picture - the OpenArt
# logo, or the cut-out of a child; RIGHT is what it is being promoted FOR. A pair is one of each
# and is picked as a unit.
#
# LEFT / RIGHT are pool names; the renderer owns screen position.
# Since 9 Sep 2026 Claude is first and on the left again.
#
# LEFT HOLDS SEVERAL NAMES AND THEY ALL GO OUT ALONGSIDE EACH OTHER. `child` was added
# 28 Aug 2026 - Steven wants the cut-out of a child on MOST videos instead of the OpenArt
# logo, not on all of them, so the two are alternatives in rotation and neither replaces the
# other. That is the whole reason a pair is named after its left-hand FILE now (`child-1`,
# `openart-1`) rather than after its number alone: `child-1.png` and `openart-1.png` are two
# different pairs, both real, and both go with `shorts-1.png`. How often each is seen is
# simply how many of each he keeps in the folder - there is no ratio setting anywhere.
#
# Adding a fourth picture later is this line and nothing else. When OpenArt replaced Claude
# (27 Aug 2026) this prefix turned out to be hardcoded in THREE separate places - here, again
# in the panel's old `logo_key`, and a third time as a regex in the page's own JavaScript. A file
# named `openart-1.png` was therefore not a logo at all, and the only thing the tool would
# have said about it is "No complete logo pair", naming a file that was sitting right there.
LOGO_LEFT = ("child", "openart")

# RIGHT HOLDS SEVERAL NAMES TOO, since 7 Sep 2026. `airbnb` is Steven's second campaign brand,
# and he asked for it the same way `child` was asked for: *"make a new naming call called
# Airbnb"*. A slot may now hold more than one right-hand picture, and each one makes its own
# pair with each left-hand picture in that slot - see `group_logos`.
LOGO_RIGHT = ("shorts", "airbnb")

# THE RIGHT-HAND PICTURE A PAIR'S NAME DOES NOT MENTION. A pair is named after its left-hand
# file - `openart-1` - and that was every pair's whole name while `shorts` was the only thing
# on the right. Those names are in the ledger's `logo_pair` column on 158 videos and in
# historical recipes, so they must not change: a pair whose right-hand half is
# `shorts` is still just `openart-1`, and only the pictures that arrived later add their name
# to it (`openart-3+airbnb2`). Exactly the reason `LOGO_LEFT_WAS` exists - a name that is
# already written down somewhere is not free to be tidied.
LOGO_RIGHT_IMPLIED = "shorts"

# OLD SPELLINGS of a left-hand picture that has since been renamed, and what it is called now.
# A file under an old name still pairs and still builds - a half-finished rename is a normal
# state that lasts about a minute - but it lands on the SAME pair as its current name, the
# current name wins, and the loser is named on the Assets tab instead of quietly going out.
# `claude` -> `openart` was the swap of 27 Aug 2026.
#
# THIS IS NOT WHERE A NEW PICTURE GOES. A name in here is the same picture under a stale name
# and is expected to disappear; a picture meant to keep going out beside the others belongs in
# LOGO_LEFT above. Put `child` in here and `child-1.png` claims the pair `openart-1`, so one
# of the two pictures never reaches a video and every child video is FILED as an OpenArt one.
LOGO_LEFT_WAS = {"claude": "openart"}

# HOW BIG each left-hand picture is drawn, as a multiple of the standard card height. A name
# not in here is 1.0 - the height the OpenArt and Shorts cards were measured at.
#
# It is here rather than in the renderer because it is a fact about a PICTURE, and this is the
# one place that already says what the pictures are called. OpenArt and Shorts are white boxes
# of roughly the same shape, so one height suited both; the child is a cut-out on a transparent
# background, nearly square, with no box around it, and at the card's height it reads as much
# smaller than the Shorts logo next to it. Steven asked for it bigger, 28 Aug 2026.
#
# It grows UPWARD - the bottom edge does not move, so both pictures stand on the same line.
# 1.6 puts the top of the child at y=144 of 1920; much past 2.0 and it starts running into
# Instagram's own furniture at the top of the screen.
LOGO_LEFT_SIZE = {"child": 1.6}

# Everything accepted as a left-hand name, current and stale.
LOGO_LEFT_ALL = LOGO_LEFT + tuple(sorted(LOGO_LEFT_WAS))
# Longest first, so a prefix that starts with another prefix cannot be matched by the shorter
# one. None of them do today; the day one does, the failure would be a key silently gaining a
# few extra characters and every pair quietly ceasing to match.
LOGO_PREFIXES = tuple(sorted(LOGO_LEFT_ALL + LOGO_RIGHT, key=len, reverse=True))


def logo_upload_names():
    """Current pictures offered by Assets, without renaming historical ledger keys."""
    return LOGO_LEFT, LOGO_RIGHT


def logo_pair_label(pair):
    left = pair.get("left") or pair.get("claude", {}).get("name", "")
    if logo_prefix(os.path.basename(left)) == "claude":
        return "Claude + Shorts (%s)" % logo_key(os.path.basename(left))
    return pair["key"]


def logo_side(name):
    """Which half of a pair a file is - "left", "right", or None if it is not a logo."""
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    if stem.startswith(LOGO_LEFT_ALL): return "left"
    if stem.startswith(LOGO_RIGHT): return "right"
    return None


def logo_prefix(name):
    """The name a logo file starts with - "child", "openart", "shorts" - or None."""
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    return next((p for p in LOGO_PREFIXES if stem.startswith(p)), None)


def _split_variant(rest):
    """`rest` is what is left of a logo's name after its prefix. Hands back (variant, the rest).

    WHICH OF SEVERAL PICTURES OF THE SAME NAME THIS IS, written as a number stuck straight onto
    the name: `airbnb-3`, `airbnb2-3` and `airbnb3-3` are three different Airbnb pictures, all
    in slot 3. That is how Steven named the three he sent on 7 Sep 2026, and it reads the way
    he meant it.

    THE SEPARATOR IS WHAT TELLS THE TWO NUMBERS APART - the variant is JOINED to the name, the
    slot follows a dash. Without that rule `airbnb2-3` is unreadable: it could as easily be
    Airbnb in slot "2-3". So digits count as a variant only when the slot follows them.
    """
    i = 0
    while i < len(rest) and rest[i].isdigit():
        i += 1
    if i and (i == len(rest) or rest[i] in "-_ ."):
        return rest[:i], rest[i:]
    return "", rest


def logo_key(name):
    """The SLOT a logo file is in - what a left file and a right file MATCH on.

    `child-1.png`, `openart-1.png` and `shorts-1.png` are all "1". `airbnb2-3.webp` is "3" -
    the 2 says which Airbnb picture it is, not which slot. `openart-blue.png` and
    `shorts-blue.png` are both "blue". Anything after the prefix and its variant, minus
    separators and extension.

    This is the MATCHING key, not the pair's name - see `pair_key` below for that. It is
    deliberately the SUFFIX and not the whole stem, so one `shorts-1.png` serves every
    left-hand picture numbered 1 and Steven does not have to keep a copy of the same Shorts
    logo per picture. The variant works the other way round and for the same reason: one
    `openart-3.jpeg` serves all three Airbnb pictures in slot 3, so he does not have to keep
    three copies of the OpenArt logo either.
    """
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    for pre in LOGO_PREFIXES:
        if stem.startswith(pre):
            return _split_variant(stem[len(pre):])[1].lstrip("-_ .") or "1"
    return stem


def logo_picture(name):
    """WHICH PICTURE this file is, whatever slot it is in - "openart", "shorts", "airbnb2".

    The name plus the number stuck to it, with a stale spelling brought up to date the way
    `logo_pair_key` does it. None if the file is not a logo at all.
    """
    pre = logo_prefix(name)
    if pre is None:
        return None
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    return LOGO_LEFT_WAS.get(pre, pre) + _split_variant(stem[len(pre):])[0]


def logo_pair_key(name):
    """Which PAIR a LEFT-hand file makes: its own name, with any stale spelling brought up to
    date. `child-1.png` -> "child-1"; `openart-1.png` and a leftover `claude-1.png` both ->
    "openart-1", which is exactly what makes one of them shadow the other.

    This is what goes in the ledger's `logo_pair` column. It used to be the number on its own,
    from back when there was only ever one left-hand picture and the number therefore said
    everything. The 31 rows written before 28 Aug 2026 were brought up to date in place, so a
    breakdown does not show one logo as two rows - see `docs/formats.md`.
    """
    pre = logo_prefix(name)
    if pre is None: return logo_key(name)
    return "%s-%s" % (logo_picture(name), logo_key(name))


def pair_key(left, right):
    """What the PAIR of these two files is called - the ledger's `logo_pair`, the name on the
    Assets tab and historical recipe usage.

    The left-hand file names it, as it always has. The right-hand PICTURE is added when it is
    not the one every existing pair carries - see `LOGO_RIGHT_IMPLIED`. So the four pairs
    Steven has been building since August keep the names his ledger already holds -
    `child-1`, `openart-1`, `child-2`, `openart-2` - and the three that arrived with Airbnb say
    which of the three they are: `openart-3+airbnb`, `openart-3+airbnb2`, `openart-3+airbnb3`.

    ADDING A PICTURE MUST NEVER RENAME A PAIR THAT ALREADY EXISTS. That is why the rule is
    "this one picture is implied" and not "the right-hand half is named only when the slot
    holds more than one": under the second rule, dropping a second Shorts logo into slot 1
    would silently turn `openart-1` into two pairs called something else, and every tie and
    every row of history pointing at `openart-1` would quietly stop matching.
    """
    pic = logo_picture(right)
    if pic is None or pic == LOGO_RIGHT_IMPLIED:
        return logo_pair_key(left)
    return "%s+%s" % (logo_pair_key(left), pic)


def logo_scale(name):
    """How tall this left-hand picture is drawn, against the standard card height.

    A stale name is asked under its current one, so a leftover `claude-1.png` mid-rename is
    drawn exactly as `openart-1.png` would be rather than snapping back to the default.
    """
    pre = logo_prefix(name)
    if pre is None: return 1.0
    return LOGO_LEFT_SIZE.get(LOGO_LEFT_WAS.get(pre, pre), 1.0)


def logo_pair_scales(left, right):
    """The rounded Claude/Shorts pair requested 9 Sep is 30% larger on both sides."""
    names = tuple(os.path.basename(n).lower() for n in (left, right))
    if names == ("claude-2.png", "shorts-2.png"):
        return 1.3, 1.3
    return logo_scale(left), 1.0


def _logo_pref(name):
    """Which of two left-hand files claiming ONE pair wins. A current name beats a stale one;
    otherwise the one already held wins, so the answer cannot change between two runs."""
    return 1 if logo_prefix(name) in LOGO_LEFT_WAS else 0


def group_logos(names):
    """Which files make which pairs. THE one implementation.

    `logo_pairs()` below runs it over the folder and `dashboard.logo_pairs_state()` runs it
    over the rows it is already drawing, so the page and the builder cannot disagree about
    what goes with what. It used to be written out twice and the page held a third copy as a
    regex; renaming the left-hand logo meant finding all three, and only one of them was
    found.

    Takes plain filenames and hands back plain filenames - three lists:

        pairs     {"key": "child-1", "left": "child-1.png", "right": "shorts-1.png",
                   "match": "1"}          one per left file that has a right to go with it
        lonely    {"name": ..., "want": "shorts", "key": "1"}      a file doing nothing
        shadowed  {"name": "claude-1.png", "key": "openart-1", "beaten_by": "openart-1.png"}

    A RIGHT-HAND FILE SERVES EVERY LEFT FILE WITH ITS NUMBER. `shorts-1.png` goes with both
    `child-1.png` and `openart-1.png`. That is not the tool mixing and matching - Steven's
    rule, 24 Aug 2026, is that `child-1` must never appear beside `shorts-3`, and it still
    holds. The number is the set he designed; the left-hand name is which version of that set
    this is.

    AND IT NOW WORKS BOTH WAYS ROUND. Since 7 Sep 2026 a slot may hold several right-hand
    pictures too, and every left in that slot makes a pair with every right in it. Slot 3 is
    one `openart-3.jpeg` and three Airbnb pictures, and Steven asked for exactly that:
    *"the third column will create three new logo pairs (using the OpenArt logo and one of the
    three Airbnb logos)"*. Still nothing mixed across slots - the slot is the set he designed,
    and both halves of it are versions of that set.

    TWO FILES WANTING THE SAME THING IS NAMED, NEVER SILENTLY RESOLVED. On the left that is two
    left files claiming one pair, which happens when one of them is a stale name mid-rename. On
    the right it is two files that are the same PICTURE in the same SLOT - `airbnb2-3.webp` and
    `airbnb2-3.png` - which used to be resolved by a `setdefault` and no sentence at all. The
    fault both guard against is the one recorded in make_farm.py, where "a new name sorting
    before claude-3d.webp replaced it everywhere without a word".
    """
    left, right, shadowed = {}, {}, []
    for f in sorted(names):
        side = logo_side(f)
        if side == "left":
            k = logo_pair_key(f)
            if k in left:
                win, lose = ((f, left[k]) if _logo_pref(f) < _logo_pref(left[k])
                             else (left[k], f))
                left[k] = win
                shadowed.append({"name": lose, "key": k, "beaten_by": win})
            else:
                left[k] = f
        elif side == "right":
            # KEYED ON THE PICTURE AND THE SLOT, so three Airbnb pictures in slot 3 are three
            # entries and not one. Two files that are the same picture in the same slot are
            # the shadowing case, and are said out loud rather than one quietly winning.
            k = (logo_key(f), logo_picture(f))
            if k in right:
                shadowed.append({"name": f, "key": "%s-%s" % (k[1], k[0]),
                                 "beaten_by": right[k]})
            else:
                right[k] = f
    # The right-hand pictures of each slot, in a settled order - by picture name, so a pair's
    # place in the list does not move about between runs.
    by_slot = {}
    for (slot, _pic), f in sorted(right.items()):
        by_slot.setdefault(slot, []).append(f)
    pairs = [{"key": pair_key(left[k], rf), "left": left[k], "right": rf,
              "match": logo_key(left[k])}
             for k in sorted(left) for rf in by_slot.get(logo_key(left[k]), [])]
    used = set(logo_key(left[k]) for k in left)
    lonely = ([{"name": left[k], "want": LOGO_RIGHT[0], "key": logo_key(left[k])}
               for k in sorted(left) if logo_key(left[k]) not in by_slot] +
              [{"name": f, "want": LOGO_LEFT[0], "key": slot}
               for slot in sorted(by_slot) if slot not in used
               for f in by_slot[slot]])
    return pairs, lonely, shadowed


def logo_pairs(A):
    """The pairs in assets/logos/, any file with no partner, and any file being shadowed.

    A PAIR IS PICKED AS A UNIT, never mixed and matched. Steven's call, 24 Aug 2026: he adds
    logos as matching sets, so a video showing `child-1` next to `shorts-3` is not a variant he
    ever wanted - it is the tool inventing a combination he did not design.

    The matching itself is `group_logos` above; this only turns names into paths.
    """
    d = paths.asset("logos", A)
    if not os.path.isdir(d): return [], [], []
    names = [f for f in os.listdir(d)
             if not f.startswith(".") and f.lower().endswith(LOGO_EXT)]
    grouped, lonely, shadowed = group_logos(names)
    P = lambda n: os.path.join(d, n)
    # "claude"/"shorts" are the names the renderer's spec calls these two slots by, and are
    # kept for it; "left"/"right" are the same two paths under names that do not go stale the
    # next time the picture changes. New code should use left/right.
    pairs = [{"key": p["key"], "claude": P(p["left"]), "shorts": P(p["right"]),
              "left": P(p["left"]), "right": P(p["right"])} for p in grouped]
    return pairs, [P(x["name"]) for x in lonely], shadowed


def check_assets(A, want_formats=None):
    """Everything the tool needs, checked up front, so it fails with a sentence you can act
    on instead of halfway through a batch."""
    problems = []
    # Two folders of scenes, because the card format is a different length of video with a
    # different song under it - see FORMAT_SOURCE.
    hooks = usable_scenes(clips_in(paths.asset("hooks", A)))
    shorts_scenes = usable_scenes(clips_in(paths.asset("hooks_short", A)))
    tuts = {f: [os.path.join(TL.folder_for(f, A), n) for n in tutorial_names(A, f)]
            for f in (want_formats or FORMATS)}
    if not hooks and not shorts_scenes:
        problems.append("Add opening scenes in Assets before building.")
    if not any(tuts.values()):
        problems.append("No tutorials assigned to the selected content type. Assign tutorials in Assets → Tutorial libraries.")

    pairs, lonely, shadowed = logo_pairs(A)
    song = paths.asset("song.m4a", A)
    emoji = read_emoji(paths.asset("emoji.txt", A))
    support = supporting_blockers(A, {'logos': [pair['key'] for pair in pairs]},
                                  csvfile.read(paths.data('money_cards.csv'))[0], emoji)
    problems.extend(dict.fromkeys(support[fmt] for fmt in (want_formats or FORMATS) if support[fmt]))

    if problems: die("Cannot build yet:\n\n  - " + "\n  - ".join(problems))
    if lonely:
        print("  logo(s) with no partner, so they are not used: %s"
              % ", ".join(os.path.basename(x) for x in lonely))
    for s in shadowed:
        # Said out loud every build, not once. A logo that is on disk and never on screen is
        # invisible by definition, so the log is the only place it can show.
        print("  %s and %s both want to be pair \"%s\" - using %s"
              % (s["beaten_by"], s["name"], s["key"], s["beaten_by"]))
    return {"hooks": hooks, "hooks_short": shorts_scenes}, tuts, song, emoji, pairs


def song_for(fmt):
    return FORMAT_SONG.get(fmt, "song.m4a")


def drop_for(fmt):
    return SONG_DROP.get(song_for(fmt), DROP_IN_SONG)


def beat_grid(hook_len, fmt="line"):
    """Everything counted backwards from the cut, in whole beats.

    The cut is snapped to a whole FRAME first. It has to be: the hook is re-timed to 30fps, so
    its real length becomes a whole number of frames, which is almost never exactly the clip's
    own duration. Timing the captions off the raw duration but cutting on the frame grid leaves
    them a frame out - and that frame is the first frame of the TUTORIAL, so the logos and the
    money card flash over it. Snap once here and everything downstream agrees.

    The song start is the same rule in all three formats, and that is not an assumption - the
    reference reels for both static formats matched the track at exactly (drop - cut), within
    one frame, the same as ours. Only what is DRAWN changes between formats.

    An overlay is switched off by giving it a window that can never be true, rather than by
    dropping it from the filter chain. Every format then runs the identical chain over the
    identical four images, so there is one code path to get right instead of three."""
    hook_len = round(hook_len * FPS) / FPS
    g = {"cut": hook_len, "song_start": drop_for(fmt) - hook_len}
    if fmt == "card":
        # The whole card from frame one; no line ever. lt(t, 0) is never true.
        g.update(line_out=0.0, claude_in=0.0, shorts_in=0.0, money_in=0.0)
    elif fmt == "compare":
        # The two lines from frame one to the cut; no card ever. gte(t,cut)*lt(t,cut) is
        # never true.
        g.update(line_out=hook_len, claude_in=hook_len, shorts_in=hook_len, money_in=hook_len)
    else:
        # Claude first and on the left again, 9 Sep 2026. The plus follows Shorts.
        g.update(line_out=hook_len - BUILD_BEATS * BEAT,
                 claude_in=hook_len - BUILD_BEATS * BEAT,
                 shorts_in=hook_len - 3 * BEAT,
                 money_in=hook_len - 1 * BEAT)
    return g


def plus_with(g):
    """Which logo the "+" is drawn with - "claude" or "shorts".

    IT NAMES A PICTURE, NOT A PLACE. It answered "left"/"right" for a few hours on 7 Sep 2026
    and then the two pictures swapped sides, which would have left the word meaning the
    opposite of what it says. Where each is DRAWN is `render_hook.swift`'s business and nothing
    here needs to know it.

    WITH WHICHEVER ARRIVES SECOND, and worked out from the two times rather than written down
    beside them, so that swapping the order can never leave the "+" behind. A "+" that came in
    with the FIRST logo would hang in the middle of the frame with a gap beside it for two
    beats, which reads as a picture that failed to load.

    TOGETHER IS NOT SECOND. The card format brings both in on frame one, and there the "+" stays
    where it has always been - with the right-hand picture - because the two images are
    composited into the same frame and the answer only has to be the one that does not change
    what that format already looks like.
    """
    return "claude" if g["claude_in"] > g["shorts_in"] else "shorts"


def hook_wrong_length(hook_len, fmt):
    """The reason a clip cannot be used, in a sentence, or None if it can."""
    if fmt == "line":
        if hook_len - BUILD_BEATS * BEAT < MIN_LINE_TIME:
            return ("scene is only %.1fs - the build-up needs %.1fs, leaving under a second "
                    "for the line. Use a scene of at least %.1fs, or build it as one of the "
                    "static formats, which have no build-up."
                    % (hook_len, BUILD_BEATS * BEAT, BUILD_BEATS * BEAT + MIN_LINE_TIME))
    elif hook_len < MIN_STATIC_HOOK:
        return ("scene is only %.1fs - too short to read. Use one of at least %.1fs."
                % (hook_len, MIN_STATIC_HOOK))
    # Mist's hit is 2.468s in, so that is all the run-up there is. A longer scene would need
    # the song to start before it begins.
    if fmt == "card" and hook_len > SHORT_MAX + 0.001:
        return ("short scene is %.2fs, and the card format's song only has %.2fs of run-up "
                "before its hit. Trim it to %.2fs or under." % (hook_len, SHORT_MAX, SHORT_MAX))
    return None


def build_one(out_path, hook, tut, line, emoji, money, A, font, renderer, tmp,
               claude_logo, shorts_logo, fmt="line", look="plain", speed=1.0, mark="",
               tutorial_speed=1.0, song_shift=0.0):
    """One video. `speed` is the hook's, `tutorial_speed` the tutorial's, and `song_shift`
    (seconds, later only) starts the song later by starting the scene later; see
    `head_trim_frames`. Production draws all of them from `micro_repurpose`.

    The tutorial is used exactly as it is on disk, captions and all: Golden Goose's caption
    preparation and verification are not part of Silver Goose."""
    from storage_guard import require_space
    require_space(os.path.dirname(out_path))
    def drift():
        return [random.randint(-JITTER, JITTER), random.randint(-JITTER, JITTER)]

    # THE PLAYED LENGTH, not the file's. At 1.06x the scene is on screen for less time than it
    # lasts, and the cut, the song's start and every beat of the build-up are counted off this
    # number - so getting it from the file instead would put the drop a tenth of a second off
    # the cut, which is the one thing this format is measured on.
    raw_len = duration(hook)
    hook_len = raw_len / speed if speed else raw_len
    preserve_picture = PRESERVE_TUTORIAL_PICTURE
    # The tutorial's own small speed change, measured against the file actually rendered.
    if tutorial_speed != 1:
        tutorial_speed = MR.fit_speed(tutorial_speed, MR.floor_for_fps(clip_fps(tut), FPS))
    tut_len = duration(tut) / tutorial_speed
    if hook_len <= 0 or tut_len <= 0:
        return False, "", "", "could not read one of the clips"

    why = hook_wrong_length(hook_len, fmt)
    if why:
        return False, os.path.basename(hook), "", why
    # THE SONG'S START, moved later by starting the scene a few frames in. See `head_trim_frames`.
    head = head_trim_frames(hook_len, fmt, song_shift)
    hook_len -= head / FPS

    g = beat_grid(hook_len, fmt)
    if g["song_start"] < 0:
        return False, os.path.basename(hook), "", "hook clip is longer than the song's run-up"

    # Draw the captions on macOS - ffmpeg cannot do text or emoji here.
    claude_scale, shorts_scale = logo_pair_scales(claude_logo, shorts_logo)
    spec = {"out_dir": tmp, "line": line.replace("\\n", "\n"),
            "money": "= %s %s" % (money, "\U0001F92F"),
            "font": font, "format": fmt,
            "claude_logo": claude_logo,
            "claude_logo_scale": claude_scale,
            "shorts_logo_scale": shorts_scale,
            "shorts_logo": shorts_logo,
            "plus_with": plus_with(g),
            "jitter_line": drift(), "jitter_cards": drift(), "jitter_money": drift()}
    sp = os.path.join(tmp, "spec.json")
    json.dump(spec, open(sp, "w"), ensure_ascii=False)
    r = run([renderer, sp])
    if r.returncode != 0:
        return False, os.path.basename(hook), "", "caption renderer failed: " + r.stderr[:200]

    hook_len = g["cut"]                     # the frame-snapped length, not the raw one
    total = hook_len + tut_len
    def nudged_sat():
        return 1.0 + random.choice((-1, 1)) * random.uniform(SAT_MIN, SAT_MAX)

    hook_sat = nudged_sat()
    tut_sat = nudged_sat()

    def fit(sat, look=None, speed=1.0, preserve=False):
        """One clip, squared up to the canvas, graded, and re-timed if it is being re-timed.

        THE GRADE AND THE NUDGE SHARE ONE `eq`. The look's saturation is MULTIPLIED by the
        nudge rather than stacked in a second filter: two `eq` passes would round the pixels
        twice for a number that is the product either way.

        `setpts` BEFORE `fps`, so the retime happens on the source's own frames and the 30fps
        resample then picks from them - the order measured on the retired Humbled opening
        (docs/history/pump.md). Nothing invented, nothing dropped.

        THE OVERLAYS ARE NOT IN HERE and that is what makes the grade safe. The line, the money
        card and the two logos are drawn over the CONCATENATED video further down, so a hue
        shift moves the footage and leaves the white text and its black outline exactly where
        `render_hook.swift` put them. Grading the composed frame would tint them.
        """
        l_sat, l_gam, l_con, l_hue = RP.LOOKS.get(look or "plain", RP.LOOKS["plain"])
        retime = "setpts=PTS/%.4f," % speed if speed != 1.0 else ""
        hue = ",hue=h=%.1f" % l_hue if l_hue else ""
        # Select output frames before resizing; the discarded source frames need no scaling.
        resize = ("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
                  if preserve else "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
        return ("%sfps=%d,%s,setsar=1,"
                "eq=saturation=%.4f:gamma=%.4f:contrast=%.4f%s,format=yuv420p"
                % (retime, FPS, resize, l_sat * sat, l_gam, l_con, hue))

    # Every overlay ends with lt(t,cut) - LESS THAN, never between(). between() includes its
    # end, so the caption survives onto the first frame of the tutorial.
    mark_filter = RP.mark_vf(*RP.parse_mark(mark), w=1080, h=1920) if mark else 'null'
    tail = '[v4]%s[v5]' % mark_filter
    # The tutorial wears the same look as the hook, so the colour change covers the whole
    # video; the drawn overlays still go on after it and keep their own colours.
    fc = (
        "[0:v]%s,trim=start_frame=%d,setpts=PTS-STARTPTS,trim=end=%.5f,setpts=PTS-STARTPTS[h];"
        "[1:v]%s,setpts=PTS-STARTPTS[t];"
        "[h][t]concat=n=2:v=1:a=0[base];"
        "[base][2:v]overlay=0:0:enable='lt(t,%.4f)'[v1];"
        "[v1][3:v]overlay=0:0:enable='gte(t,%.4f)*lt(t,%.4f)'[v2];"
        "[v2][4:v]overlay=0:0:enable='gte(t,%.4f)*lt(t,%.4f)'[v3];"
        "[v3][5:v]overlay=0:0:enable='gte(t,%.4f)*lt(t,%.4f)'[v4];"
        # THE MARK, last, on the composed frame - text, logos and money card move with the
        # footage, which is the point: a 2-3% zoom and a few pixels of pan that no viewer sees
        # and that makes no two renders the same picture. Added 6 Sep 2026 (Steven: every
        # format carries the small changes). Never read back: these covers are matched on
        # their TEXT. `null` when there is none, so the graph always ends on [v5].
        "%s;"
        "[6:a]atrim=0:%.4f,asetpts=PTS-STARTPTS,afade=t=out:st=%.4f:d=0.12[a]"
        % (fit(hook_sat, look, speed), head, hook_len,
           fit(tut_sat, look, tutorial_speed, preserve=preserve_picture), g["line_out"],
           g["claude_in"], g["cut"], g["shorts_in"], g["cut"], g["money_in"], g["cut"],
           tail,
           total, max(total - 0.12, 0))
    )
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", hook, "-i", tut,
           "-i", os.path.join(tmp, "line.png"), "-i", os.path.join(tmp, "claude.png"),
           "-i", os.path.join(tmp, "plusshorts.png"), "-i", os.path.join(tmp, "money.png"),
           "-ss", "%.4f" % g["song_start"], "-i", paths.asset(song_for(fmt), A),
           "-filter_complex", fc, "-map", "[v5]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", "30",
           # SAID OUT LOUD NOW. This builder set no rate at all and inherited 44100 from
           # whatever the source happened to be. Whether or not that ever mattered, a
           # finished video's audio should not be decided by accident. See encode.AUDIO_RATE.
           ] + E.audio_args() + ["-movflags", "+faststart",
           "-t", "%.4f" % total, out_path]
    r = VE.run(cmd, runner=run, label=fmt)
    # Not merely "exists": the number's reservation is an empty file at this path.
    if r.returncode != 0 or not os.path.isfile(out_path) or not os.path.getsize(out_path):
        return False, os.path.basename(hook), "", ("ffmpeg failed: " + r.stderr[-300:]).strip()

    # The recipe is free text for Steven to read back later, so it names only the parts this
    # format actually has - a "card only" row claiming a hook line it never drew would be a
    # lie in the ledger.
    bits = ["%s + %s" % (os.path.basename(hook), os.path.basename(tut)),
            "format: %s" % FORMAT_NAMES.get(fmt, fmt),
            "cut %.2fs on the drop" % g["cut"],
            "%s from %.2fs%s" % (song_for(fmt), g["song_start"],
                                 " (scene from frame %d)" % head if head else "")]
    if fmt != "card":
        bits.append("line: %s" % line.replace("\n", " / "))
    if fmt == "line":
        bits.append("emoji: %s" % emoji)
    if fmt != "compare":
        bits += [money, "logos %s+%s" % (os.path.basename(claude_logo),
                                         os.path.basename(shorts_logo))]
    # THE GRADE AND THE SPEED GO BEFORE THE SATURATION, and the order is load-bearing:
    # `tests/test_pool.py` strips a trailing " | sat x/y" off the recipe before asking whether
    # two videos are really the same video, and it strips it off the END. Anything appended
    # after `sat` would leave that drift in the string, and then two videos that differ by
    # nothing but an invisible nudge would pass the test that exists to catch them.
    bits.append("look %s at %s, tutorial %s%s" % (look or "plain", RP.speed_key(speed),
                                                  RP.speed_key(tutorial_speed),
                                                  (" mark " + mark) if mark else ""))
    bits.append("sat %.3f/%.3f" % (hook_sat, tut_sat))
    return True, os.path.basename(hook), " | ".join(bits), ""


def apply_emoji(line, e):
    """The emoji goes INSIDE the closing quote - '"...get a real job [emoji]"' - because that
    is how the reference videos read. Write your lines in lines.txt however you want them to
    appear, quotes and all, and leave the emoji off; this puts it in the right place."""
    s = line.rstrip()
    if s.endswith('"'):
        return s[:-1].rstrip() + " " + e + '"'
    return s + " " + e


def pick_money(money_rows, life=None, batch=None, recent=None, avoid=()):
    """Mostly one of the proven amounts from money_cards.csv; occasionally a few dollars off
    one, so hundreds of videos are not all showing the same six numbers.

    WHICH proven amount is spread, and that arrived with four videos a scene. It used to be a plain
    `random.choice` over the six, which was fine at two videos a scene - the odds of a scene's
    pair sharing a figure were one in six. At four they are closer to three in four, and on the
    CARD format the money figure is the ONLY text on the screen. Measured on a real 8-video
    run before this changed: three of one scene's four `line` videos all read "$500/day".

    So: least-used in this run, then least-used ever, then not used lately - `poolpick.pick`,
    the same three counters as every other pool here - and `avoid` takes out the amounts this
    scene has already shown in this format.

    THE LIFETIME COUNT IS OFF THE UN-JITTERED FIGURES ONLY, and that is deliberate rather than
    sloppy. A row that came out as "$487/day" is a variation on $478 and matches no amount in
    the file; trying to attribute it back to its row would be guessing. It is one video in five
    and it under-counts rather than mis-counts, and the run counter and `avoid` are what
    actually keep a scene's four apart.
    """
    def rendered(r):
        return "%s/%s" % (r.get("amount", "").strip(),
                          (r.get("per", "day") or "day").strip())
    free = [r for r in money_rows if rendered(r) not in avoid] or list(money_rows)
    if life is None:
        row = random.choice(free)
    else:
        row = PP.pick(free, life, batch or {}, recent or [], rendered)
    amount = row.get("amount", "").strip()
    per = (row.get("per", "day") or "day").strip()
    if random.random() >= MONEY_FROM_CSV:
        n = int_or(amount.lstrip("$"), 0)
        if n:
            n = max(50, n + random.choice((-1, 1)) * random.randint(1, 25))
            amount = "$%d" % n
    return "%s/%s" % (amount, per)


def pick_emoji(emoji):
    total = sum(w for _e, w in emoji)
    x = random.uniform(0, total)
    for e, w in emoji:
        x -= w
        if x <= 0: return e
    return emoji[-1][0]


def clip_slots(clip_uses, name, fmt):
    """How many videos this clip has already made in THIS format.

    One line, because `manifest.scene_uses` hands back the counts already keyed and shaped.
    It used to also read a bare number as the "line" count, for a `clip_uses.json` written
    back when there was only one format; that file is retired and so is the branch.
    """
    return M.uses_of(clip_uses, name, fmt)


def bump_clip(clip_uses, name, fmt):
    """Spend one, for the rest of THIS run only.

    Nothing is saved: the ledger row appended for the video is what records it. This keeps
    the batch spreading correctly across itself without re-counting the ledger per video.
    """
    key = M.scene_key(name)
    v = clip_uses.setdefault(key, {})
    v[fmt] = int_or(v.get(fmt), 0) + 1


def pick_unused_line(ranked, make_text, scene, taken, sig):
    """The best line that has NOT already been used on this scene. (row, text) or (None, None).

    WHY A SCENE HAS TO BE CHECKED AND NOT JUST THE BATCH. At two a scene, every scene gets
    two slots in the same run, and there are only five comparison pairs. The old picker spread
    lines evenly across the BATCH - least-used-this-batch first - which is right as far as it
    goes and knows nothing about where each one is going. So round one and round two of
    `hook-scenes-06` both drew the same pair, and the run produced two videos off the same clip,
    the same tutorial, the same cut and the same words: final_0040 and final_0051, 25 Aug 2026.
    The same video, twice, differing only by a saturation tweak of 0.005 that nobody can see.

    Neither was ever posted, and Steven caught it himself on 26 Aug: "I'm pretty sure that
    Final 40 and Final 51 were an identical video... the last thing I want is to post an
    identical video to my Instagram."

    `ranked` is already in preference order - this only walks past the ones that would repeat.
    Returning (None, None) means every live line has been spent on this scene; the caller says
    so out loud rather than quietly making one anyway.
    """
    for cand in ranked:
        text = make_text(cand)
        if sig(scene, text) not in taken:
            return cand, text
    return None, None


def plan_slots(pools, clip_uses, want_formats, per_clip=None, left_of=None):
    """`per_clip` is a number for every format, or a function of the format - see `per_clip()`.
    Left out, it is whatever the Settings tab says a short scene is worth today. It must NOT be
    a default argument: a default is evaluated once, when this module is imported, and the
    panel imports it and then stays up for days - so a number he changed at lunchtime would go
    on being ignored until the panel was restarted.
    `left_of(scene, fmt)`, when given, says what each scene has LEFT and wins over `per_clip`:
    the line format's allowance is per tutorial, so a scene's total is what it has made plus
    what it has left, not a flat count - see `left_for`."""
    """Decide which scene makes which video, variety first.

    The rule Steven asked for: spread as wide as possible, and only repeat a scene when the
    number of videos asked for forces it. Two things fall out of that:

      * Round by round, not scene by scene. Every scene gets its FIRST video before any scene
        gets its second. Ask for ten off ten scenes and you get ten different scenes, not five
        used twice.
      * Least-used scenes first WITHIN each round. This is the part that matters when new
        footage arrives: with ten spent scenes and five fresh ones, the next five videos come
        off the five fresh ones, because they are the only ones in round 0.
      * ACROSS THE FORMATS AS WELL, since 6 Sep 2026. The rounds are worked out one format at a
        time - a format's allowance is its own - but the deal that interleaves them is not, and
        that was the fault. See below.

    `pools` maps a format to its list of scenes. Returns a flat list of (scene, format), in the
    order they should be built - the caller just takes as many as it wants off the front.
    """
    # Resolved here rather than in the signature - see the docstring.
    if per_clip is None:
        per_clip = per_clip_n()
    by_fmt = {}
    for fmt in want_formats:
        pool = pools.get(fmt) or []
        rounds = []
        # HOW MANY A SCENE HAS MADE **OF WHAT IT MAY MAKE NOW** is what the rounds count, not
        # how many it has ever made. Those were the same number while every format was a flat
        # count per scene. The line format's allowance is per tutorial since 6 Sep 2026, and
        # the first batch under it went 3-3-3-3-2-2-2-1-1-1-1-1-1 over 13 of 24 scenes: the
        # rounds were still counting lifetime uses, so a scene that had made three videos with
        # tutorials long gone from the folder was not "due" until round three, and the scenes
        # with no history took three each first. Steven: *"it should have made exactly one
        # video for each starting scene."* So with `left_of` a scene's count is `in all - left`
        # (three tutorials' worth less what it has left), which is zero for every scene the
        # moment a new tutorial arrives - and the flat formats read exactly as before, because
        # for them in-all minus left IS the use count.
        if left_of is not None:
            in_all = per_clip(fmt) if callable(per_clip) else per_clip
            left = {h: left_of(h, fmt) for h in pool}
            made = {h: max(0, in_all - left[h]) for h in pool}
            n_rounds = max((made[h] + left[h] for h in pool), default=0)
        else:
            left = None
            made = {h: clip_slots(clip_uses, os.path.basename(h), fmt) for h in pool}
            n_rounds = per_clip(fmt) if callable(per_clip) else per_clip
        for r in range(n_rounds):
            # Everything that has made r or fewer of its allowance is due its (r+1)th video -
            # and, with `left_of`, only while it still has one left.
            due = [h for h in pool if made[h] <= r and (left is None or r < made[h] + left[h])]
            # Least-used first, so fresh footage is always reached for before worn footage.
            due.sort(key=lambda h: made[h])
            # KEPT AS ROUNDS, not flattened. The deal below is allowed to reorder WITHIN a
            # round and must never reach across one: a scene taking its second video before
            # another has had its first is the exact thing the rounds are here to stop.
            if due:
                rounds.append(due)
        by_fmt[fmt] = rounds

    # Deal the formats out round-robin so asking for four across two formats gives two of each
    # rather than four of whichever came first.
    #
    # AND NO TWO OF THOSE FOUR OFF ONE SCENE WHILE OTHER SCENES ARE GOING SPARE. Steven,
    # 6 Sep 2026, on batch 0906-2130: two `line` and two `compare`, and between them only two
    # scenes - final_0382/0383 both scene-15, final_0384/0385 both scene-19. *"instead of those
    # four videos using four unique scenes, they only use two scenes."*
    #
    # WHY IT HAPPENED. `line` and `compare` draw from the SAME folder (`FORMAT_SOURCE`), so
    # their round 0 is the same list of scenes in very nearly the same order - both formats had
    # scene-15 at the front. Each format's rounds were right on their own; the deal then took
    # the front of each in turn and handed the same scene to both. Neither format could see
    # what the other had taken, because nothing was keeping count across them.
    #
    # SO ONE COUNT, SHARED. `taken` is how many videos this run has already planned off each
    # scene, and each format picks the least-taken scene IN ITS CURRENT ROUND rather than
    # whatever happens to be at the front. Everything the rounds decide is untouched - the
    # round a scene is in, and which scenes are in it - this only chooses between scenes that
    # were already equally due.
    #
    # KEYED ON `manifest.scene_key`, so a short cut counts as its own footage: `hooks_short/`
    # holds the same scene under the same name, and a `card` video off scene-15's short cut is
    # a video of scene-15. Counting the two folders apart would put the `card` format straight
    # back into the fault the other two just came out of.
    #
    # AND THE COUNT STARTS FROM THE LEDGER, NOT FROM ZERO. Steven, the same evening, asking
    # the obvious next question: *"let's say I have 12 scenes, and I make three line then card
    # and three tick and cross, and then 30 minutes later I make another three and three. Is it
    # 100% sure that my 12 videos will all have 12 different scenes?"*
    #
    # With the count starting empty it was not, and it came out exactly as badly as the fault
    # above: batch one took scenes 1-6, and batch two took THE SAME SIX in the other order -
    # twelve videos off six scenes, with six scenes never touched. The reason is that a round
    # counts what a scene has made IN THAT FORMAT, which is right for the allowance and blind
    # to variety: scene 2 had a tick-and-cross video and no line video, so it was still round 0
    # for `line` and got picked ahead of scene 7, which had nothing at all.
    #
    # So the run starts knowing how many videos each scene has ALREADY made, across every
    # silent format, and a scene with none of them wins. That is the same "least-used footage
    # first" rule the rounds follow, asked of the footage rather than of one format's share of
    # it - and it makes a batch spread the same way whether it is built in one go or in four
    # goes half an hour apart, which is how he actually works.
    #
    # A SINGLE FORMAT READS EXACTLY AS BEFORE. Every scene in a round has made the same number
    # in that format, so the seeding only reorders scenes that differ in what the OTHER formats
    # spent on them - and with one format there is no other. The order test_spread.py pins is
    # untouched.
    taken = {M.scene_key(k): sum(int_or(v.get(f), 0) for f in FORMATS)
             for k, v in (clip_uses or {}).items() if isinstance(v, dict)}

    def took(h):
        return taken.get(M.scene_key(os.path.basename(h)), 0)

    slots = []
    while any(any(by_fmt.get(f) or []) for f in want_formats):
        for fmt in want_formats:
            rounds = by_fmt.get(fmt) or []
            # Rounds are emptied from the front, and an empty one is simply finished with.
            while rounds and not rounds[0]:
                rounds.pop(0)
            if not rounds:
                continue
            due = rounds[0]
            # `min` keeps the FIRST of equals, so a tie falls back on the round's own order -
            # least-used footage first, which is what the sort above put there.
            h = min(due, key=took)
            due.remove(h)
            taken[M.scene_key(os.path.basename(h))] = took(h) + 1
            slots.append((h, fmt))
    return slots


def seed_compare_csv(path):
    """Write compare_lines.csv the first time, holding ONLY the pairs actually seen on the
    reference account. Nothing here is invented: the rule for hook_lines.csv is that untested
    wordings do not go in the file without asking, and the same rule applies to these."""
    if os.path.exists(path): return
    rows = [
        {"id": "1", "bad": "Part time job", "good": "Claude + Kids YT", "tier": "observed",
         csvfile.USES_COL: "0", "retire_at": "",
         "note": "Seen on the reference account. No view count of its own - "
                 "the comparison format overall ran a 6.5% hit rate over 46 reels."},
        {"id": "2", "bad": "Part time job", "good": "Kids YouTube + AI", "tier": "observed",
         csvfile.USES_COL: "0", "retire_at": "",
         "note": "Seen on the reference account, same day as id 1."},
    ]
    csvfile.write(path, rows, ["id", "bad", "good", "tier", csvfile.USES_COL, "retire_at", "note"],
                  False)


def supporting_spreads(rows):
    """Shared support pools remember successful builds across runs.

    Silver Goose has one library and no accounts, so every successful row counts, and a
    scene's last tutorial in a format is whichever it was last built with."""
    rows = BV.successful_rows(rows, FORMATS)
    tutorials, logos, last_tut = [], [], {}
    for row in rows:
        fmt = (row.get('format') or '').strip()
        name = (row.get('tutorial') or '').strip()
        if name:
            identity = (TL.row_library(row), os.path.basename(name))
            tutorials.append(identity)
            last_tut[(M.scene_key(row.get('scene')), fmt)] = identity
        pair = (row.get('logo_pair') or '').strip()
        if pair and fmt != 'compare':
            logos.append(pair)
    return BV.LedgerSpread(tutorials), BV.LedgerSpread(logos), last_tut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", type=int, default=3, help="how many videos to build")
    ap.add_argument("--all", action="store_true",
                    help="build everything the hook clips you have can still make")
    ap.add_argument("--formats", default="line",
                    help="which formats to build: line, card, compare - comma separated")
    # How many of EACH, rather than a total shared out round-robin: --counts line=2,compare=5.
    # The panel asks for an exact number per format now, and "five of one and two of the other"
    # is not something a single total can say. It replaces --make and --formats when given.
    #
    # One run rather than one run per format keeps a mixed request's scene planning and
    # batch identity together. Supporting pools also restore successful history, so the
    # panel's one-process-per-format batches do not reset tutorial/logo variety each run.
    ap.add_argument("--counts", default="",
                    help="how many of each: line=2,compare=5. Overrides --make/--formats")
    ap.add_argument("--assets", default=paths.ASSETS)
    # A real build saves each video in its format's folder (`paths.output`); --out is only
    # used, as one folder, by a test run with --assets.
    ap.add_argument("--out", default=M.VIDEOS)
    a = ap.parse_args()

    # A cap per format, or {} when --counts was not given. A format asked for zero is simply
    # not asked for - it does not appear in want_formats and nothing is checked on its behalf.
    caps = {}
    if a.counts.strip():
        for part in a.counts.split(","):
            k, _, v = part.partition("=")
            k = k.strip().lower()
            if not k: continue
            if k not in FORMATS:
                die("Don't know the format: %s\nPick from: %s" % (k, ", ".join(FORMATS)))
            try: n = int(v)
            except ValueError: die("--counts wants a number: %s" % part.strip())
            if n > 0: caps[k] = n
        if not caps:
            die("--counts asked for nothing. Give at least one format a number above zero.")
        want_formats = [f for f in FORMATS if f in caps]
    else:
        want_formats = [f.strip().lower() for f in a.formats.split(",") if f.strip()]
        bad = [f for f in want_formats if f not in FORMATS]
        if bad: die("Don't know the format(s): %s\nPick from: %s" % (", ".join(bad), ", ".join(FORMATS)))
        if not want_formats: want_formats = ["line"]

    A = os.path.abspath(a.assets)
    testing = A != paths.ASSETS
    available_formats = set(want_formats)
    if not testing:
        available_formats = set(catalog.formats(paths.product())) & set(FORMATS)
        if any(fmt not in available_formats for fmt in want_formats):
            die("This content type does not build those formats. Choose an allowed format in Builder.")
    OUTDIR = os.path.abspath(a.out)
    os.makedirs(OUTDIR, exist_ok=True)

    # Pointing --assets somewhere else means you are testing with stand-in clips. A test must
    # never touch the real ledger or the real use counts: a stand-in video would take a video
    # id off a real one, and fake runs would burn through real hook lines.
    STATE = os.path.join(OUTDIR, "state") if testing else WORK
    if testing:
        os.makedirs(STATE, exist_ok=True)
        M.MANIFEST = os.path.join(STATE, "manifest.csv")
        M.VIDEOS = OUTDIR
        print("  test run - ledger and counts kept in %s" % STATE)

    scenes, tuts, _song, emoji, logo_sets = check_assets(A, want_formats)
    font = ensure_font(A)
    renderer = ensure_renderer()

    seed_compare_csv(COMPARE_CSV)

    # A test run gets its own copies of the line files so it cannot burn real lines.
    lines_csv = LINES_CSV if not testing else os.path.join(STATE, "hook_lines.csv")
    cmp_csv = COMPARE_CSV if not testing else os.path.join(STATE, "compare_lines.csv")
    cap_csv = CAPTIONS_CSV if not testing else os.path.join(STATE, "captions.csv")
    for real, copy in ((LINES_CSV, lines_csv), (COMPARE_CSV, cmp_csv), (CAPTIONS_CSV, cap_csv)):
        if testing and not os.path.exists(copy) and os.path.exists(real):
            shutil.copy2(real, copy)

    # Use counts come from successful history rows (`wording_allowances.read`); nothing is
    # written back to these files - the row appended per video IS the record of its spend.
    line_rows, _line_fields = WA.read(lines_csv)
    cmp_rows, _cmp_fields = WA.read(cmp_csv)
    cap_rows, _cap_fields = csvfile.read(cap_csv)
    money_rows, _mf = csvfile.read(MONEY_CSV)
    if not money_rows: die("No money amounts found in %s" % os.path.basename(MONEY_CSV))
    capcol = csvfile.USES_COL

    # Counted off the ledger, not read out of a running total - see `manifest.scene_uses`.
    # Fresh rows rather than the cached answer: this run is about to spend what it says.
    _ledger = M.read_rows()
    clip_uses = M.scene_uses(_ledger)

    # Exact visible-cover and recipe history belongs to build_plan below.
    dup_skipped = []
    # Report exhausted scene/tutorial allowances separately from duplicate combinations.
    spent_skipped = []

    ucol = ccol = csvfile.USES_COL

    live = WA.live(line_rows, path=lines_csv)
    cmp_live = WA.live(cmp_rows, path=cmp_csv)
    if "line" in want_formats:
        if not live:
            print('FAIL Line, then card: no opening lines. Add one under Assets.')
            want_formats.remove('line')
    if "compare" in want_formats and not cmp_live:
        print('FAIL Tick and cross: no pairs. Add one under Assets.')
        want_formats.remove('compare')
    if not want_formats:
        die('None of the requested formats has live wordings left.')

    def scenes_for(fmt):
        return scenes.get(FORMAT_SOURCE.get(fmt, "hooks"), [])

    # Say up front when a format is asked for and has no scenes to work from, rather than
    # letting it silently make nothing and leave "made 0 of 4" to be puzzled over.
    for fmt in want_formats:
        if not scenes_for(fmt):
            where = FORMAT_SOURCE.get(fmt, "hooks")
            print("  no scenes in assets/%s/ - %s cannot build anything yet"
                  % (where, FORMAT_NAMES.get(fmt, fmt)))

    # HOW MANY ONE SCENE MAY MAKE, per format - `per_clip()` says what it is worth in all and
    # `left_for()` what it has left; on the line format that is three per tutorial, counted per
    # (scene, tutorial) off the ledger, so the tutorials are said out loud where the number
    # comes from.
    tut_uses = tutorial_uses(_ledger, A)

    # THE POOLS AS THEY STAND, read once for the whole run - the tutorials, the logo pairs, the
    # tick-and-cross ids. Every `left_for` below
    # takes it, so a batch of twenty asks the disk once instead of once per scene per format.
    pools = pools_now(A)
    exact_plan = build_plan(_ledger, assets=A, pools=pools, line_rows=live,
                            cmp_rows=cmp_live, money_rows=money_rows, emoji=emoji)
    # Which tutorials each format may actually use, as PATHS, in the order check_assets found
    # them. `usable_tutorials` answers in file names; the builder needs the path it opens.
    usable_tuts = {}
    for f in list(want_formats):
        ok = set(usable_tutorials(f, A, pools))
        usable_tuts[f] = [t for t in tuts[f] if os.path.basename(t) in ok]
        if not usable_tuts[f]:
            print("  %s: no eligible tutorials to build with." % FORMAT_NAMES.get(f, f))
            want_formats.remove(f)
    if not want_formats:
        die("No format has an eligible tutorial. Assign tutorials to this content type in Assets.")

    def per_of(f):
        return per_clip(f, A, pools)

    # Only the exceptional case of identical wording across two formats needs a
    # joint basket allocation. Ordinary batches retain their established scene rounds.
    mixed_wordings = None
    scene_names = {fmt:[os.path.basename(h) for h in scenes_for(fmt)] for fmt in want_formats}
    if any(exact_plan.has_shared_covers(name, want_formats)
           for name in set(scene_names.get('line', ())) | set(scene_names.get('compare', ()))):
        limits = caps or {fmt:sum(exact_plan.count(name,fmt) for name in names)
                          for fmt,names in scene_names.items()}
        mixed_wordings = {}
        for candidate in exact_plan.batch_wording_plan(scene_names,limits):
            mixed_wordings.setdefault((candidate['scene'],candidate['format']),[]).append(candidate)

    def left_of(h, f):
        if mixed_wordings is not None and f in PER_TUTORIAL_FORMATS:
            return len(mixed_wordings.get((M.scene_key(os.path.basename(h)),f),()))
        return exact_plan.count(os.path.basename(h), f)
    for f in want_formats:
        if f in PER_TUTORIAL_FORMATS:
            n_tuts = len(usable_tuts[f])
            print("  %s: %d tutorial(s) x %d = %d videos a scene, %d left across the pool"
                  % (FORMAT_NAMES.get(f, f), n_tuts, line_per_tutorial(), per_of(f),
                     sum(left_of(h, f) for h in scenes_for(f))))

    # One entry per video that COULD still be made, as (clip, format). Built format by format
    # and then dealt out round-robin, so asking for four across two formats gives two of each
    # instead of four of whichever came first.
    slots = plan_slots({f: scenes_for(f) for f in want_formats}, clip_uses,
                       want_formats, per_of, left_of)
    if not slots:
        # Said in the build log, with a failing exit, so the panel reports a failed format.
        reason = '; '.join(dict.fromkeys(exact_plan.reason(os.path.basename(h), f)
                          for f in want_formats for h in scenes_for(f))) or 'No eligible starting scenes remain.'
        die("Nothing left to build in %s.\n%s"
            % (" and ".join(FORMAT_NAMES.get(f, f) for f in want_formats), reason))

    batch = time.strftime("%m%d-%H%M")
    tmp = os.path.join(STATE, "render_tmp")
    os.makedirs(tmp, exist_ok=True)
    made = 0
    tutorial_spread, logo_spread, last_tut = supporting_spreads(_ledger)
    line_used, cap_used = {}, {}

    # THE COLOUR GRADE AND THE HOOK SPEED - the two levers that arrived with four videos a scene.
    #
    # Spread by `poolpick.pick` like every other pool in the tool: least-used in this run, then
    # least-used ever, then not used lately, ties at random. The third counter is the one that
    # matters here and the one that looks redundant - with six looks and a balanced pool, a
    # plain coin toss hands the same grade to consecutive videos about one time in six.
    #
    # COUNTED OFF THE LEDGER, never kept in a counter file. Standing rule, and the reason a
    # deleted video hands its grade straight back with nothing to remember.
    #
    # COUNTED ACROSS ALL THREE SILENT FORMATS AT ONCE, not per format. A look is the same look
    # wherever it lands, and a scene's four videos are dealt out across formats - so counting
    # them apart would let `line` and `compare` each settle on "warm" and put the same grade on
    # two videos off one scene, which is the exact thing this is here to prevent.
    # The speed, the mark and the song's start are drawn fresh for every video instead
    # (`micro_repurpose`), so they have nothing to spread.
    look_life, money_life = {}, {}
    look_recent, money_recent = [], []
    for _r in _ledger:
        if _r.get("status") != "ok" or (_r.get("format") or "").strip() not in FORMATS:
            continue
        for _col, _life, _recent in (("look", look_life, look_recent),
                                     ("money", money_life, money_recent)):
            _v = (_r.get(_col) or "").strip()
            if _v:
                _life[_v] = _life.get(_v, 0) + 1
                _recent.append(_v)
    look_used, money_used = {}, {}

    # The money figure gets the same scene-level guard as the grade, and for a sharper reason:
    # on the CARD format it is the only text on the screen, so two of a scene's four showing
    # the same number is two videos that read as one. Six amounts against four slots.
    taken_money = {(M.scene_key(r.get("scene") or ""), (r.get("format") or "").strip(),
                    (r.get("money") or "").strip())
                   for r in _ledger if r.get("status") == "ok"
                   and (r.get("money") or "").strip()}

    # A SCENE MAY NEVER CARRY THE SAME GRADE TWICE IN ONE FORMAT, and this is not the same
    # thing as spreading the grades evenly. `poolpick.pick` keeps the six level ACROSS THE
    # BATCH and knows nothing about where each one is going - which is precisely the fault that
    # made final_0040 and final_0051, and `pick_unused_line` exists one screen up because of
    # it. Caught here the same way, on a real 8-video test run: two `line` videos off
    # Starting-Scenes-02 both came out "plain" while the batch counter was perfectly level.
    #
    # So the grade is filtered to what this scene has not already worn in this format, and only
    # then handed to the picker - the spread still decides WHICH of the free ones, it just
    # cannot choose one that would repeat.
    #
    # PER (SCENE, FORMAT), not per scene. A `line` video and a `compare` video off one scene
    # share no drawn element at all, so they may share a grade; four of one format may not.
    # Five tints against four videos a scene leaves one spare, which is what makes this always possible.
    taken_looks = {(M.scene_key(r.get("scene") or ""), (r.get("format") or "").strip(),
                    (r.get("look") or "").strip())
                   for r in _ledger if r.get("status") == "ok"
                   and (r.get("look") or "").strip()}

    combo_skipped = []
    # --all means "use up every clip that has videos left in it". There is no reason to hold
    # back: these just sit in a folder until Steven posts them by hand, and a folder of videos
    # cannot get an account flagged.
    #
    # With --counts the ceiling is per format instead: `caps` says how many of each, and a
    # format that has had its share is stepped over while the others carry on. The slot order
    # is untouched - variety is still decided by plan_slots, this only decides where to stop.
    fmt_made = {}
    if caps:
        # What can actually be reached, not what was asked for: asking for 5 line videos off
        # scenes that have 2 left in them is 2, and `wanted` has to say 2 or the run reports
        # "made 2 of 5" and looks like it failed.
        have = {}
        for _h, f in slots: have[f] = have.get(f, 0) + 1
        caps = {f: min(n, have.get(f, 0)) for f, n in caps.items()}
        wanted = sum(caps.values())
        counts = dict(caps)
    else:
        wanted = len(slots) if a.all else a.make
        counts = {}
        for _h, f in slots[:wanted]: counts[f] = counts.get(f, 0) + 1
    print("  building %d: %s" % (min(wanted, len(slots)),
          ", ".join("%d %s" % (n, FORMAT_NAMES.get(f, f)) for f, n in counts.items() if n)))
    if wanted <= 0:
        print("Nothing to build."); return

    for hook, fmt in slots:
        if made >= wanted: break
        # This format has had its share. `continue`, never `break` - the slots are dealt out
        # round-robin, so the next entry is very likely a format that still has room.
        if caps and fmt_made.get(fmt, 0) >= caps.get(fmt, 0): continue
        name = os.path.basename(hook)

        # Pick only recipes from the same exact owner used by availability. Its
        # matching shares visible covers across the requested formats and tutorial allowances.
        def tutorial_key(t):
            return (pools['library_by_format'][fmt], os.path.basename(t))
        scene_format = (M.scene_key(name), fmt)
        preferred = [t for t in usable_tuts[fmt] if tutorial_key(t) != last_tut.get(scene_format)] or usable_tuts[fmt]
        first = tutorial_spread.pick(preferred, key=tutorial_key)
        order = ([os.path.basename(first)] if first else []) + [os.path.basename(t) for t in usable_tuts[fmt]]
        prefix = 'c' if fmt == 'compare' else ''
        def wording_rank(r):
            return (line_used.get(prefix + str(r.get('id', '')).strip(), 0),
                    int_or(r.get(ucol), 0))
        card_choices = []
        if fmt == 'card':
            card_choices = exact_plan.card_options(name)
            candidates = card_choices
        elif mixed_wordings is not None:
            candidates = mixed_wordings.get((M.scene_key(name),fmt),[])
        else:
            candidates = exact_plan.wording_plan(name, fmt, tutorial_order=order,
                word_order=lambda tutorial, rows: min(wording_rank(r) for r in rows),
                formats=available_formats)
        offered = {item['tutorial'] for item in candidates}
        free = [t for t in usable_tuts[fmt] if os.path.basename(t) in offered]
        if not free:
            dup_skipped.append(name)
            continue
        choices = [t for t in free if tutorial_key(t) != last_tut.get(scene_format)] or free
        tut = tutorial_spread.pick(choices, key=tutorial_key)
        tutorial_spread.record(tutorial_key(tut))
        last_tut[scene_format] = tutorial_key(tut)
        tut_name = os.path.basename(tut)
        allowed = exact_plan.logos[fmt, tut_name]
        if fmt == 'card':
            card_choices = [item for item in card_choices if item['tutorial'] == tut_name]
            allowed = list(dict.fromkeys(item['pair'] for item in card_choices))
        pair = logo_spread.pick(allowed)
        if fmt != 'compare':
            logo_spread.record(pair)
        chosen_pair = next(p for p in logo_sets if p['key'] == pair)
        row = None
        if fmt in PER_TUTORIAL_FORMATS:
            available = [r for item in candidates if item['tutorial'] == tut_name for r in item['rows']]
            row = min(available, key=lambda r: (*wording_rank(r), random.random()))
            if mixed_wordings is not None:
                candidates.remove(next(item for item in candidates if row in item['rows']))
            e = pick_emoji(emoji) if fmt == 'line' else '❌/✅'
            text = wrap(apply_emoji(row.get('hook_text', '').strip(), e)) if fmt == 'line' else comparison_text(row)
            rid = prefix + str(row.get('id', '')).strip()
            line_used[rid] = line_used.get(rid, 0) + 1
        else:
            text, e = '', ''
            card_choices = [item for item in card_choices if item['pair'] == pair]

        money = pick_money(money_rows, money_life, money_used, money_recent,
                           avoid={m for (sc, f, m) in taken_money
                                  if sc == M.scene_key(name) and f == fmt})
        if fmt == 'card':
            possible_money = list(dict.fromkeys(item['money'] for item in card_choices))
            if money not in possible_money:
                money = PP.pick(possible_money, money_life, money_used, money_recent)
            card_choices = [item for item in card_choices if item['money'] == money]
        money_used[money] = money_used.get(money, 0) + 1
        money_recent.append(money)
        taken_money.add((M.scene_key(name), fmt, money))
        # Same shape as every other pick here: least-used in THIS batch first, then least-used
        # ever, ties at random. Nothing retires - see CAPTIONS_CSV.
        cap_row = None
        if cap_rows:
            cap_row = sorted(cap_rows,
                             key=lambda r: (cap_used.get(str(r.get("id", "")).strip(), 0),
                                            int_or(r.get(capcol), 0), random.random()))[0]
            cap_used[str(cap_row.get("id", "")).strip()] = \
                cap_used.get(str(cap_row.get("id", "")).strip(), 0) + 1

        # The five gentle tints that change the picture (`micro_repurpose.LOOKS`); older names
        # and the untouched one remain readable but are not picked anew. Whole video.
        possible_looks = list(dict.fromkeys(item['look'] for item in card_choices)) if fmt == 'card' else list(MR.LOOKS)
        free_looks = [l for l in possible_looks
                      if (M.scene_key(name), fmt, l) not in taken_looks]
        # A guard that can empty the list is a guard that can hang the pick, so it never can -
        # the same shape `poolpick._stale` uses. It cannot fire while the allowance is under five.
        look = PP.pick(free_looks or possible_looks,
                       look_life, look_used, look_recent)
        look_used[look] = look_used.get(look, 0) + 1
        look_recent.append(look)
        taken_looks.add((M.scene_key(name), fmt, look))

        # THE OTHER THREE MICRO CHANGES, drawn fresh for this video (`micro_repurpose`): the
        # hook's speed (no frame held, and still a legal length - see `draw_hook_speed`), the
        # tutorial's smaller one, the zoom and shift on the composed frame, and a later song
        # start. Not in `taken_looks`' scene guard: they are invisible by design, so they are
        # never what makes two of a scene's four different videos.
        speed = draw_hook_speed(hook, fmt)
        spd_key = RP.speed_key(speed)
        tutorial_speed = MR.draw_speed("tutorial", floor=0)     # fitted to the footage in build_one
        mark = MR.draw_mark()
        song_shift = MR.draw_song_shift(later_only=True)

        # RESERVED, not merely read - see `manifest.claim_id`: two builds running at once must
        # not be handed the same number and overwrite each other's video. A real build saves
        # into this format's own folder; a test run keeps everything in its --out folder.
        destination = OUTDIR if testing else paths.output(fmt)
        idx, out = M.claim_id(destination)
        out_name = os.path.basename(out)
        try:
            ok, source, recipe, err = build_one(out, hook, tut, text, e, money,
                                                A, font, renderer, tmp,
                                                chosen_pair["left"], chosen_pair["right"], fmt,
                                                look, speed, mark, tutorial_speed, song_shift)
        except Exception as ex:
            ok, source, recipe, err = False, name, "", str(ex)[:300]
        except BaseException:
            # A die() deep in a helper is SystemExit, not an Exception.
            M.drop_claim(out)
            raise

        # The same facts as `recipe`, one per column, because spreading and counting work on
        # them. A sentence cannot be sorted.
        tags = {
            "format": fmt,
            "wording_id": str(row.get("id", "")) if fmt in PER_TUTORIAL_FORMATS and row is not None else "",
            "scene": M.scene_key(name),
            "tutorial": os.path.basename(tut),
            "tutorial_library": pools['library_by_format'][fmt],
            "hook_line": text.replace("\n", " / ") if fmt != "card" else "",
            "money": money if fmt != "compare" else "",
            "logo_pair": chosen_pair["key"] if fmt != "compare" else "",
            "emoji": e if fmt == "line" else "",
            "caption": (cap_row.get("caption") or "").strip() if cap_row else "",
            # Columns rather than notes in `recipe` for the same reason every other pool here
            # is: they are spread least-used-first and the counting comes off these rows.
            "look": look,
            "hook_speed": spd_key,
            "frame_mark": mark,
        }
        ledger_row = M.blank_row(
            video_id="final_%04d" % idx, file=out_name if ok else "",
            source=source, recipe=recipe, batch=batch,
            status="ok" if ok else "FAIL", error=err or "", **tags)
        # A failed or unrecordable export is moved out of the finished-video folder here.
        M.record_result(ledger_row, out)

        if ok:
            exact_plan.record(ledger_row)
            made += 1
            # Counted alongside `made`, in the same place and on the same condition, so a
            # format's share is spent by videos that actually came out. A FAIL costs nothing.
            fmt_made[fmt] = fmt_made.get(fmt, 0) + 1
            bump_clip(clip_uses, name, fmt)
            if fmt in PER_TUTORIAL_FORMATS:
                _tk = (fmt, M.scene_key(name), os.path.basename(tut))
                tut_uses[_tk] = tut_uses.get(_tk, 0) + 1
            # In-run copies of the lifetime counts, so later picks in this run rank on them.
            if cap_row is not None:
                cap_row[capcol] = int_or(cap_row.get(capcol), 0) + 1
            if fmt in PER_TUTORIAL_FORMATS and row is not None:
                row[ucol] = int_or(row.get(ucol), 0) + 1
            print("  ok   final_%04d  %-10s %-24s %s"
                  % (idx, fmt, name, (text.replace("\n", " / ")[:46] or money)))
        else:
            print("  FAIL final_%04d  %-10s %-24s %s" % (idx, fmt, name, err[:60]))

    # Nothing to write. The row appended per video IS the record of what that video spent.
    print("\nmade %d of %d requested (batch %s) -> %s" % (made, wanted, batch, OUTDIR))
    if dup_skipped:
        # Never silent. A skipped slot looks exactly like "made 3 of 4" and would be puzzled
        # over otherwise - and the reason is worth reading, because the cure is more lines.
        import collections as _c
        for scene, n in _c.Counter(dup_skipped).most_common():
            print("  skipped %d on %s: every live line has already been used on that scene, "
                  "and two videos with the same line AND the same footage cannot be told "
                  "apart once they are posted. Add lines to fix it." % (n, scene))
    if spent_skipped:
        # The scene has run out of TUTORIALS, not out of lines - it has made its three with
        # every one of them. Its own sentence, because "add lines" is the wrong instruction.
        import collections as _c
        for scene, n in _c.Counter(spent_skipped).most_common():
            print("  skipped %d on %s: it has made its %d videos with every tutorial it may "
                  "use in this format. A new tutorial is worth %d more on it."
                  % (n, scene, line_per_tutorial(), line_per_tutorial()))
    if combo_skipped:
        # Same rule, different pool. This one only ever fires on the card format, which draws
        # no line at all - so its four videos off a scene lean on the tutorial, the money
        # figure, the logo pair and the grade, and this is what refuses when all four repeat.
        import collections as _c
        for scene, n in _c.Counter(combo_skipped).most_common():
            print("  skipped %d on %s: the tutorial, money card, logos and grade had all been "
                  "used together on that scene already, which would have been the same video "
                  "twice. More tutorials or more money cards is the cure." % (n, scene))
    if made < wanted:
        # Say WHY rather than leaving a bare "made 2 of 4" to be puzzled over.
        spare = sum(exact_plan.count(os.path.basename(h), f) for f in want_formats for h in scenes_for(f))
        if not spare:
            print("Ran out of scenes - every one has made all it may in these formats (%s).\n"
                  "Drop more in assets/hooks/ (4.2s+) or assets/hooks_short/ (about 2s), or "
                  "turn on another format." % ", ".join("%d for %s" % (per_of(f), FORMAT_NAMES.get(f, f)) for f in want_formats))
        else:
            print("Stopped early - %d more could still be made from the clips you have." % spare)


if __name__ == "__main__":
    main()
