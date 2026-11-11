"""Pure unit tests: synthetic local/outbox evidence only. No external calls."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from crm_quality.make_orchestration import NAMESPACE, construct, digest
from crm_quality.a11_delivery_reconciliation import (
    ReconciliationError, _record, check_remote, local_state, reconcile, SCHEMA,
)

UUID1='11111111-1111-4111-8111-111111111111'
CASE='22222222-2222-4222-8222-222222222222'
SHA='a'*64

def sample():
    payload=construct('a8',UUID1,CASE,'postwrite_verified',SHA,'2026-11-10T10:00:00Z')
    row={'event_id':payload['event_id'],'source_layer':'a8','source_event_id':UUID1,
         'source_sha256':SHA,'case_ref':payload['case_ref'],'payload_sha256':digest(payload),
         'payload':payload,'occurred_at':'2026-11-10T10:00:00Z'}
    return row

def evidence(row):
    p=row['payload'];return {
        'schema_version':SCHEMA,
        'snapshot_scope':'observed_make_airtable_test_records_only',
        'collected_at_utc':'2026-11-10T16:40:00Z',
        'make_data_store':[{'key':p['event_id'],'status':'mirrored',
            'airtable_record_id':'rec123456789ABCDE', 'evidence_sha256':p['source_evidence_sha256']}],
        'airtable':[{'id':'rec123456789ABCDE','event_id':p['event_id'],
           'case_ref':p['case_ref'],'event_type':p['event_type'],
           'source_layer':p['source_layer'],'occurred_at':p['occurred_at'],
           'evidence_sha256':p['source_evidence_sha256']}]
    }

class AuditTests(unittest.TestCase):
    def test_01_local_synthetic_outbox_hash_validates(self):
        self.assertEqual(_record(sample())['event_type'],'postwrite_verified')
    def test_02_invalid_payload_digest_rejected(self):
        row=sample();row['payload_sha256']='b'*64
        with self.assertRaises(ReconciliationError):reconcile([row],[])
    def test_03_modified_source_event_id_rejected(self):
        row=sample();row['source_event_id']='33333333-3333-4333-8333-333333333333'
        with self.assertRaises(ReconciliationError):reconcile([row],[])
    def test_04_blank_journal_pending(self):
        r=reconcile([sample()],[]);self.assertEqual(r['summary']['local_states'],{'pending':1})
    def test_05_reserved_state(self):
        r=reconcile([sample()],[{'event_id':sample()['event_id'],'event_kind':'dispatch_reserved'}]);self.assertEqual(r['events'][0]['local_state'],'reserved')
    def test_06_uncertain_state(self):
        id_=sample()['event_id'];r=reconcile([sample()],[{'event_id':id_,'event_kind':x} for x in ('dispatch_reserved','outcome_uncertain')]);self.assertEqual(r['events'][0]['local_state'],'uncertain')
    def test_07_ack_state(self):
        id_=sample()['event_id'];r=reconcile([sample()],[{'event_id':id_,'event_kind':x} for x in ('dispatch_reserved','processing_acknowledged')]);self.assertEqual(r['events'][0]['local_state'],'processed_ack')
    def test_08_dangling_ack_conflict(self):
        id_=sample()['event_id'];r=reconcile([sample()],[{'event_id':id_,'event_kind':'processing_acknowledged'}]);self.assertEqual(r['events'][0]['local_state'],'journal_conflict')
    def test_09_uncertain_and_ack_conflict(self):
        id_=sample()['event_id'];r=reconcile([sample()],[{'event_id':id_,'event_kind':x} for x in ('dispatch_reserved','processing_acknowledged','outcome_uncertain')]);self.assertEqual(r['events'][0]['local_state'],'journal_conflict')
    def test_10_remote_verified(self):
        row=sample();r=reconcile([row],[],evidence(row))
        self.assertEqual(r['events'][0]['remote_evidence'],'mirrored_fields_match_snapshot')
        self.assertEqual(r['events'][0]['action'],'HOLD_REMOTE_OBSERVED_NO_LOCAL_ACK_MANUAL_REVIEW')
    def test_11_remote_case_mismatch(self):
        row=sample();remote=evidence(row);remote['airtable'][0]['case_ref']='f'*24
        self.assertEqual(reconcile([row],[],remote)['events'][0]['remote_evidence'],'remote_mismatch')
    def test_12_remote_digest_mismatch(self):
        row=sample();remote=evidence(row);remote['make_data_store'][0]['evidence_sha256']='f'*64
        self.assertEqual(reconcile([row],[],remote)['events'][0]['remote_evidence'],'digest_mismatch')
    def test_13_remote_extra_ids(self):
        r=reconcile([],[],evidence(sample()))
        self.assertEqual(r['summary']['external_events_without_local_outbox'],1)
        self.assertTrue(r['requires_manual_review'])
    def test_14_remote_duplicate_event(self):
        row=sample();remote=evidence(row)
        double=dict(remote['airtable'][0]);double['id']='recABCDE123456789'
        remote['airtable'].append(double)
        self.assertEqual(reconcile([row],[],remote)['events'][0]['remote_evidence'],'remote_duplicate')
    def test_15_store_only_reserved(self):
        row=sample();remote=evidence(row);remote['airtable']=[]
        remote['make_data_store'][0]['status']='reserved'
        remote['make_data_store'][0]['airtable_record_id']=''
        self.assertEqual(reconcile([row],[],remote)['events'][0]['remote_evidence'],'reserved_without_airtable')
    def test_16_remote_mirror_without_store(self):
        row=sample();remote=evidence(row);remote['make_data_store']=[]
        self.assertEqual(reconcile([row],[],remote)['events'][0]['remote_evidence'],'airtable_without_store')
    def test_17_wrong_remote_schema_fails(self):
        row=sample();remote=evidence(row);remote['schema_version']='fake'
        with self.assertRaises(ReconciliationError):reconcile([row],[],remote)
    def test_18_unknown_remote_status_fails(self):
        row=sample();remote=evidence(row);remote['make_data_store'][0]['status']='done'
        with self.assertRaises(ReconciliationError):reconcile([row],[],remote)
    def test_19_unknown_local_delivery_fails(self):
        row=sample();events=[{'event_id':str(uuid.uuid4()),'event_kind':'dispatch_reserved'}]
        with self.assertRaises(ReconciliationError):reconcile([row],events)
    def test_20_synth_outbox_report_no_raw_payload(self):
        row=sample();s=json.dumps(reconcile([row],[],evidence(row)))
        self.assertNotIn('source_event_id',s)
        self.assertNotIn('payload_sha256',s)
        self.assertNotIn('authorizes_crm_write',s)
    def test_21_duplicate_local_event_id_fails(self):
        row=sample()
        with self.assertRaises(ReconciliationError):reconcile([row,row],[])
    def test_22_no_auto_dispatch_or_ack_policy(self):
        r=reconcile([sample()],[])
        self.assertEqual(r['policy'],'read_only_no_dispatch_no_replay_no_ack_no_crm_write')
    def test_24_four_smoke_events_are_not_local_deliveries(self):
        external = evidence(sample())
        external['make_data_store'] = []
        external['airtable'] = []
        for i in range(4):
            smoke_id = str(uuid.UUID(int=i + 1))
            record_id = f'rec{i:014d}'
            smoke = evidence(sample())
            external['make_data_store'].append(dict(
                smoke['make_data_store'][0], key=smoke_id, airtable_record_id=record_id))
            external['airtable'].append(dict(
                smoke['airtable'][0], id=record_id, event_id=smoke_id))
        result = reconcile([sample()], [], external)
        self.assertEqual(result['summary']['external_events_without_local_outbox'],4)
        self.assertEqual(result['events'][0]['local_state'],'pending')
        self.assertEqual(result['events'][0]['remote_evidence'],'not_observed')
    def test_25_timestamp_validation_rejects_naive_datetime(self):
        row=sample();row['occurred_at']='2026-11-10T10:00:00'
        with self.assertRaises(ReconciliationError):reconcile([row],[])
    def test_26_outbox_uppercase_sha_rejected(self):
        row=sample();row['source_sha256']='A'*64
        with self.assertRaises(ReconciliationError):reconcile([row],[])
    def test_27_remote_wrong_source_layer_detected(self):
        row=sample();remote=evidence(row);remote['airtable'][0]['source_layer']='a9'
        self.assertEqual(reconcile([row],[],remote)['events'][0]['remote_evidence'],'remote_mismatch')
    def test_28_outbox_above_safe_cap_rejected(self):
        with self.assertRaises(ReconciliationError):reconcile([sample()]*101,[])

    def test_mirrored_make_entry_requires_airtable_record_id(self):
        for invalid in (None, '', False, 0, []):
            with self.subTest(record_id=invalid):
                remote = evidence(sample())
                remote['make_data_store'][0]['airtable_record_id'] = invalid
                with self.assertRaises(ReconciliationError):
                    check_remote(remote)

    def test_make_event_id_must_agree_with_record_key_when_supplied(self):
        remote = evidence(sample())
        remote['make_data_store'][0]['event_id'] = UUID1
        with self.assertRaises(ReconciliationError):
            check_remote(remote)

    def test_23_processed_ack_without_remote_is_not_verified(self):
        row=sample();id_=row['event_id']
        r=reconcile([row],[{'event_id':id_,'event_kind':'dispatch_reserved'},{'event_id':id_,'event_kind':'processing_acknowledged'}])
        self.assertEqual(r['events'][0]['action'],'HOLD_ACK_REQUIRES_REMOTE_RECHECK')

if __name__=='__main__':unittest.main()
