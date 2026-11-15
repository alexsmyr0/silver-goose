"""The four micro changes a video applies, and the one place their ranges live.

Ported from Golden Goose (commit 3aec2164) on 15 Nov 2026, where Steven's rule of 26 Oct 2026
is that every format applies all four on every video:

  1. ZOOM AND SHIFT    on the whole video: a 2-3% zoom and a few pixels of shift.
  2. SPEED             on every part except the tutorial by up to 3%; on the tutorial by
                       up to 1%. Never slower than the source's frame rate allows.
  3. COLOUR            one of the gentle tints, on the whole video, never the untouched one.
  4. SONG START        the song starts a fraction of a second earlier or later.

IN SILVER GOOSE ONLY THE THREE SILENT FORMATS (line, card, compare) USE THIS MODULE SO FAR.
The other builders still carry the recipes extracted from Golden Goose on 30 Sep 2026
(`docs/architecture.md`); `FORMATS` below lists exactly the ones that draw from here.

None of them lowers the quality of the video, and none of them is a reason to make another
video: allowances and repurposing are counted elsewhere. Each video draws its own value
inside each range, so two videos are not the same few versions over and over. The tints are
the exception: the Card only format counts them as part of what makes one scene's videos
different (see `make_videos.per_clip_n`).

Filters are built by `repurpose` (zoom/shift, speed spelling) and `openart_repurpose` (the
gentle tints). Video and audio timing stay with each builder.
"""
import random

import openart_repurpose as RP

# Format id -> (the module that draws the four changes, the module that renders them).
# Only formats whose builder really draws from this module belong here.
FORMATS = {
    "line": ("make_videos", "make_videos"),
    "card": ("make_videos", "make_videos"),
    "compare": ("make_videos", "make_videos"),
}

# ---- 1. zoom and shift ------------------------------------------------------------------
# The envelope of the measured grid in `repurpose` (zoom 1.02-1.03, shift up to 6px across
# and 12px down). At the smallest zoom there are 11px of spare picture on each side and 19px
# top and bottom, so no shift in range can expose an edge.
ZOOM = (1.020, 1.030)
SHIFT_X, SHIFT_Y = 6, 12
MIN_SHIFT = 2             # px, |dx| + |dy|: a mark always moves the picture as well as zooming

# ---- 2. speed ---------------------------------------------------------------------------
# (smallest change, largest change) either side of 1.00x.
OPENING_SPEED = (0.010, 0.030)
TUTORIAL_SPEED = (0.003, 0.010)
SPEED_PARTS = {"opening": OPENING_SPEED, "tutorial": TUTORIAL_SPEED}

# ---- 3. colour --------------------------------------------------------------------------
LOOKS = [name for name in RP.LOOK_NAMES if RP.look_vf(name)]

# ---- 4. song start ----------------------------------------------------------------------
SONG_SHIFT = (0.04, 0.25)   # seconds, earlier or later


def rng(seed=None):
    """A repeatable generator for a recipe's seed, or the shared one when there is none."""
    return random if seed is None else random.Random(str(seed))


def draw_mark(r=random):
    """A zoom and a shift, always both, inside the measured envelope."""
    zoom = round(r.uniform(*ZOOM), 3)
    while True:
        dx, dy = r.randint(-SHIFT_X, SHIFT_X), r.randint(-SHIFT_Y, SHIFT_Y)
        if abs(dx) + abs(dy) >= MIN_SHIFT:
            return RP.mark_key(zoom, dx, dy)


def valid_mark(key):
    """A saved mark inside the envelope (new draws) or the older measured grid."""
    if not key:
        return False
    if key in RP.marks():
        return True
    try:
        zoom, dx, dy = RP.parse_mark(key)
    except (AttributeError, TypeError, ValueError):
        return False
    return (ZOOM[0] - 1e-9 <= zoom <= ZOOM[1] + 1e-9
            and abs(dx) <= SHIFT_X and abs(dy) <= SHIFT_Y)


def grid_marks():
    """The measured grid without its unzoomed and unshifted states.

    Content farm tells two videos off one scene and title apart by their cover mark, and the
    cover reader was measured on this grid's spacing, so farm picks from it instead of
    drawing freely. Every state still zooms and shifts the whole video."""
    out = []
    for key in RP.marks():
        zoom, dx, dy = RP.parse_mark(key)
        if zoom > 1 and abs(dx) + abs(dy) >= MIN_SHIFT:
            out.append(key)
    return out


def floor_for_fps(src_fps, out_fps=30):
    """The slowest speed that holds no frame. Speeding up never holds one.

    The arithmetic is `repurpose.speeds_for`'s: an output frame at time t comes from source
    time t x speed, so slowing is only free while src_fps x speed >= out_fps. An unreadable
    rate may only speed up."""
    if not src_fps or not out_fps:
        return 1.0
    return min(1.0, out_fps / float(src_fps))


def speed_floor(path, out_fps=30):
    import encode
    return floor_for_fps(encode.clip_fps(path), out_fps)


def draw_speed(part, r=random, floor=1.0, legal=None):
    """A speed for one part of the video, never 1.00x when the format allows any change.

    `floor` is from `floor_for_fps`/`speed_floor`; `legal` is an optional extra test the
    format applies (a silent hook must stay a legal length). Returns 1.0 only when no speed
    in range passes both."""
    low, high = SPEED_PARTS[part]
    sides = [(1 + low, 1 + high)]
    if 1 - low >= floor - 1e-9:
        sides.append((max(1 - high, floor), 1 - low))
    for _ in range(40):
        a, b = r.choice(sides)
        value = round(r.uniform(a, b), 3)
        if (abs(value - 1) >= low - 1e-9 and value >= floor - 1e-9
                and (legal is None or legal(value))):
            return value
    for a, b in sides:
        steps = int(round((b - a) * 1000))
        for i in range(steps + 1):
            value = round(a + i / 1000.0, 3)
            if value >= floor - 1e-9 and (legal is None or legal(value)):
                return value
    return 1.0


def fit_speed(requested, floor):
    """A saved speed made safe for the file actually being rendered.

    Recipes that are drawn before their clips are measured keep the size of the change and
    flip a slowdown the source cannot supply into the same speed-up."""
    requested = float(requested or 1.0)
    if requested >= floor - 1e-9:
        return requested
    return round(2 - requested, 3)


def valid_speed(value, part):
    """A saved speed inside its part's range, or the untouched 1.00x of older recipes."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    if abs(value - 1) < 1e-9:
        return True
    return abs(value - 1) <= SPEED_PARTS[part][1] + 1e-9


def draw_song_shift(r=random, later_only=False):
    """Seconds to move the song's start: earlier (negative) or later (positive)."""
    value = round(r.uniform(*SONG_SHIFT), 3)
    return value if later_only or r.random() < .5 else -value


def valid_song_shift(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return abs(value) <= SONG_SHIFT[1] + 1e-9


def shifted_start(start, shift, seconds=None):
    """A song's saved start moved by `shift`, kept inside the recording."""
    out = max(0.0, float(start) + float(shift or 0))
    if seconds:
        out = min(out, max(0.0, float(seconds) - 0.5))
    return round(out, 3)


def draw(r=random, *, opening_floor=1.0, tutorial_floor=1.0, later_only=False):
    """All four changes for one video, for formats that take them as one recipe entry."""
    return dict(mark=draw_mark(r),
                look=r.choice(LOOKS),
                speed=draw_speed("opening", r, opening_floor),
                tutorial_speed=draw_speed("tutorial", r, tutorial_floor),
                song_shift=draw_song_shift(r, later_only))
