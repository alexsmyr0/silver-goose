#!/usr/bin/env python3
"""repurpose.py - the levers that make two videos off the same footage different videos.

**Why this is a module and not two copies.** Both pump formats need the same two things - a
serial number a cover reader can recover, and a change a VIEWER can see - and the numbers
behind them were measured once. `headcut.py`, `talktrack.py`, `poolpick.py` and `encode.py`
exist for exactly this reason: a constant that exists twice is a constant that will be
corrected once. Nothing in here knows which format is being built.

There are two levers and they are NOT the same thing. Getting them the wrong way round is the
mistake `pump.md` records as *A MARK IS NOT A CEILING*:

  THE MARK    a zoom and a pan. Invisible on purpose - about 1.5% off each edge. Its whole job
              is to let `cover_match` say WHICH video a post was, so it is handed back the
              moment that post is accounted for. It is not a reason to make another video.

  THE LOOK    a colour grade over the whole timeline. Plainly visible, and it does the opposite
              job: nothing reads it back, it is never a signature, and it exists so two videos
              off one talking head are not the same video to a person watching them.

**Where the look comes from.** `research/GRATTGRINDS.md` - a teardown of 114 files off a
competitor account running our `humbled` format. His entire repurposing method is one
randomised global colour grade, whole frame, whole runtime: saturation ranging 51% of its mean
across 23 files that share byte-identical audio, brightness 31%, contrast 35%. No speed change,
no duration jitter, no audio trick, nothing localised. 28 uploads with byte-identical audio all
published and one of them reached 247,461 views.

**Ours is deliberately gentler than his** - measured below at roughly half his saturation range
and an eighth of his contrast range - because we are not evading anything. He grades to stop a
platform seeing a duplicate; we grade so a second video off one head is worth watching. The
tool still has to recognise its own covers afterwards, and that is measured too.
"""

# ---------------------------------------------------------------------------
# THE MARK - the geometry, and the one place its spelling lives
# ---------------------------------------------------------------------------
# MEASURED, and the measurement is in `pump.md` under "Making one opening clip last for
# hundreds of videos": 30 states built, put through a hard platform re-encode (crf 28,
# downscaled to 720x1280) and a 360x640 JPEG cover, then matched against our own renders.
# **30 of 30 recovered, 0px of black exposed, smallest margin +0.00846.** A COLOUR mark was
# measured NOT to survive the same pipeline - signal and noise both 0.002 - which is why the
# look below is never asked to identify anything.
#
# THE PAN NEEDS THE ZOOM, and this is the part found by checking rather than reasoning: a pan
# of D pixels needs `zoom >= 1 + D/540` horizontally or it drags a black strip in from the
# edge. At zoom 1.000 a 12px pan leaves a visible 12px band. At 1.02 there are 10.8px of
# overscan against a 6px pan and 19.2px against a 12px one, so nothing here can expose an edge.
ZOOMS   = (1.02, 1.03)
MARK_DX = (-6, 0, 6)
MARK_DY = (-12, -6, 0, 6, 12)
MARK_STATES = len(ZOOMS) * len(MARK_DX) * len(MARK_DY)


def mark_key(zoom, dx, dy):
    """The zoom and pan as the ledger spells it.

    ONE converter, so the row, the cover check and the recency list can never be keyed
    differently from each other. The format is fixed by 10 live ledger rows - do not change it.
    """
    return "%.3f/%+d/%+d" % (zoom, dx, dy)


def parse_mark(key):
    """`"1.020/-6/+12"` back to `(1.02, -6, 12)`."""
    z, dx, dy = key.split("/")
    return float(z), int(dx), int(dy)


def marks():
    """Every mark, in a fixed order."""
    return [mark_key(z, dx, dy) for z in ZOOMS for dx in MARK_DX for dy in MARK_DY]


def mark_vf(zoom, dx, dy, w, h):
    """The mark as filters on an ALREADY COMPOSED frame: zoom in, then crop back to size.

    This is CR7's way of wearing it. Humbled puts the same numbers on its opening clip alone,
    because that clip is the whole of its cover and the talking head after it is not; CR7's
    cover is the composed frame, title and corner man included, so the mark goes on all of it.

    Zoom first and crop after means there is never an edge to expose - the crop only ever
    takes pixels the scale has just made. That is why the same grid carries over from a clip
    that had to be checked for black strips.
    """
    sw = max(w, round(w * zoom / 2) * 2)
    sh = max(h, round(h * zoom / 2) * 2)
    return ("scale=%d:%d:flags=lanczos,crop=%d:%d:(iw-%d)/2+(%d):(ih-%d)/2+(%d)"
            % (sw, sh, w, h, w, dx, h, dy))


# ---------------------------------------------------------------------------
# THE LOOK - the colour grade, which is grattgrinds' one lever
# ---------------------------------------------------------------------------
# `(saturation, gamma, contrast, hue)`. The first three go to ffmpeg's `eq`, the last to `hue`.
#
# **THERE IS NO ADDITIVE BRIGHTNESS HERE AND THAT IS NOT AN OVERSIGHT.** `eq=brightness` adds a
# constant to every pixel, and both of these formats sit on PURE BLACK - CR7's stills track
# shows black wherever a still does not cover the frame, and a letterboxed humbled opening has
# black bars top and bottom. Measured on `final_0051`: `brightness=0.05` lifts the darkest 1%
# of the frame from 3 to 13 grey levels, which reads as a fault rather than a grade. `gamma`
# does the same job to the midtones and leaves black at black - the same frame measures 8.5
# at `gamma=1.12`, a five-level lift on the darkest pixels nobody can see.
#
# MEASURED per lever on a real frame of `final_0051` (87% of it not near-black), 1 Sep 2026:
#
#   eq=saturation 1.06  ->  +7.1% HSV saturation      1.15 -> +16.7%
#   eq=contrast   1.08  ->  +5.5% contrast, -5.3% value, +10.0% saturation
#   hue=h=6 / h=12      ->  no change to any of the three magnitudes: it moves colour, not size
#
# ...and the six together, sampled at 10/25/40/60/75/90% of `final_0051` exactly the way
# `GRATTGRINDS.md` sampled his, as the range across the six over the mean:
#
#                     saturation   brightness   contrast
#     ours                  23%          26%         4%
#     grattgrinds           51%          31%        35%
#
# So it is under half his saturation range and a fraction of his contrast, and the darkest 1%
# of the frame stays between 0.0 and 8.5 on every one of them.
#
# The hue values span 15 degrees of 180. The circular mean of the measured frames moves further
# than that and is not worth quoting: hue is unstable to average over a picture that is mostly
# dark, which is what a CR7 frame is.
LOOKS = {
    "plain": (1.00, 1.00, 1.00,  0),   # the reference look, untouched. It stays in the pool.
    "warm":  (1.08, 1.00, 1.00,  7),
    "cool":  (1.08, 1.00, 1.03, -8),
    "lift":  (1.02, 1.12, 1.00,  0),
    "deep":  (0.93, 0.94, 1.08,  0),
    "rich":  (1.12, 1.05, 1.00,  3),
}
LOOK_NAMES = list(LOOKS)


def look_vf(name, looks=None):
    """The look as ffmpeg filters, or "" for the one that does nothing.

    An unknown name grades nothing rather than raising: a look is read back off the ledger to
    rebuild a video, and a row written by a newer version must not stop an older one reading it.
    """
    palette = LOOKS if looks is None else looks
    s, g, c, h = palette.get(name or "plain", palette["plain"])
    out = []
    if (s, g, c) != (1.0, 1.0, 1.0):
        out.append("eq=saturation=%.3f:gamma=%.3f:contrast=%.3f" % (s, g, c))
    if h:
        out.append("hue=h=%.1f" % h)
    return ",".join(out)


def tail_vf(mark, look, w, h, looks=None):
    """Both levers, in the order they go on the end of a filter chain, or "" for neither.

    The mark goes on FIRST. It is a resample, and grading a resampled frame is the same
    picture as resampling a graded one - but doing the geometry first means the grade is the
    last thing that touches the pixels, which is what the reference measurement above was
    taken on.
    """
    bits = []
    if mark:
        bits.append(mark_vf(*parse_mark(mark), w=w, h=h))
    lv = look_vf(look, looks=looks)
    if lv:
        bits.append(lv)
    return ",".join(bits)


# ---------------------------------------------------------------------------
# THE MUSIC SHIFT - a few hundredths of a second, and it is a DELAY, not a skip
# ---------------------------------------------------------------------------
# Steven, 1 Sep 2026: *"I want the jitter to be very small because I generally always want the
# music to start at the time I've set it to start."*
#
# **So it does not skip INTO the track, it starts the WHOLE track a few hundredths later.** That
# distinction is not pedantry, it is what the measurement said to do. Humbled's `music-01.m4a`
# opens on a hit and decays hard - 0.00s measures -17.7 dB, 0.15s -26.0, 0.45s -33.5 - so
# skipping even a tenth of a second into it eats the attack it opens on. CR7's track is a steady
# bed (-15.7 at 0.00, -16.4 at 0.30) and would not have cared, but one rule for both is simpler
# than two, and a delay costs NOTHING on either: every note still plays.
#
# **A tiny shift is fully enough for what this is for.** It makes the mixed audio a completely
# different set of samples, so no two videos are byte-identical and no fixed-segment hash can
# match them. What it does NOT do is make a person hear different music - and that is what he
# asked for. Seconds would be needed for that, and seconds are what would cost him the opening
# of a track he chose.
#
# POSITIVE ONLY. On humbled the music starts at the cut to the talking head and not at zero -
# measured, and it is the reference build's own behaviour: under the opening clip you hear that
# clip's own audio and nothing else. A negative shift would start it before the cut.
# PROVED, not assumed: the same video built twice, differing ONLY by this, came back with
# **frame-identical picture and different audio data**. It does one thing and touches nothing.
MUSIC_SHIFT = (0.00, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14)


def shift_key(seconds):
    """The music shift as the ledger spells it - milliseconds, so it is a whole number."""
    return "%dms" % round(seconds * 1000)


def shift_of(key):
    """`"60ms"` back to `0.06`. A blank reads as no shift, which every row before 1 Sep 2026 is."""
    try:
        return int(str(key).strip().rstrip("ms") or 0) / 1000.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# THE OPENING-CLIP SPEED - humbled only, and it is the safe place to put speed
# ---------------------------------------------------------------------------
# The opening clip is borrowed footage, it plays before the hard cut, and NOTHING of ours is
# synced to it - no captions, no pictures, no still changes. So a tempo change there cannot
# desync anything, which is not true of the talking half and is the whole reason the speed lever
# lives here rather than on the finished video.
#
# **IT IS FREE OR IT IS NOT OFFERED, and that took a measurement to get right.** Counting frames
# that are byte-identical to the one before, over the first 6 seconds of a real render:
#
#                              0.94x   0.97x   1.00x   1.03x   1.06x
#   starting_vid-04 (60fps)      0%      0%      0%      0%      0%
#   starting_vid-01 (30fps)    6.1%    2.8%      0%      0%      0%
#
# The rule behind that, and it is arithmetic rather than a threshold: an output frame at time t
# comes from source time `t x speed`, so the source supplies `src_fps x speed / FPS` frames for
# every one we emit. Below 1.0 of those a frame has to be held. **So a clip may be SLOWED only
# while `speed >= FPS / src_fps`** - free on anything shot at 60, never free on a 30fps source.
# `speeds_for()` applies exactly that, so a 30fps clip is offered 1.00x and faster and nothing
# is ever held. Speeding UP costs nothing on any source: it drops frames rather than repeating
# them, and there were 0 repeats in every column above from 1.00x rightwards.
#
# `atempo` is PITCH-PRESERVING, so the clip's own audio does not go squeaky. It is what plays
# under the whole opening, so that matters.
#
# ±6% on footage nobody has seen the original of. It also moves the finished length, which is
# worth knowing: `research/FINDINGS.md` measures 25-30s as the best band (24% against a 12.3%
# baseline) and these builds land at 29.6-33s. That was measured on a different account and a
# different format, so it is a reason to watch the number rather than to chase it.
SPEEDS = (0.94, 0.97, 1.00, 1.03, 1.06)


def speeds_for(src_fps, out_fps, speeds=None):
    """Which speeds this clip may have without a single frame being held.

    See the table above for the measurement and the one line of arithmetic behind it. An
    unreadable frame rate gets `1.00x` alone - nothing here may cost quality on a guess.
    """
    if not src_fps or not out_fps:
        return [1.0]
    floor = out_fps / float(src_fps)
    choices = SPEEDS if speeds is None else speeds
    return [v for v in choices if v >= floor - 1e-9] or [1.0]


def speed_key(speed):
    """The speed as the ledger spells it."""
    return "%.2fx" % speed


def speed_of(key):
    """`"1.03x"` back to `1.03`. A blank reads as 1.0 - every row before 1 Sep 2026."""
    try:
        return float(str(key).strip().rstrip("x") or 1.0)
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# WHAT THE COVER READER MAKES OF ALL THIS - measured, 1 Sep 2026
# ---------------------------------------------------------------------------
# Run on a real built CR7 video (`final_0051`): six copies differing only by their mark, each
# put through a hard re-encode to 720x1280 and read back off a 360x640 JPEG cover.
#
#   the coarse pass  6 of 6 right, gaps 0.006 to 0.058   - under PIC_GAP, so it refuses alone
#   `_differences`   6 of 6 right, gaps 0.514 to 0.655, absolute 0.986 to 0.988
#
# `DIFF_GAP` is 0.20 and `DIFF_MIN` is 0.80, so the pass that looks at where the candidates
# differ clears its bar by two and a half to three times. For comparison, the same pass on six
# videos separated by nothing but the builder's 1-5px nudge measured a gap of 0.211 - right on
# the bar. **A mark is an order of magnitude stronger than the nudge**, which is what makes two
# CR7 videos off one head and one wording safe to build.
#
# THE GRADE DOES NOT BLIND IT. The same six with a DIFFERENT look on each came back 6 of 6
# right with gaps of 0.506 to 0.634 - about a hundredth off the ungraded numbers.
#
# ...AND THE GRADE IS NOT ITSELF A MARK, which is the half that had to be true. Six copies
# sharing one mark and differing only by look scored a THREE-WAY TIE at the top (0.9849,
# 0.9849, 0.9847), so `_confirms` refuses, exactly as it should. `cover_match._unit` takes the
# mean and the scale out of every frame before comparing, so brightness and contrast cannot
# decide an answer here by design. **Never put the look in a cover signature.**


# ---------------------------------------------------------------------------
# WHAT WAS REJECTED, AND WHY - so nobody re-derives it
# ---------------------------------------------------------------------------
# * A COLOUR MARK - a grade you read back to identify a video. Measured 29 Aug 2026 through our
#   own encode, a hard platform re-encode and a JPEG cover: recovered delta 0.0024 across a
#   x1.005 to x1.080 sweep against frame-to-frame noise of 0.0020. Signal to noise about 1.
#   The look above is fine BECAUSE nothing reads it back.
#
# * A MIRROR / HORIZONTAL FLIP. Big, survives everything, and wrong here: the borrowed opening
#   clips carry their own burned-in captions and flipped text reads as broken.
#
# * SPEED ON THE TALKING HALF, or on the finished video. He does none at all - his 114 files
#   collapse to 16 durations, each exact to six decimal places within its group. Ours is on the
#   OPENING CLIP only, where nothing is synced to it; putting it on the composed video would
#   drag a caption and picture engine that is measured to the frame. **Steven asked for the
#   speed lever on 1 Sep 2026 and this is the half of it that was safe to give him.**
#
# * PITCH-SHIFTING HIS VOICE. `atempo` above is pitch-preserving on purpose. Even a couple of
#   per cent is audible on somebody talking to camera, and his voice is the product.
#
# * A BIG MUSIC OFFSET - starting seconds into the track. It is the version that would make a
#   person hear different music, and it is the version Steven turned down: he wants the track to
#   start where he set it. The measurement above says he is right on the audio as well, because
#   one of the two tracks opens on a hit.
#
# * PER-FRAME GRAIN OR NOISE. Low-amplitude signal is exactly what a platform re-encode throws
#   away, which is the same measurement that killed the colour mark. It costs bitrate on a file
#   we are already paying to host.
#
# AND THE ONE THING THIS FILE CANNOT DO. `GRATTGRINDS.md` section 10 measures two accounts
# running this same trick: 13 opening clips and 17 builds against 1 clip and 3 builds, similar
# floors, and ceilings of 247,461 against 15,382. **Creative variety tracked the outcome and
# grade randomisation did not.** So the look buys distribution, not performance - more footage
# and more wordings are still the levers that move views, and nothing in here replaces them.
