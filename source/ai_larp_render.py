"""Render AI LARP's 720x1280 split screen and required full-screen tutorial."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

import ai_larp as L
import render_support as RS
import video_encode as VE


WIDTH = 720
HEIGHT = 1280
FPS = 30
PANEL_HEIGHT = 444
CAPTION_BAND_HEIGHT = 72
LABEL_SIZE = 34
# CapCut's saved Classic stroke is 0.06 em, drawn outside the white fill.
LABEL_OUTLINE_EM = 0.06
LOGO = Path(__file__).resolve().parent / 'branding' / 'openart_logo_ai_larp.png'
FONT_CANDIDATES = (
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
)


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    raise ValueError('AI LARP needs an Arial or DejaVu Sans bold font.')


def _layout(captioned):
    gap = CAPTION_BAND_HEIGHT if captioned else 0
    top = (HEIGHT - 2 * PANEL_HEIGHT - gap) // 2
    return top, top + PANEL_HEIGHT, top + PANEL_HEIGHT + gap


def _overlay(path, ai_on_top, captioned=False):
    top_y, _, bottom_y = _layout(captioned)
    layer = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    with Image.open(LOGO) as source:
        logo = source.convert('RGBA').resize((220, 101), Image.Resampling.LANCZOS)
    title_y = top_y - 49
    layer.alpha_composite(logo, (250, (title_y - 101) // 2))
    title = 'AI LARP IS HERE'
    font = _font(48)
    box = draw.textbbox((0, 0), title, font=font)
    draw.text(((WIDTH - (box[2] - box[0])) / 2, title_y - 3 - box[1]), title,
              fill='white', font=font)
    # Supersample to retain the fractional outline thickness at this output size.
    import paths
    scale = 4
    label_font = ImageFont.truetype(RS.ensure_font(paths.ASSETS), LABEL_SIZE * scale)
    labels = Image.new('RGBA', (WIDTH * scale, HEIGHT * scale))
    label_draw = ImageDraw.Draw(labels)
    for top, y in ((True, top_y), (False, bottom_y)):
        label = 'AI' if top == ai_on_top else 'original'
        # Baseline follows its panel, including when captions change the layout.
        label_draw.text((23 * scale, (y + PANEL_HEIGHT - 22) * scale),
                        label, anchor='ls', font=label_font, fill='white',
                        stroke_width=round(LABEL_SIZE * LABEL_OUTLINE_EM * scale),
                        stroke_fill='black')
    layer.alpha_composite(labels.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS))
    layer.save(path)


def _countdown(scratch, split_frames, captioned, first_input, base_label):
    footer_y = _layout(captioned)[2] + PANEL_HEIGHT
    footer_height = HEIGHT - footer_y
    font = _font(42)
    inputs, graph, label = [], [], base_label
    for remaining in (3, 2, 1):
        start = max(0, split_frames - remaining * FPS)
        end = split_frames - (remaining - 1) * FPS
        if end <= start:
            continue
        text = f'tutorial in {remaining}'
        band = Image.new('RGBA', (WIDTH, footer_height))
        draw = ImageDraw.Draw(band)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((WIDTH - box[0] - box[2]) / 2,
                   16 - box[1]),
                  text, font=font, fill='white')
        png = os.path.join(scratch, f'countdown-{remaining}.png')
        band.save(png)
        index = first_input + len(inputs) // 2
        inputs += ['-i', png]
        next_label = f'countdown{remaining}'
        # Count output frames backwards from the measured tutorial cut, without extending clips.
        graph.append(f"[{label}][{index}:v]overlay=0:{footer_y}:"
                     f"enable='gte(n,{start})*lt(n,{end})'[{next_label}]")
        label = next_label
    return inputs, graph, label


def _panel(index, label, mirror, frames):
    parts = [f'[{index}:v]']
    if mirror:
        parts.append('hflip,')
    parts.append(f'fps=30,scale={WIDTH}:{PANEL_HEIGHT}:force_original_aspect_ratio=increase,'
                 f'crop={WIDTH}:{PANEL_HEIGHT}:(iw-ow)/2:(ih-oh)/2,setsar=1,format=yuv420p,'
                 f'trim=end_frame={frames},settb=1/30,setpts=N[{label}]')
    return ''.join(parts)


def _full_tutorial(index, frames):
    return (f'[{index}:v]fps=30,scale=720:1280:force_original_aspect_ratio=increase,'
            'crop=720:1280,setsar=1,format=yuv420p,'
            f'trim=end_frame={frames},settb=1/30,setpts=N[tutorialv]')


def _audio(index, label, frames):
    samples = frames * 1600  # 48 kHz / 30 fps
    return (f'[{index}:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,'
            f'apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS[{label}]')


def _run(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=1800)


def _verify(path, frames):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
        'stream=codec_type,width,height,nb_read_frames:format=duration', '-of', 'json', path],
        capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('The AI LARP output could not be read.')
    try:
        data = json.loads(result.stdout)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
        actual_frames = int(video['nb_read_frames'])
        if (int(video['width']), int(video['height'])) != (WIDTH, HEIGHT) or not audio:
            raise ValueError()
        if actual_frames != frames:
            raise ValueError()
        return float(data['format']['duration'])
    except (KeyError, TypeError, ValueError, StopIteration):
        raise RuntimeError('The AI LARP output has the wrong picture, sound or length.')


def build_one(recipe, output):
    L.require_current_layout(recipe)
    original = L._asset('originals', recipe['original']['name'])
    ai = L._asset('ai', recipe['ai']['name'])
    if not recipe['original']['audio']:
        raise ValueError('The original clip needs sound for AI LARP.')
    split_frames = int(min(recipe['original']['seconds'], recipe['ai']['seconds']) * FPS)
    if split_frames < 2:
        raise ValueError('The original and AI clips must overlap for at least two frames.')
    tutorial = recipe['tutorial']
    if not tutorial['audio']:
        raise ValueError('The tutorial needs its own sound.')
    tutorial_frames = int(tutorial['seconds'] * FPS)
    if tutorial_frames < 2:
        raise ValueError('The tutorial is too short.')
    with tempfile.TemporaryDirectory(prefix='ai-larp-') as scratch:
        captioned = bool(recipe.get('captions'))
        top_y, band_y, _ = _layout(captioned)
        chunks, caption_pngs = [], []
        if captioned:
            import ai_larp_captions as LC
            chunks, caption_pngs = LC.prepare(original, split_frames, scratch,
                                              CAPTION_BAND_HEIGHT)
        overlay = os.path.join(scratch, 'overlay.png')
        _overlay(overlay, recipe['ai_on_top'], captioned)
        inputs = ['-i', original, '-i', ai, '-i', overlay]
        inputs += ['-i', L._asset('tutorial', tutorial['name'], tutorial['library'])]
        top, bottom = 1, 0
        graph = [
            _panel(top, 'top', recipe['mirror'], split_frames),
            _panel(bottom, 'bottom', recipe['mirror'], split_frames),
        ]
        if captioned:
            graph += [f'color=c=black:s=720x{CAPTION_BAND_HEIGHT}:r=30,trim=end_frame={split_frames},'
                      'settb=1/30,setpts=N[gap]',
                      '[top][gap][bottom]vstack=inputs=3[stack]']
        else:
            graph += ['[top][bottom]vstack=inputs=2[stack]']
        graph += [
            f'[stack]pad=720:1280:0:{top_y}:black[canvas]',
            '[canvas][2:v]overlay=0:0:repeatlast=1:shortest=0[splitbase]',
        ]
        label = 'splitbase'
        if captioned:
            caption_inputs, caption_graph, label = LC.overlays(
                chunks, caption_pngs, 4, label, band_y)
            inputs += caption_inputs
            graph += caption_graph
        countdown_inputs, countdown_graph, label = _countdown(
            scratch, split_frames, captioned, inputs.count('-i'), label)
        inputs += countdown_inputs
        graph += countdown_graph
        music = recipe.get('music')
        music_index = len([x for x in inputs if x == '-i'])
        if music:
            import ai_larp_music as MUSIC
            settings = MUSIC.validate(music['settings'], music['seconds'])
            inputs += ['-stream_loop', '-1', '-i', MUSIC.source(music['name'])]
        graph += [f'[{label}]format=yuv420p,trim=end_frame={split_frames},'
                  'settb=1/30,setpts=N[splitv]',
                  _audio(0, 'splita', split_frames)]
        total_frames = split_frames + tutorial_frames
        audio_label = 'voice' if music else 'a'
        graph += [_full_tutorial(3, tutorial_frames), _audio(3, 'tutoriala', tutorial_frames),
                  f'[splitv][splita][tutorialv][tutoriala]concat=n=2:v=1:a=1[v][{audio_label}]']
        if music:
            # Mix one continuous song after the join, preserving both clips' own audio.
            graph += [f'[{music_index}:a]atrim=start={settings["start"]:.8f},'
                      'asetpts=PTS-STARTPTS,aresample=48000,'
                      'aformat=sample_rates=48000:channel_layouts=stereo,'
                      f'volume={10 ** (settings["gain_db"] / 20):.8f},'
                      f'atrim=end_sample={total_frames * 1600}[music]',
                      '[voice][music]amix=inputs=2:duration=first:normalize=0,'
                      'alimiter=limit=0.98:level=false:latency=true[a]']
        command = ['ffmpeg', '-hide_banner', '-v', 'error', '-y'] + inputs + [
            '-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
            '-movflags', '+faststart', output]
        result = VE.run(command, runner=_run, label='AI LARP')
        if result.returncode:
            raise RuntimeError('AI LARP rendering failed: ' + (result.stderr or '')[-500:])
    return {'duration': _verify(output, total_frames), 'split_frames': split_frames,
            'tutorial_frames': tutorial_frames, 'total_frames': total_frames,
            'caption_chunks': len(chunks),
            'music': dict(name=music['name'], **settings) if music else None}
