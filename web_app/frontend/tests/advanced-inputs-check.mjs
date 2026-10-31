import assert from 'node:assert/strict';
import { compensationInputs } from '../src/advancedInputs.ts';

const defaults = { Rpullup: 1, Copto: 1, C2: 1 };
const desktop = compensationInputs({ vars: { Rpullup: { v: 20, u: 'k' }, Copto: { v: 2, u: 'n' }, C2: { v: 0, u: 'n' } } }, defaults, 'desktop');
assert.equal(desktop.values.Rpullup, 20000);
assert.equal(desktop.values.Copto, 2e-9);
assert.equal(desktop.values.C2, 0);
assert.equal(desktop.warnings.length, 0);

const explicitlySI = compensationInputs({ encoding: 'si', vars: { Rpullup: { v: 20000, u: 'k' }, Copto: { v: 2e-9, u: 'n' } } }, defaults, 'si');
assert.equal(explicitlySI.values.Rpullup, 20000);
assert.equal(explicitlySI.values.Copto, 2e-9);

const notGuessed = compensationInputs({ vars: { Rpullup: { v: 20000, u: 'k' } } }, defaults, 'desktop');
assert.equal(notGuessed.values.Rpullup, 20000000);
const badPrefix = compensationInputs({ vars: { Copto: { v: 2, u: 'invalid' } } }, defaults, 'desktop');
assert.equal(badPrefix.values.Copto, 1);
assert.equal(badPrefix.warnings.length, 1);
assert.equal(compensationInputs({ vars: { Rpullup: { v: null, u: '' } } }, defaults, 'desktop').values.Rpullup, 1);
assert.equal(compensationInputs({ vars: { Rpullup: { v: 20, u: '' }, unsupported: { v: 50, u: '' } } }, defaults, 'desktop').values.unsupported, undefined);
console.log('PASS: compensation display-prefix / explicit-SI interpretation, zero branches, invalid values, and no magnitude guessing.');
