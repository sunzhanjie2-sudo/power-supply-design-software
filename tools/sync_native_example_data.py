"""Refresh only embedded personal-TS example inputs, never numerical goldens.

Use --check to detect stale data or --write after reviewing examples/*.json.
The complete export_native_reference.py remains the explicit full model export.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def synchronize(data):
    from web_app.metadata import normalize_config, read_example, preview
    from isolated_outputs import RAIL_KEYS
    from design_engine.contracts import json_value
    result = copy.deepcopy(data)
    # Preserve the supported catalog: system-network examples are not single-
    # converter specifications and must not be normalized through this path.
    for name in data['examples']:
        result['examples'][name] = normalize_config(read_example(name))
    startup = copy.deepcopy(result['examples']['40W_CCM_FLYBACK.json'])
    startup.update(V_in_min=startup['V_in'], V_in_max=startup['V_in'], input_voltage_case='min')
    result['bootstrap']['spec'] = startup
    if data['bootstrap'].get('default_spec') == data['bootstrap']['spec']:
        result['bootstrap']['default_spec'] = copy.deepcopy(startup)
    result['bootstrap']['output_template'] = {key: copy.deepcopy(startup[key]) for key in RAIL_KEYS}
    result['bootstrap']['preview'] = preview(startup)
    isolated_defaults = dict(component_management={}, input_capacitors=None,
        output_capacitors=None, mos_miller_curve={}, mos_charge_curve={},
        mos_manual_events={}, diode_curves={}, device_curve_settings={})
    for key, value in isolated_defaults.items():
        result['defaults'][key] = value
    return json_value(result), set(isolated_defaults)


def protected(data, isolated_defaults):
    value = copy.deepcopy(data)
    value.pop('examples')
    for key in ('spec', 'default_spec', 'output_template', 'preview'):
        value['bootstrap'].pop(key, None)
    for key in isolated_defaults:
        value['defaults'].pop(key, None)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--write', action='store_true')
    parser.add_argument('--receipt', type=Path,
        default=ROOT/'artifacts/example-real-parts-20261108/native-data-sync.json')
    args = parser.parse_args()
    target = ROOT/'web_app/frontend/src/native_engine/reference-data.json'
    before_bytes = target.read_bytes()
    before = json.loads(before_bytes.decode('utf-8'))
    fixtures = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'tests/fixtures').glob('native*reference.json')}
    after, isolated_defaults = synchronize(before)
    protected_before = protected(before, isolated_defaults)
    protected_after = protected(after, isolated_defaults)
    if protected_before != protected_after:
        raise RuntimeError('Refusing to modify non-example metadata/model sources')
    stale = before != after
    if args.write and stale:
        target.write_text(json.dumps(after, ensure_ascii=False, indent=2, allow_nan=False)+'\n', 'utf-8')
    end_fixtures = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'tests/fixtures').glob('native*reference.json')}
    if fixtures != end_fixtures:
        raise RuntimeError('Historical fixture changed during data-only synchronization')
    receipt = dict(schema='power.native-example-data-sync/1', written=args.write,
        changed=stale, examples=list(after['examples']),
        example_sha256={name: hashlib.sha256((ROOT/'examples'/name).read_bytes()).hexdigest()
            for name in after['examples']},
        protected_subtrees_unchanged=True, protected_before_sha256=digest(protected_before),
        protected_after_sha256=digest(protected_after), fixtures_sha256=fixtures,
        old_reference_sha256=hashlib.sha256(before_bytes).hexdigest(),
        reference_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        refreshed_paths=['examples', 'bootstrap.spec', 'bootstrap.output_template', 'bootstrap.preview'],
        source_hashes_updated=False,
        scope='Personal TS input examples only; no company deployment, formulas or numerical reference regeneration')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps(dict(written=args.write, changed=stale, examples=len(after['examples']),
        protected_subtrees_unchanged=True, fixtures_unchanged=True), ensure_ascii=False))
    if args.check and stale:
        raise SystemExit('Embedded examples are stale; review and run --write')


if __name__ == '__main__':
    main()
