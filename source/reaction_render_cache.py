"""Bounded, reproducible Hook Story intermediates, separate from durable work state."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

import encode as E
import reaction_captions as RC

MAX_BYTES = 4 * 1024**3
VERSION = 'fast-media-v1'


def root(cache):
    path = Path(cache) / VERSION
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def session(cache):
    """Readers pin this cache while rendering; pruning never removes an in-use file."""
    folder = root(cache)
    with (folder / '.lease').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                prune(folder)
                fcntl.flock(lock, fcntl.LOCK_UN)


def prune(folder):
    # With an exclusive lease no active build owns a temporary file here.
    for partial in folder.glob('*.tmp-*'):
        if partial.suffix in ('.mov', '.mp4'):
            partial.unlink()
    files = [p for p in folder.iterdir() if p.suffix in ('.mov', '.mp4') and '.tmp-' not in p.name]
    files.sort(key=lambda p: p.stat().st_mtime)
    size = sum(p.stat().st_size for p in files)
    for path in files:
        if size <= MAX_BYTES:
            break
        size -= path.stat().st_size
        path.unlink()


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def geometry(settings, w, h):
    top, bottom, left, right = [settings.get('crop_'+side, 0)
                               for side in ('top', 'bottom', 'left', 'right')]
    cw = max(2, int(w*(1-left-right))//2*2)
    ch = max(2, int(h*(1-top-bottom))//2*2)
    ow = max(2, int(w*settings['width'])//2*2)
    oh = max(2, int(ow*ch/cw)//2*2)
    return cw, ch, round(w*left), round(h*top), ow, oh


def cached(path, command, estimated_bytes=0):
    """One writer per intermediate, atomic completion, no reusable partial files."""
    with Path(str(path)+'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.is_file() and path.stat().st_size:
            os.utime(path, None)
            return str(path)
        from storage_guard import require_space, BUILD_HEADROOM
        require_space(path.parent, BUILD_HEADROOM + estimated_bytes)
        temp = path.with_name(path.stem+'.tmp-'+uuid.uuid4().hex+path.suffix)
        try:
            E.run(command + [str(temp)])
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return str(path)


def foreground(asset, wanted_frames, cache, w, h, *, source, frames):
    """Prepare only the silent reaction. Speech-bearing intros keep their audio path.

    Eight-second buckets let several hook lengths share a prepared clip. Final trim
    still uses the recipe's exact frames; looping uses the complete selected take.
    """
    s = asset['settings']
    available = frames(s['end']-s['start'])
    needed = min(wanted_frames, available)
    extent = min(available, int(math.ceil(needed/240))*240)
    crop = geometry(s, w, h)
    identity = key([asset['id'], s['start'], s['end'], w, h, crop, 'silent-alpha-1'])
    folder = root(cache)
    reusable = []
    for p in folder.glob(identity+'-*.mov'):
        try:
            count = int(p.stem.rsplit('-', 1)[1])
            if count >= needed and p.stat().st_size:
                reusable.append((count, p))
        except (ValueError, FileNotFoundError):
            continue
    if reusable:
        path = min(reusable)[1]
        os.utime(path, None)
        return str(path), needed
    path = folder / ('%s-%d.mov' % (identity, extent))
    end = min(s['end'], s['start']+extent/30)
    vf = ('format=rgba,trim=start=%.8f:end=%.8f,setpts=PTS-STARTPTS,fps=30,'
          'scale=%d:%d:force_original_aspect_ratio=decrease,'
          'pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1,'
          'tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame=%d,settb=1/30,setpts=N,'
          'format=rgba,crop=%d:%d:%d:%d,scale=%d:%d') % (
              s['start'], end, w, h, w, h, extent, *crop)
    from media_source import ensure_sdr
    src = ensure_sdr(source(asset))
    cmd = ['ffmpeg', '-v', 'error', '-y']
    if src.lower().endswith('.webm'):
        cmd += ['-c:v', 'libvpx-vp9']
    cmd += ['-i', src, '-vf', vf, '-an', '-c:v', 'qtrle', '-pix_fmt', 'argb',
            '-t', '%.8f' % (extent/30)]
    return cached(path, cmd, crop[4]*crop[5]*4*extent), needed


def ending(path, nf, settings, note, pngs, cache, w, h):
    """Cache the framed, captioned ending losslessly and copy its prepared audio."""
    stat = os.stat(path)
    identity = key([path, stat.st_size, stat.st_mtime_ns, nf, settings.get('frame_scale', 1),
                    settings.get('frame_x', .5), settings.get('frame_y', .5), note,
                    RC.FONT_SHA256, w, h, 'captioned-ending-1'])
    dest = root(cache) / (identity+'.mp4')
    zoom = settings.get('frame_scale', 1)
    cw, ch = max(2, int(w/zoom)//2*2), max(2, int(h/zoom)//2*2)
    graph = ['[0:v]crop=%d:%d:%d:%d,scale=%d:%d,setsar=1,format=yuv420p[base]' % (
        cw, ch, round((w-cw)*settings.get('frame_x', .5)),
        round((h-ch)*settings.get('frame_y', .5)), w, h)]
    inputs, filters, label = RC.overlay(note, pngs, 1, 'base', w, h)
    graph += filters
    cmd = ['ffmpeg', '-v', 'error', '-y', '-filter_complex_threads', '4', '-i', path] + inputs
    cmd += ['-filter_complex', ';'.join(graph), '-map', '['+label+']', '-map', '0:a:0',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-pix_fmt', 'yuv420p',
            '-c:a', 'copy', '-frames:v', str(nf), '-t', '%.8f' % (nf/30)]
    return cached(dest, cmd, w*h*3*nf)
