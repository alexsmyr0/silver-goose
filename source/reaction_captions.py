"""Captions for the combined ending only; source stories/tutorials keep their own text.

Style comes from the user's CapCut 0917 (1) draft, matching the supplied settings
screenshots. Shared rendering and speech helpers remain the owners of glyphs/timing.
"""
import hashlib
import json
import os
import subprocess

import captions as C
import render_support as RS

STYLE = dict(font='Classic', font_size=11, scale=100, x=0, y=-914,
             transform_y=-0.4762640901771336, fill='#ffffff', outline='#000000',
             outline_em=0.06, bold=False, italic=False, underline=False,
             letter_spacing=0, line_spacing=0.02, shadow=False, background=False,
             animation=False, canvas=[1080, 1920])
FONT_SHA256 = 'f404cf5b44ae21071907df5aeb027d3c968a2b68b4108cf6ab158bff487e1159'
SIZE = 11 * 6.25
BASELINE = (1 - STYLE['transform_y']) * 960 + 0.288 * SIZE


def prepare(path, cache, duration, saved=None):
    """Transcribe the selected ending audio, never notes or another segment's speech."""
    if saved is not None:
        if saved.get('style') != STYLE:
            raise ValueError('This ending uses a different caption style. Make a fresh preview.')
        chunks = saved['chunks']
    else:
        chunks, error = C.caption_chunks(path, fps=30)
        if error:
            raise ValueError('Could not caption the End of video clip: ' + error)
    chunks = [dict(text=c['text'], start=max(0, c['start']), end=min(duration, c['end']))
              for c in chunks if c['text'].strip() and c['start'] < duration and c['end'] > 0]
    chunks = [c for c in chunks if c['end'] > c['start']]
    if not chunks:
        raise ValueError('No spoken words were found in the End of video clip. Check its sound.')
    font = C.font()
    with open(font, 'rb') as f:
        if hashlib.sha256(f.read()).hexdigest() != FONT_SHA256:
            raise ValueError('The Classic caption font differs from the saved reference.')
    note = dict(style=STYLE, chunks=chunks, role='ending')
    key = hashlib.sha256(json.dumps(note, sort_keys=True).encode()).hexdigest()
    root = os.path.join(cache, 'ending-captions-' + key)
    os.makedirs(root, exist_ok=True)
    pngs = [os.path.join(root, 'cap', 'c%04d.png' % i) for i in range(len(chunks))]
    if not all(os.path.isfile(p) for p in pngs):
        spec = dict(out_dir=root, font=font, chunks=chunks, caption_size=SIZE,
                    caption_baseline=BASELINE, caption_outline=STYLE['outline_em'] * 200)
        specpath = os.path.join(root, 'spec.json')
        with open(specpath, 'w') as f:
            json.dump(spec, f)
        result = subprocess.run([RS.ensure_renderer(), specpath], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Ending caption renderer failed: ' + result.stderr[-300:])
    return note, pngs


def overlay(note, pngs, first_input, base_label, w, h):
    """Attach captions to the ending stream before concatenation; they cannot reach hooks."""
    args, graph, label = [], [], base_label
    for i, (chunk, png) in enumerate(zip(note['chunks'], pngs)):
        args += ['-i', png]
        picture, output = 'endingcaption%d' % i, 'endingtext%d' % i
        graph.append('[%d:v]scale=%d:%d[%s]' % (first_input+i, w, h, picture))
        start, end = round(chunk['start']*30), round(chunk['end']*30)
        graph.append('[%s][%s]overlay=0:0:enable=\'gte(n,%d)*lt(n,%d)\'[%s]' %
                     (label, picture, start, max(start+1, end), output))
        label = output
    return args, graph, label
