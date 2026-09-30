"""AI LARP's shared songs and per-recording start/volume settings."""
import json
import os
from collections import Counter

import paths
from install_config import atomic_write_json
from ledger_lock import locked
from tutorial_story import inspect_music, SOUND_EXTS
from tutorial_story_music import validate


def store_path():
    return paths.data('ai_larp_music.json')


def folder():
    return paths.asset('ai_larp/music')


def source(name):
    if (not isinstance(name, str) or not name or name.startswith('.') or
            os.path.basename(name) != name or not name.lower().endswith(SOUND_EXTS)):
        raise ValueError('Choose a song from AI LARP Songs.')
    root = os.path.realpath(folder())
    path = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath((root, path)) != root:
        raise ValueError('The song must stay inside AI LARP Songs.')
    return path


def read():
    try:
        with open(store_path()) as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {'tracks': {}}
    if not isinstance(data, dict) or not isinstance(data.get('tracks'), dict):
        raise ValueError('AI LARP music settings could not be read. Restore the settings file.')
    return data


def inventory():
    settings = read()['tracks']
    try:
        names = sorted(os.listdir(folder()))
    except FileNotFoundError:
        return []
    out = []
    for name in names:
        if name.startswith('.') or not name.lower().endswith(SOUND_EXTS):
            continue
        info = inspect_music(source(name))
        out.append(dict(info, name=name, settings=validate(settings.get(info['id'], {}), info['seconds'])))
    return out


def save(name, value):
    info = inspect_music(source(name))
    settings = validate(value, info['seconds'])
    with locked(store_path()):
        data = read()
        previous = data['tracks'].get(info['id'], {})
        if not isinstance(previous, dict):
            raise ValueError('This song has unreadable settings. Restore the settings file.')
        data['tracks'][info['id']] = dict(previous, **settings)
        atomic_write_json(store_path(), data)
    return settings


def assign(recipes, rows):
    songs = inventory()
    if not songs:
        return recipes  # Existing installs with no songs retain voice-only builds.
    usage = Counter()
    for row in rows:
        if row.get('format') != 'ai_larp' or row.get('status') != 'ok' or row.get('repost_root'):
            continue
        recipe = json.loads(row.get('reaction_recipe') or '{}')
        music = recipe.get('music') or {}
        if music.get('id'):
            usage[music['id']] += 1
    for recipe in recipes:
        song = min(songs, key=lambda s: (usage[s['id']], s['name']))
        recipe['music'] = dict(song, settings=dict(song['settings']))
        usage[song['id']] += 1
    return recipes
