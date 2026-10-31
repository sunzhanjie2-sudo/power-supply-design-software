"""Configuration decoding shared by GUI startup and headless calculations."""
import json
from pathlib import Path

UNITS = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'c': 1e-2,
         'k': 1e3, 'M': 1e6, 'G': 1e9, '': 1.0}
DEFAULT_CONFIG = 'examples/40W_CCM_FLYBACK.json'


def read_default_config():
    return json.loads((Path(__file__).parent / DEFAULT_CONFIG).read_text(encoding='utf-8'))


def decode_config(config):
    """Display units -> SI; metadata stays outside the numerical input dict."""
    result = {}
    aliases = {'rcd_K': 'K', 'rcd_Kc': 'Kc', 'rcd_dC': 'dC'}
    for key, entry in config.items():
        if key.startswith('__'):
            continue
        if isinstance(entry, dict) and 'v' in entry:
            value = entry['v']
            if not isinstance(value, (str, bool)):
                unit = entry.get('u', '')
                if unit not in UNITS:
                    raise ValueError(f'{key}: unknown unit prefix {unit!r}')
                value = float(value) * UNITS[unit]
        else:
            value = entry
        if key in ('topology', 'control_mode') and isinstance(value, str):
            value = value.split(' (', 1)[0]
            if key == 'topology' and value == 'FLYBACK-QR':
                value = 'QR-FLYBACK'
        result[aliases.get(key, key)] = value
    return result
