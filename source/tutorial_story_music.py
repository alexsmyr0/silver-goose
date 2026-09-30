"""Bottle spin's shared per-recording audio settings, saved by content identity."""
import json
import math

from install_config import atomic_write_json
from ledger_lock import locked


def store_path():
    import paths
    return paths.data('tutorial_story_music.json')


def read():
    try:
        with open(store_path()) as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {'tracks': {}}
    if not isinstance(data, dict) or not isinstance(data.get('tracks'), dict):
        raise ValueError('Bottle spin music settings could not be read. Restore the settings file.')
    return data


def validate(value, seconds):
    if not isinstance(value, dict):
        raise ValueError('Music settings must contain a start time and volume.')
    result = {}
    for key, default in (('start', 0), ('gain_db', -18)):
        try:
            result[key] = float(value.get(key, default))
        except (ValueError, TypeError):
            raise ValueError('Music start and volume must be numbers.')
        if not math.isfinite(result[key]):
            raise ValueError('Music start and volume must be finite numbers.')
    if not 0 <= result['start'] < seconds:
        raise ValueError('Start within the song, before its end.')
    if not -60 <= result['gain_db'] <= 0:
        raise ValueError('Music volume must be between -60 and 0 dB.')
    return result


def save(identity, value, seconds):
    settings = validate(value, seconds)
    path = store_path()
    with locked(path):
        data = read()
        previous = data['tracks'].get(identity, {})
        if not isinstance(previous, dict):
            raise ValueError('This song has unreadable settings. Restore the settings file.')
        data['tracks'][identity] = dict(previous, **settings)
        atomic_write_json(path, data)
    return settings
