"""Shared soundtrack settings and reproducible mixing for Hook Story."""
import hashlib
import math
import os

import paths

_CACHE = {}


def folder():
    return paths.asset('reaction/music')


def file_path(music):
    name = music.get('name', '')
    if not name or os.path.basename(name) != name:
        raise ValueError('Choose a song from the Reaction music folder.')
    path = os.path.join(folder(), name)
    if not os.path.isfile(path):
        raise ValueError('The Reaction song is missing: ' + name)
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    if key not in _CACHE:
        with open(path, 'rb') as source:
            _CACHE[key] = hashlib.file_digest(source, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(source.read()).hexdigest()
    if _CACHE[key] != music.get('id'):
        raise ValueError('The Reaction song changed. Restore the saved version before building.')
    return path


def settings(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('The Reaction music settings could not be read.')
    out = dict(value)
    out['enabled'] = bool(out.get('enabled', True))
    for name, default, low, high in [('song_start', 0, 0, 3600),
                                    ('offset', 0, -30, 30), ('gain_db', -18, -60, 0)]:
        try:
            n = float(out.get(name, default))
        except (TypeError, ValueError):
            raise ValueError('Music timing and volume must be numbers.')
        if not math.isfinite(n) or not low <= n <= high:
            raise ValueError('Music %s must be between %g and %g.' % (name, low, high))
        out[name] = n
    if out['song_start'] >= float(out.get('seconds', 0)):
        raise ValueError('The song start must be before the end of the recording.')
    out['entry'] = 'after_hook'
    file_path(out)
    return out


def mix(music, *, input_index, hook_end, duration, rate):
    """Keep the chosen song excerpt tied to the story ending, independently of its length."""
    entry = max(0, hook_end + music['offset'])
    remaining = duration - entry
    if remaining <= 0:
        raise ValueError('Music must start before the video ends.')
    delay = round(entry * rate)
    chain = ('[%d:a]atrim=start=%.8f,asetpts=PTS-STARTPTS,'
             'aresample=%d,aformat=channel_layouts=stereo,volume=%.8f,'
             'atrim=duration=%.8f,afade=t=in:d=0.02,'
             'afade=t=out:st=%.8f:d=%.8f,adelay=%dS:all=1[music];'
             '[ca][music]amix=inputs=2:duration=first:normalize=0,'
             'alimiter=limit=0.98:level=false:latency=true,aresample=%d[a]') % (
        input_index, music['song_start'], rate, 10**(music['gain_db']/20), remaining,
        max(0, remaining-.35), min(.35, remaining), delay, rate)
    return chain, dict(music, video_start=entry)
