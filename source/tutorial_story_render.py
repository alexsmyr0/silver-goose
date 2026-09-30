"""Three complete clips in order, with automatic captions on the ending only.

Speed is applied to source picture and sound before conversion to the output frame
rate. Captions are then timed against that prepared ending. Existing starting-scene
and tutorial text remains part of its source picture throughout.
"""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

import encode as E
import openart_repurpose as RP
import reaction_captions as RC
import reaction_render_cache as FRC
from render_support import clip_frames
import video_encode as VE
import tutorial_story_music as MUSIC

FPS = 30
ROLES = ('start', 'tutorial', 'ending')


def _source(asset):
    if not asset.get('path'):
        from tutorial_story import asset_path
        return asset_path(asset)
    path = os.fspath(asset['path'])
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != asset['id']:
        raise ValueError('This ingredient changed: ' + asset['name'])
    return path


def _number(value, name, low, high):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(name + ' is not a valid number.')
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(name + ' is outside the supported range.')
    return result


def _settings(asset):
    duration = _number(asset['seconds'], 'Clip length', 2 / FPS, 86400)
    saved = asset.get('settings') or {}
    settings = dict(start=_number(saved.get('start', 0), 'Start', 0, duration),
                    end=_number(saved.get('end', duration), 'End', 0, duration),
                    gain_db=_number(saved.get('gain_db', 0), 'Volume', -60, 12),
                    frame_scale=_number(saved.get('frame_scale', 1), 'Zoom', 1, 3),
                    frame_x=_number(saved.get('frame_x', .5), 'Framing', 0, 1),
                    frame_y=_number(saved.get('frame_y', .5), 'Framing', 0, 1))
    if settings['end'] - settings['start'] < 2 / FPS:
        raise ValueError('Keep at least two frames in each clip.')
    return settings


def _variation(recipe, sources):
    saved = recipe.get('variation') or {}
    mark = saved.get('mark') or RP.NORMAL_MARK
    look = saved.get('look') or 'natural'
    speed = _number(str(saved.get('speed', '1.00x')).rstrip('x'), 'Speed', .5, 2)
    if mark not in RP.marks() or look not in RP.LOOK_NAMES:
        raise ValueError('Choose one of the regular OpenArt variations.')
    for source in sources.values():
        if not any(abs(speed - value) < 1e-8 for value in RP.speeds_for(E.clip_fps(source), FPS)):
            raise ValueError('This speed would repeat frames in one of the clips. Make a fresh preview.')
    return dict(mark=mark, look=look, speed=RP.speed_key(speed)), speed


def _prepare(asset, source, settings, speed, cache, w, h):
    from media_source import ensure_sdr
    source = ensure_sdr(source)
    nf = clip_frames((settings['end'] - settings['start']) / speed, FPS)
    stat = os.stat(source)
    identity = FRC.key([asset['id'], stat.st_size, stat.st_mtime_ns,
                        settings, speed, w, h, 'tutorial-story-source-1'])
    dest = FRC.root(cache) / (identity + '.mp4')
    vf = ('trim=start=%.8f:end=%.8f,setpts=(PTS-STARTPTS)/%.8f,fps=%d,'
          'scale=%d:%d:force_original_aspect_ratio=decrease,'
          'pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,'
          'tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame=%d,settb=1/%d,setpts=N'
          % (settings['start'], settings['end'], speed, FPS, w, h, w, h, nf, FPS))
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', source]
    if asset.get('audio'):
        # atempo needs a short trailing analysis window to retain the final sound.
        # Feed silence into that window, then cut back to the exact output samples.
        # At normal speed there is no reason to run a tempo processor at all.
        tempo = (',apad=pad_dur=0.1,atempo=%.8f' % speed) if speed != 1 else ''
        af = ('atrim=start=%.8f:end=%.8f,asetpts=PTS-STARTPTS,'
              'volume=%.8f,aresample=%d%s,apad,atrim=end_sample=%d,'
              'aformat=sample_rates=%d:channel_layouts=stereo'
              % (settings['start'], settings['end'], 10 ** (settings['gain_db'] / 20),
                 E.AUDIO_RATE, tempo, nf * E.AUDIO_RATE // FPS, E.AUDIO_RATE))
        cmd += ['-map', '0:v:0', '-map', '0:a:0', '-af', af]
    else:
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=%d:cl=stereo' % E.AUDIO_RATE,
                '-map', '0:v:0', '-map', '1:a:0']
    cmd += ['-vf', vf, '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0',
            '-pix_fmt', 'yuv420p'] + E.audio_args()
    cmd += ['-t', '%.8f' % (nf / FPS), '-movflags', '+faststart']
    return FRC.cached(dest, cmd, estimated_bytes=w * h * 3 * nf), nf, identity


def _framing(index, settings, label, w, h):
    cw = max(2, int(w / settings['frame_scale']) // 2 * 2)
    ch = max(2, int(h / settings['frame_scale']) // 2 * 2)
    return ('[%d:v]crop=%d:%d:%d:%d,scale=%d:%d,setsar=1,format=yuv420p[%s]'
            % (index, cw, ch, round((w - cw) * settings['frame_x']),
               round((h - ch) * settings['frame_y']), w, h, label))


def _check_output(path, expected_frames):
    probe = json.loads(E.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                              '-show_format', '-of', 'json', path]))
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    duration = float(probe['format']['duration'])
    if int(video.get('nb_read_frames') or 0) != expected_frames or abs(duration - expected_frames / FPS) > .12:
        raise RuntimeError('The output length did not match the selected clips.')
    if int(audio.get('sample_rate') or 0) != E.AUDIO_RATE or int(audio.get('channels') or 0) != 2:
        raise RuntimeError('The output sound did not match the required audio format.')
    return duration


def build_one(recipe, out, cache=None, w=E.W, h=E.H):
    """Render an existing recipe without spending uses or exposing a partial output."""
    if cache is None:
        import paths
        cache = os.path.join(paths.WORK, 'tutorial-story-cache')
    assets = recipe.get('assets') or recipe
    assets = {role: assets[role] for role in ROLES}
    if not assets['ending'].get('audio'):
        raise ValueError('The final talking clip has no sound to caption.')
    sources = {role: _source(asset) for role, asset in assets.items()}
    music = recipe.get('music')
    music_source = _source(music) if music else None
    music_settings = MUSIC.validate(music.get('settings') or {},
                                    E.duration(music_source)) if music else None
    settings = {role: _settings(asset) for role, asset in assets.items()}
    variation, speed = _variation(recipe, sources)
    out = os.path.abspath(out)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    from storage_guard import require_space
    require_space(Path(out).parent)
    temp = str(Path(out).with_name('.tutorial-story-' + uuid.uuid4().hex + '.mp4'))
    try:
        with FRC.session(cache):
            prepared = {role: _prepare(asset, sources[role], settings[role], speed, cache, w, h)
                        for role, asset in assets.items()}
            path, nf, identity = prepared['ending']
            saved = recipe.get('captions')
            if saved and saved.get('source') not in (None, identity):
                raise ValueError('The ending or its speed changed. Make a fresh preview for its captions.')
            captions, pngs = RC.prepare(path, cache, nf / FPS, saved)
            captions['source'] = identity
            path = FRC.ending(path, nf, settings['ending'], captions, pngs, cache, w, h)
            prepared['ending'] = path, nf, identity
            cmd = ['ffmpeg', '-v', 'error', '-y', '-filter_complex_threads', '4']
            graph, inputs, segments, cursor = [], [], [], 0
            for index, role in enumerate(ROLES):
                path, nf, _ = prepared[role]
                cmd += ['-i', path]
                graph.append(('[%d:v]null[v%d]' % (index, index)) if role == 'ending'
                             else _framing(index, settings[role], 'v%d' % index, w, h))
                # A decoded AAC packet can include padding beyond its declared duration.
                # Exact sample trims prevent that padding shifting the next picture join.
                graph.append('[%d:a]atrim=end_sample=%d,asetpts=PTS-STARTPTS[a%d]'
                             % (index, nf * E.AUDIO_RATE // FPS, index))
                inputs += ['[v%d][a%d]' % (index, index)]
                segments.append(dict(role=role, start_frame=cursor, frames=nf,
                                     start=cursor / FPS, duration=nf / FPS,
                                     source_start=settings[role]['start'],
                                     source_end=settings[role]['end'], speed=speed))
                cursor += nf
            graph.append(''.join(inputs) + 'concat=n=3:v=1:a=1[cv][ca]')
            tail = RP.tail_vf(variation['mark'], variation['look'], w, h)
            graph.append('[cv]settb=1/%d,setpts=N,%s,format=yuv420p[v]' % (FPS, tail or 'null'))
            if music:
                # Loop the recording continuously through both later clips. Delay in
                # samples follows the prepared opening, including trims and speed.
                cmd += ['-stream_loop', '-1', '-i', music_source]
                delay = prepared['start'][1] * E.AUDIO_RATE // FPS
                remaining = (cursor - prepared['start'][1]) * E.AUDIO_RATE // FPS
                graph.append('[3:a]atrim=start=%.8f,asetpts=PTS-STARTPTS,aresample=%d,'
                             'aformat=channel_layouts=stereo,volume=%.8f,'
                             'atrim=end_sample=%d,adelay=%dS:all=1[music]'
                             % (music_settings['start'], E.AUDIO_RATE,
                                10 ** (music_settings['gain_db'] / 20), remaining, delay))
                graph.append('[ca][music]amix=inputs=2:duration=first:normalize=0,'
                             'alimiter=limit=0.98:level=false:latency=true,aresample=%d[a]'
                             % E.AUDIO_RATE)
            else:
                graph.append('[ca]aresample=%d[a]' % E.AUDIO_RATE)
            cmd += ['-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[a]',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p']
            cmd += E.audio_args() + ['-frames:v', str(cursor), '-t', '%.8f' % (cursor / FPS),
                    '-map_metadata', '-1', '-movflags', '+faststart+use_metadata_tags',
                    '-metadata', 'creation_time=' + datetime.datetime.now(datetime.timezone.utc).isoformat(), temp]
            VE.run(cmd, runner=E.run, label='Bottle spin')
            measured = _check_output(temp, cursor)
            os.replace(temp, out)
            return dict(duration=cursor / FPS, measured_duration=measured, fps=FPS,
                        start_frames=prepared['start'][1], tutorial_frames=prepared['tutorial'][1],
                        ending_frames=prepared['ending'][1], segments=segments,
                        captions=captions, variation=variation)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
