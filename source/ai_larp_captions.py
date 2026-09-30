"""Draw timed AI LARP captions in the black band between the two videos."""
import os

from PIL import Image

import captions as C


WIDTH = 720
CAPTION_PADDING = 8


def prepare(original, split_frames, scratch, band_height):
    chunks, error = C.caption_chunks(original, fps=30)
    if chunks is None:
        raise ValueError('Could not caption the original clip: ' + (error or 'transcription failed'))
    limit = split_frames / 30
    chunks = [dict(text=c['text'], start=max(0, c['start']), end=min(limit, c['end']))
              for c in chunks if c['text'].strip() and c['start'] < limit and c['end'] > 0]
    chunks = [c for c in chunks if c['end'] > c['start']]
    if not chunks:
        raise ValueError('No spoken words were found in the original clip.')

    pngs = C.draw(chunks, scratch, size=68.0, baseline=960.0)
    return chunks, _bands(pngs, scratch, band_height)


def _bands(pngs, scratch, band_height):
    # Use one crop and scale for the entire clip. Per-phrase ink bounds move
    # the baseline when letters gain ascenders/descenders, and can change size.
    bounds = []
    canvas = None
    for source in pngs:
        with Image.open(source) as image:
            if canvas is not None and image.size != canvas:
                raise ValueError('Caption images have inconsistent dimensions.')
            canvas = image.size
            box = image.convert('RGBA').getchannel('A').getbbox()
            if box is None:
                raise ValueError('Caption drawing produced no visible text.')
            bounds.append(box)
    top, bottom = min(b[1] for b in bounds), max(b[3] for b in bounds)
    scale = min(WIDTH / canvas[0],
                (band_height - 2 * CAPTION_PADDING) / (bottom - top))
    size = (max(1, round(canvas[0] * scale)), max(1, round((bottom - top) * scale)))
    offset = ((WIDTH - size[0]) // 2, (band_height - size[1]) // 2)
    cropped = []
    for i, source in enumerate(pngs):
        target = os.path.join(scratch, 'ai-larp-caption-%04d.png' % i)
        with Image.open(source) as image:
            strip = image.convert('RGBA').crop((0, top, canvas[0], bottom))
            strip = strip.resize(size, Image.Resampling.LANCZOS)
            band = Image.new('RGBA', (WIDTH, band_height))
            band.alpha_composite(strip, offset)
            band.save(target)
        cropped.append(target)
    return cropped


def overlays(chunks, pngs, first_input, base_label, band_y):
    inputs, graph, label = [], [], base_label
    for i, (chunk, png) in enumerate(zip(chunks, pngs)):
        inputs += ['-i', png]
        start = max(0, round(chunk['start'] * 30))
        end = max(start + 1, round(chunk['end'] * 30))
        next_label = 'larpcaption%d' % i
        graph.append("[%s][%d:v]overlay=0:%d:enable='gte(n,%d)*lt(n,%d)'[%s]" %
                     (label, first_input + i, band_y, start, end, next_label))
        label = next_label
    return inputs, graph, label
