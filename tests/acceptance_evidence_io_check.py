"""Bound evidence survives references; mutation, missing identity and bad ZIPs do not."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from acceptance_evidence_io import load_evidence, normalize_reference
from engineering_acceptance import input_fingerprint


class EvidenceIO(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'comparison.json'
        self.p=dict(V_in_min=20.,V_in_max=30.,L=50e-6)
        self.data=dict(schema='powerdesign-spice-comparison-2',
                       input_fingerprint=input_fingerprint(self.p),cases=[])
        self.path.write_text(json.dumps(self.data),encoding='utf-8')

    def tearDown(self):self.folder.cleanup()

    def test_reference_and_zip_member_own_exact_payload(self):
        ref, envelope=load_evidence(self.path)
        self.assertEqual(envelope['input_fingerprint'],input_fingerprint(self.p))
        self.assertEqual(normalize_reference(ref),ref)
        self.assertEqual(load_evidence(self.path,reference=ref)[1],envelope)
        zipped=self.path.with_suffix('.zip')
        with ZipFile(zipped,'w') as z:z.writestr('comparison.json',self.path.read_bytes())
        zipped_ref, zipped_envelope=load_evidence(zipped)
        self.assertEqual(zipped_ref['payload_sha256'],ref['payload_sha256'])
        self.assertEqual(zipped_envelope['evidence'],self.data)

    def test_mutation_unbound_and_invalid_records_rejected(self):
        ref,_=load_evidence(self.path)
        self.data['cases']=[dict(id='Vinmin',complete=False)]
        self.path.write_text(json.dumps(self.data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'已变化'):load_evidence(self.path,reference=ref)
        self.data.pop('input_fingerprint')
        self.path.write_text(json.dumps(self.data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'缺少输入指纹'):load_evidence(self.path)
        self.path.write_text('{"schema": NaN}',encoding='utf-8')
        with self.assertRaises(ValueError):load_evidence(self.path)

    def test_joint_adopted_hardware_owns_the_binding(self):
        adopted=dict(self.p,L=70e-6)
        joint=dict(schema='power-design.joint-simulation.v1',original_config=self.p,
            adopted_config=adopted,circuit=dict(evidence=self.data))
        self.path.write_text(json.dumps(dict(record=joint)),encoding='utf-8')
        _,envelope=load_evidence(self.path)
        self.assertEqual(envelope['input_fingerprint'],input_fingerprint(adopted))
        self.assertNotEqual(envelope['input_fingerprint'],input_fingerprint(self.p))


if __name__=='__main__':unittest.main(verbosity=2)
