"""AI LARP pairs, variants, and successful-build allowances."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
import os
import re
import subprocess

import manifest as M
import paths
import tutorial_libraries as TL


FORMAT = 'ai_larp'
# Keep the retired split key readable in history and stale requests.
SUBFORMATS = ('split', 'tutorial')
TUTORIAL_REQUIRED = 'Every AI LARP video needs a tutorial. Choose Split screen + tutorial.'
EXTS = TL.EXTENSIONS
ORIGINAL = re.compile(r'^larp-(\d+)\.(mp4|mov|m4v|webm|mkv)$', re.I)
AI = re.compile(r'^larp-(\d+)-ai-(\d+)\.(mp4|mov|m4v|webm|mkv)$', re.I)


def folder(role):
    if role == 'tutorial':
        return TL.folder_for(FORMAT)
    if role not in ('originals', 'ai'):
        raise ValueError('Choose an AI LARP asset folder.')
    return paths.asset(FORMAT + '/' + role)


def _names(root):
    try:
        return sorted(n for n in os.listdir(root) if not n.startswith('.') and
                      n.lower().endswith(EXTS) and os.path.isfile(os.path.join(root, n)))
    except FileNotFoundError:
        return []


@lru_cache(maxsize=2048)
def _hash_stamped(path, size, mtime_ns, ctime_ns):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    info = os.stat(path)
    if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (size, mtime_ns, ctime_ns):
        raise ValueError('This clip changed while it was being read: ' + os.path.basename(path))
    return digest.hexdigest()


def fingerprint(path):
    info = os.stat(path)
    return _hash_stamped(os.path.realpath(path), info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=2048)
def _probe_stamped(path, size, mtime_ns, ctime_ns):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,width,height,duration', '-of', 'json', path],
        capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('Could not read video: ' + os.path.basename(path))
    try:
        data = json.loads(result.stdout)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        seconds = float(video.get('duration') or data['format']['duration'])
        if not math.isfinite(seconds) or seconds <= 0 or int(video['width']) <= 0 or int(video['height']) <= 0:
            raise ValueError()
        audio = any(s['codec_type'] == 'audio' for s in data['streams'])
    except (KeyError, ValueError, TypeError, StopIteration):
        raise ValueError('Could not read video: ' + os.path.basename(path))
    return {'seconds': seconds, 'width': int(video['width']),
            'height': int(video['height']), 'audio': audio}


def inspect(path):
    info = os.stat(path)
    return dict(_probe_stamped(os.path.realpath(path), info.st_size, info.st_mtime_ns,
                               info.st_ctime_ns), id=fingerprint(path))


def _asset(role, name, library=None):
    root = TL.folder(library) if role == 'tutorial' and library else folder(role)
    if (not isinstance(name, str) or not name or name.startswith('.') or
            os.path.basename(name) != name or not name.lower().endswith(EXTS)):
        raise ValueError('Choose a clip from its AI LARP folder.')
    path = os.path.join(root, name)
    if os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) != os.path.realpath(root):
        raise ValueError('Clip must stay inside its AI LARP folder.')
    return path


def _entry(role, name, library=None):
    path = _asset(role, name, library)
    return dict(name=name, **inspect(path),
                **({'library': library} if library else {}))


def _used(rows):
    used = set()
    for row in rows:
        if row.get('format') != FORMAT or row.get('status') != 'ok' or row.get('repost_root'):
            continue
        try:
            recipe = json.loads(row.get('reaction_recipe') or '')
            if (recipe.get('format') != FORMAT or recipe.get('subformat') not in SUBFORMATS or
                    not recipe['original']['id'] or not recipe['ai']['id']):
                raise ValueError()
            if recipe['subformat'] == 'tutorial' and not recipe['tutorial']['id']:
                raise ValueError()
            used.add((recipe['original']['id'], recipe['ai']['id'],
                      recipe['subformat'],
                      bool(recipe['ai_on_top']), bool(recipe['mirror']),
                      bool(recipe.get('captions', False))))
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError('AI LARP build history is unreadable. Restore its saved recipe before building.')
    return used


def _sources():
    originals = {}
    for name in _names(folder('originals')):
        match = ORIGINAL.fullmatch(name)
        if match:
            originals.setdefault(match.group(1), []).append(name)
    ai = {}
    for name in _names(folder('ai')):
        match = AI.fullmatch(name)
        if match:
            ai.setdefault(match.group(1), []).append(name)
    pairs = []
    original_rows = []
    for number, names in sorted(originals.items(), key=lambda item: int(item[0])):
        if len(names) != 1:
            raise ValueError('Two originals have the same AI LARP number. Remove one duplicate.')
        original = _entry('originals', names[0])
        if not original['audio']:
            raise ValueError('The original clip needs sound: ' + names[0])
        variants = []
        seen = set()
        for name in ai.get(number, []):
            item = _entry('ai', name)
            if min(original['seconds'], item['seconds']) < 2 / 30:
                raise ValueError('This original and AI clip pair is too short: ' + name)
            if item['id'] in seen:
                continue
            seen.add(item['id'])
            variants.append(item)
            pairs.append((original, item))
        original_rows.append(dict(original=original, ai=variants))
    return pairs, original_rows


def _tutorials():
    library = TL.library_for(FORMAT)
    names = TL.eligible_names(FORMAT, _names(TL.folder(library)))
    entries = [_entry('tutorial', name, library) for name in names]
    for item in entries:
        if not item['audio']:
            raise ValueError('The AI LARP tutorial needs sound: ' + item['name'])
        if item['seconds'] < 2 / 30:
            raise ValueError('The AI LARP tutorial is too short: ' + item['name'])
    return entries, library


def _choices(rows=None):
    rows = M.read_rows() if rows is None else rows
    used = _used(rows)
    pairs, original_rows = _sources()
    try:
        tutorials, library = _tutorials()
        tutorial_error = ''
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        tutorials, library, tutorial_error = [], TL.library_for(FORMAT), str(error)
    choices = {sub: [] for sub in SUBFORMATS}
    for pair_index, (original, ai) in enumerate(pairs):
        if not tutorials:
            continue
        for layout_index, (ai_on_top, mirror) in enumerate(
                ((True, False), (True, True))):
            for captions in (False, True):
                key = (original['id'], ai['id'], 'tutorial', ai_on_top, mirror, captions)
                if key not in used:
                    tutorial = tutorials[(pair_index * 4 + layout_index) % len(tutorials)]
                    choices['tutorial'].append(dict(format=FORMAT, subformat='tutorial',
                        original=original, ai=ai, tutorial=tutorial,
                        ai_on_top=ai_on_top, mirror=mirror, captions=captions))
    return choices, original_rows, tutorials, library, pairs, tutorial_error


def public_state():
    try:
        choices, originals, tutorials, library, pairs, tutorial_error = _choices()
        import ai_larp_music as MUSIC
        songs = MUSIC.inventory()
        left = {sub: len(choices[sub]) for sub in SUBFORMATS}
        missing_pair = 'Add an original and a matching AI version.'
        reasons = {
            'split': TUTORIAL_REQUIRED,
            'tutorial': tutorial_error if tutorial_error else missing_pair if not pairs else
                        'Assign an AI LARP tutorial to this Director content.' if not tutorials else
                        'All tutorial layouts have been made.',
        }
        reason = reasons['tutorial']
        return dict(ok=True, left=sum(left.values()), subformats=left,
                    originals=originals, tutorials=tutorials, tutorials_library=library, music=songs,
                    subformat_reasons=reasons, reason=reason if not any(left.values()) else '')
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return dict(ok=False, left=0, subformats={sub: 0 for sub in SUBFORMATS},
                    originals=[], tutorials=[], subformat_reasons={sub: str(error)[:300] for sub in SUBFORMATS},
                    reason=str(error)[:300])


def _variety_keys(recipe):
    return (recipe['original']['id'], recipe['ai']['id'],
            (recipe['original']['id'], recipe['ai']['id']),
            bool(recipe.get('captions')), bool(recipe['mirror']))


def _balanced_choices(choices, count, history, planned=()):
    # Spread source footage first, then exhaust the earliest unused layout tier.
    # Captions vary fastest, then mirroring. AI always stays above the original.
    batch = [Counter() for _ in range(3)]
    past = [Counter() for _ in range(3)]
    for recipe in planned:
        for counter, key in zip(batch, _variety_keys(recipe)):
            counter[key] += 1
    for original, ai, _subformat, _top, _mirror, _captions in history:
        for counter, key in zip(past, (original, ai, (original, ai))):
            counter[key] += 1

    def rank(recipe):
        keys = _variety_keys(recipe)
        source = tuple(counter[key] for counter, key in zip(batch, keys))
        source_history = tuple(counter[key] for counter, key in zip(past, keys))
        return (source, source_history, keys[4], keys[3],
                recipe['original']['name'], recipe['ai']['name'],
                (recipe.get('tutorial') or {}).get('name', ''))

    remaining, out = list(choices), []
    while len(out) < count:
        choice = min(remaining, key=rank)
        remaining.remove(choice)
        for counter, key in zip(batch, _variety_keys(choice)):
            counter[key] += 1
        out.append(choice)
    return out


def select(subformat, count, planned=()):
    if subformat == 'split':
        if count:
            raise ValueError(TUTORIAL_REQUIRED)
        return []
    if subformat not in SUBFORMATS:
        raise ValueError('Choose an AI LARP version.')
    rows = M.read_rows()
    all_choices, _originals, _tutorials, _library, _pairs, tutorial_error = _choices(rows)
    if subformat == 'tutorial' and tutorial_error:
        raise ValueError(tutorial_error)
    choices = all_choices[subformat]
    if count > len(choices):
        raise ValueError('AI LARP availability changed. Refresh Builder and try again.')
    return _balanced_choices(choices, count, _used(M.all_rows(rows)), planned)


def require_current_layout(recipe):
    if recipe.get('subformat') != 'tutorial' or not recipe.get('tutorial'):
        raise ValueError(TUTORIAL_REQUIRED)
    if recipe.get('ai_on_top') is not True:
        raise ValueError('AI LARP requires AI on top and original below. Refresh Builder.')


def validate_current(recipe, rows=None):
    music = recipe.get('music')
    if music:
        import ai_larp_music as MUSIC
        if fingerprint(MUSIC.source(music['name'])) != music['id']:
            raise ValueError('An AI LARP song changed while building: ' + music['name'])
    require_current_layout(recipe)
    for role in ('original', 'ai', 'tutorial'):
        item = recipe.get(role)
        if not item:
            continue
        asset_role = {'original': 'originals', 'ai': 'ai', 'tutorial': 'tutorial'}[role]
        if fingerprint(_asset(asset_role, item['name'], item.get('library'))) != item['id']:
            raise ValueError('An AI LARP source changed while building: ' + item['name'])
    if recipe['subformat'] == 'tutorial':
        if TL.library_for(FORMAT) != recipe['tutorial']['library']:
            raise ValueError('The AI LARP tutorial folder changed. Build again from Builder.')
        names = TL.eligible_names(FORMAT, [recipe['tutorial']['name']])
        if recipe['tutorial']['name'] not in names:
            raise ValueError('The tutorial is no longer assigned to this content type.')
    key = (recipe['original']['id'], recipe['ai']['id'], recipe['subformat'],
           recipe['ai_on_top'], recipe['mirror'], bool(recipe.get('captions', False)))
    if key in _used(M.read_rows() if rows is None else rows):
        raise ValueError('This AI LARP version was already made.')


def saved_recipe(recipe):
    return {key: ({k: v for k, v in value.items() if k in ('name', 'id', 'library', 'settings')}
                  if isinstance(value, dict) else value)
            for key, value in recipe.items()}
