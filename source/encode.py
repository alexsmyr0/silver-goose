"""The small shared bits every builder needs, in one place.

Running ffmpeg and ffprobe, compiling a Swift helper on first use, finding the font, and
turning a list of pictures into a video track. None of it knows anything about a format -
that is the point. `make_pump.py` had its own copy of all of this, which was fine while pump
was the only format built this way; a second one would have made it two copies, and the
frame-by-frame rule below is exactly the kind of measured thing that must not exist twice.

Lifted out of make_pump.py on 29 Aug 2026, unchanged. `make_videos.py` and `speech.py` still
carry their own older `run`/`duration` - they are not touched here, deliberately: this change
is verified by rebuilding pump videos to the identical frame, and widening it to the OpenArt
builders would put that proof out of reach.
"""
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# The canvas every format here draws on, and the rate it is built at. 30, not 60: the CapCut
# projects these were measured off are 30fps and the 60fps exports just duplicate every
# frame. Same motion, half the file.
W, H, FPS = 1080, 1920, 30

# ---------------------------------------------------------------------------------------
# One audio profile for every finished video, including reposts.
#
# Meta documents AAC at 48 kHz and one or two channels. Buffer's published Instagram
# guidance lists 128 kbps. We deliberately target 120 kbps, stereo: ffmpeg's AAC bitrate
# setting is a target, not a strict output ceiling. In a 36-file local sample on 12 Sep
# 2026, files built with the old 128k target measured 128.2-132.6 kbps; two reposts used
# 192k and inherited 44.1 kHz. The preparation step still needs to verify the actual file.
# This headroom is our conservative export policy, not an additional platform requirement.
#
# Historical correction: the 3 Sep experiment once described here as proof that the
# sample rate caused failures also remuxed the container and stripped its metadata.
# docs/PROGRESS.md records the stronger comparison: identical audio and video bitstreams
# from final_0068 failed with accumulated metadata and published after a clean remux.
# Keeping 48 kHz follows the documented spec; the evidence does not establish that
# Instagram tightened sample-rate enforcement that week, or that every media error
# comes from the file. Buffer has also used that message for disconnected accounts.
AUDIO_RATE = 48000
AUDIO_KBPS = 120
AUDIO_CHANNELS = 2


def audio_args():
    """The `-c:a` flags every finished video is encoded with. Never spelled out at a call site."""
    return ["-c:a", "aac", "-b:a", "%dk" % AUDIO_KBPS, "-ar", str(AUDIO_RATE),
            "-ac", str(AUDIO_CHANNELS)]


# ---------------------------------------------------------------------------------------
# Advisory checks used by the planning card. The upload preparation step must verify the
# file actually sent. These original checks cover only part of the platform guidance;
# a media-container error alone cannot identify the failing property.
IG_MAX_SECONDS = 15 * 60          # Meta: 3s to 15min for a reel
IG_MIN_SECONDS = 3
IG_MAX_WIDTH = 1920               # Meta: max 1920px on the long edge of the frame
IG_FPS_RANGE = (23, 60)
IG_MAX_VIDEO_MBPS = 25
IG_AUDIO_CHANNELS = (1, 2)


def instagram_problems(path, ignore_fixable=False):
    """Every way this file breaks Instagram's reel spec, in plain English. `[]` means fine.

    `ignore_fixable` leaves out the ones the POSTING path repairs on its way out, which today
    is the sample rate alone (`bufferpost.instagram_rate`). The card passes True: warning him
    about something the tool is about to fix by itself is how a panel teaches him to ignore its
    warnings. Everything else is his to decide about, so it is said.

    NEVER RAISES AND NEVER GUESSES. A file it cannot read answers `[]` - "I could not check"
    must not read as "this is broken", or the panel starts refusing videos on a missing ffprobe.
    The cost of a miss here is what we already had; the cost of a false alarm is Steven not
    posting a video that would have been fine.
    """
    import json as _json
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                            "-show_format", "-show_streams", path],
                           capture_output=True, text=True, timeout=120)
        d = _json.loads(r.stdout or "{}")
    except Exception:
        return []
    streams = d.get("streams") or []
    if not streams:
        # NOTHING CAME BACK AT ALL, so the file is missing, unreadable, or ffprobe is not here.
        # "I could not check" must never read as "this is broken" - the docstring above is a
        # promise, and returning a complaint here breaks it. A missing file answered "it has no
        # video in it" until this line existed.
        return []
    v = next((x for x in streams if x.get("codec_type") == "video"), None)
    a = next((x for x in streams if x.get("codec_type") == "audio"), None)
    fmt = d.get("format") or {}
    out = []
    if v is None:
        return ["it has no video in it"]
    if a is None:
        out.append("it has no sound, and Instagram will not take a reel without an audio track")

    def num(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    if a is not None:
        rate = int(num(a.get("sample_rate")))
        if rate and rate != AUDIO_RATE and not ignore_fixable:
            # THE ONE THAT COST TWO DAYS. `bufferpost.instagram_rate` fixes it on the way out,
            # so this should only ever be seen on a video nothing has hosted yet.
            out.append("its sound is %d kHz and Instagram wants %d"
                       % (rate // 1000, AUDIO_RATE // 1000))
        ch = int(num(a.get("channels")))
        if ch and ch not in IG_AUDIO_CHANNELS:
            out.append("it has %d sound channels and Instagram takes 1 or 2" % ch)
    dur = num(fmt.get("duration") or v.get("duration"))
    if dur and dur > IG_MAX_SECONDS:
        out.append("it is %d minutes long and Instagram stops at %d"
                   % (dur // 60, IG_MAX_SECONDS // 60))
    if dur and dur < IG_MIN_SECONDS:
        out.append("it is %.1f seconds long and Instagram wants at least %d"
                   % (dur, IG_MIN_SECONDS))
    if str(v.get("codec_name") or "").lower() not in ("h264", "hevc"):
        out.append("its picture is %s and Instagram takes h264 or hevc"
                   % (v.get("codec_name") or "unreadable"))
    if str(v.get("pix_fmt") or "") not in ("yuv420p", "yuvj420p"):
        out.append("its colour is %s and Instagram wants yuv420p" % v.get("pix_fmt"))
    if max(int(num(v.get("width"))), int(num(v.get("height")))) > IG_MAX_WIDTH:
        out.append("it is %sx%s and Instagram stops at %d on the long edge"
                   % (v.get("width"), v.get("height"), IG_MAX_WIDTH))
    fps = v.get("avg_frame_rate") or "0/1"
    try:
        n, _, dnm = fps.partition("/")
        fps = float(n) / float(dnm or 1)
    except Exception:
        fps = 0.0
    if fps and not (IG_FPS_RANGE[0] <= round(fps) <= IG_FPS_RANGE[1]):
        out.append("it runs at %d frames a second and Instagram takes %d to %d"
                   % (round(fps), IG_FPS_RANGE[0], IG_FPS_RANGE[1]))
    vb = num(v.get("bit_rate")) / 1e6
    if vb > IG_MAX_VIDEO_MBPS:
        out.append("its picture is %.0f Mbps and Instagram stops at %d"
                   % (vb, IG_MAX_VIDEO_MBPS))
    if str(v.get("field_order") or "progressive") not in ("progressive", "unknown"):
        out.append("it is interlaced and Instagram wants progressive")
    return out


def audio_format(label_in, label_out, extra=""):
    """An `aformat` filter for a graph that mixes audio, at the one rate that publishes.

    `extra` goes between the input and the format, for a graph that needs to trim or pad first.
    """
    return ("[%s]%saformat=sample_fmts=fltp:sample_rates=%d:channel_layouts=stereo[%s];"
            % (label_in, extra, AUDIO_RATE, label_out))


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode:
        raise RuntimeError("failed: %s\n%s" % (" ".join(map(str, cmd))[:300], p.stderr[-2000:]))
    return p.stdout


def ensure_exe(src, exe):
    """Compile a Swift helper on first use, the same way make_videos.py does."""
    s, e = os.path.join(HERE, src), os.path.join(HERE, exe)
    if not os.path.exists(e) or os.path.getmtime(s) > os.path.getmtime(e):
        run(["swiftc", "-O", "-o", e, s])
    return e


def clip_fps(path):
    """A clip's own frame rate, or 0 if it cannot be read.

    Lifted here on 6 Sep 2026 when the THIRD builder needed it - `make_videos` and
    `make_humbled` each carried a copy and said "if a third arrives, lift all three". It decides
    which speeds a clip may run at without a frame being held: `repurpose.speeds_for`.
    """
    import json
    import math
    try:
        # CSV can append empty side-data fields ("30/1,") to valid frame rates.
        # Read the named JSON field so that metadata cannot turn 30 fps into unknown.
        data = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=r_frame_rate", "-of", "json", path]))
        a, _, b = data['streams'][0]['r_frame_rate'].partition("/")
        fps = float(a) / float(b or 1)
        return fps if math.isfinite(fps) and fps > 0 else 0.0
    except Exception:
        return 0.0


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", path]).strip())


def font_path(assets):
    """The Classic font (TikTok Display Medium), out of the CAMPAIGN's own assets folder.

    This was an absolute path into CapCut's own cache until 27 Aug 2026, with a username
    written into it. Two things wrong with that, and neither would have said so plainly: the
    format could only ever build on one Mac, and CapCut's cache is a CACHE - the day it is
    cleared or the app is uninstalled, the failure comes out of the Swift renderer as a font
    it could not load rather than as a sentence anybody can act on.

    `render_support.ensure_font` is the one place that knows where CapCut keeps it. It copies it
    to `assets/font.ttf` on first use, per campaign, which is what the other four formats have
    always done - so a format keeps working after CapCut is gone, and a new install gets the
    same one-line explanation instead of a stack trace.

    The shared support module imports no builder. Campaign paths are resolved only when
    the font is requested, preserving account scope without a dependency back to a recipe.
    """
    import render_support as RS
    return RS.ensure_font(assets)


def blank_png(path):
    from PIL import Image
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(path)
    return path


def concat_file(path, items):
    """A concat-demuxer list. The last entry is repeated because the demuxer ignores the
    final `duration` otherwise and the stream ends a frame early."""
    with open(path, "w") as f:
        for p, d in items:
            f.write("file '%s'\nduration %.4f\n" % (os.path.abspath(p).replace("'", r"'\''"), d))
        f.write("file '%s'\n" % os.path.abspath(items[-1][0]).replace("'", r"'\''"))
    return path


def frame_seq(pngs_per_frame, out_path, work, name, alpha=False):
    """Encode a track by naming the picture for EVERY frame, not by giving durations.

    The concat demuxer takes float durations and rounds each one onto the frame grid as it
    goes. Even with every duration an exact multiple of 1/30, sixty of them accumulate enough
    float error that roughly half land a frame early - measured on a real build, four of the
    six scene changes had their caption appear one frame before the picture did.

    A symlink per frame removes the arithmetic entirely: frame N is whatever frame N should
    be. The links are free and there are only ever a handful of distinct images behind them.
    """
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    for i, src in enumerate(pngs_per_frame):
        link = os.path.join(d, "%06d.png" % i)
        os.symlink(os.path.abspath(src), link)
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS),
           "-i", os.path.join(d, "%06d.png")]
    # THE OPAQUE TRACK IS `libx264rgb -qp 0`, AND THE `rgb` MATTERS - see below.
    #
    # It was `ffv1 -pix_fmt bgr0` until 1 Sep 2026. Both are lossless, and the change is worth
    # 8 seconds of the 44 a CR7 video takes, measured on the still track of a real build:
    #
    #                       write     size     decode back
    #     ffv1 bgr0          6.9s    736 MB      4.4s
    #     libx264rgb qp=0    2.5s     19 MB      0.5s
    #
    # 39 times smaller, because 956 frames of it are only seven distinct pictures and x264
    # codes a repeated frame almost for nothing while ffv1 pays full price for every one. The
    # composite reads this file back, so the saving is taken twice.
    #
    # **IT IS `libx264rgb` AND NOT `libx264`, and that is the whole care in this change.**
    # Decoded and hashed frame by frame against the ffv1 it replaces: `libx264rgb -qp 0` is
    # 956 of 956 frames IDENTICAL. Plain `libx264 -qp 0 -pix_fmt yuv444p` is smaller still and
    # 0 of 956 identical - "lossless" there means lossless of the YUV it was handed, and the
    # RGB->YUV conversion in front of it is not reversible. A lossless codec fed through a
    # lossy conversion is a lossy pipeline, and it would have gone unnoticed.
    #
    # The ALPHA track stays `qtrle`: x264 has no alpha, and at 7 MB and 1.2s it is not costing
    # anything worth chasing.
    cmd += ["-c:v", "qtrle", "-pix_fmt", "argb"] if alpha else \
           ["-c:v", "libx264rgb", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "rgb24"]
    run(cmd + [out_path])
    return out_path
