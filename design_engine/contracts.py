"""Strict JSON boundary: no pickle, object repr, NaN or Infinity tokens."""
import hashlib
import json
import math


def json_value(value, diagnostics=None, path='$'):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if diagnostics is not None:
            diagnostics.append(dict(path=path, kind='nonfinite',
                                    value='NaN' if math.isnan(value) else '+Infinity' if value > 0 else '-Infinity'))
        return None
    if isinstance(value, complex):
        return {'real': json_value(value.real, diagnostics, path + '.real'),
                'imag': json_value(value.imag, diagnostics, path + '.imag')}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError(f'{path}: JSON object keys must be strings')
        return {key: json_value(child, diagnostics, path + '.' + key) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(child, diagnostics, f'{path}[{index}]') for index, child in enumerate(value)]
    if type(value).__module__.startswith('numpy'):
        if hasattr(value, 'tolist'):
            return json_value(value.tolist(), diagnostics, path)
        if hasattr(value, 'item'):
            return json_value(value.item(), diagnostics, path)
    raise TypeError(f'{path}: unsupported transport value {type(value).__name__}')


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()
