"""Offline M5c tests: fictional data; no network, DB, or credential use."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.live_preflight import PORTAL_ID, LivePreflightError
from crm_quality.history_attribution import (
    HISTORY_FIELDS, MAX_EXTRA_GETS, _category, _validated_versions,
    fetch_selected_history, correlate,
)


class TestM5c(unittest.TestCase):
    def setUp(self):
        self.token = 'fictional-token-long-enough'
        row = {'firstname': 'Private Test', 'lastname': 'Character',
               'email': 'fictional@example.test', 'phone': '+10000000000'}
        base_record = {'updated_at': '2026-11-04T18:00:00+00:00', 'properties': row}
        self.baseline = {'baseline_run_id': 'demo-uuid', 'records': {
            'contacts': {'101': copy.deepcopy(base_record), '102': copy.deepcopy(base_record)},
            'companies': {'201': {'updated_at': '2026-11-04T18:00:00+00:00',
                                  'properties': {'name': 'Fictional Co', 'domain': 'demo.example',
                                                 'country': 'US', 'phone': None}}}},
            'links': {('101','201'): []}}
        self.live = {'verified_portal': PORTAL_ID, 'records': copy.deepcopy(self.baseline['records']),
                     'links': copy.deepcopy(self.baseline['links']), 'http_get_count': 5}
        self.live['records']['contacts']['101']['updated_at'] = '2026-11-05T02:22:30.000000+00:00'
        self.live['records']['contacts']['102']['updated_at'] = '2026-11-05T03:38:21.000000+00:00'
        self.observed_at = '2026-11-09T17:00:00+00:00'
        self.v1 = {'timestamp':'2026-11-05T02:22:30Z','sourceType':'CRM_UI',
                   'sourceId':'private-user-123','updatedByUserId':'42', 'value':'sensitive content'}
        self.v2 = {'timestamp':'2026-11-05T03:38:21Z','sourceType':'INTEGRATION',
                   'sourceId':'some-app-secret','value':'another-secret'}
        self.raw = {'results': [
            {'id':'101','updatedAt':'2026-11-05T02:22:30Z','archived':False,
             'propertiesWithHistory': {'lifecyclestage':[self.v1]}},
            {'id':'102','updatedAt':'2026-11-05T03:38:21Z','archived':False,
             'propertiesWithHistory': {'hs_lastmodifieddate':[self.v2]}},
        ]}
        self.calls=[]
        def reader(url,token):
            self.assertEqual(token,self.token)
            self.calls.append(url)
            return copy.deepcopy(self.raw)
        self.reader=reader

    def history(self):
        return fetch_selected_history(self.live,self.token,self.reader)

    def result(self, history=None):
        return correlate(self.live,self.baseline,history if history is not None else self.history(),self.observed_at)

    def test_01_single_get(self):
        self.history();self.assertEqual(len(self.calls),1)
    def test_02_history_query_fields_only(self):
        self.history();q=parse_qs(urlparse(self.calls[0]).query)
        self.assertEqual(set(q['propertiesWithHistory'][0].split(',')),set(HISTORY_FIELDS))
        self.assertEqual(q['properties'],q['propertiesWithHistory'])
    def test_03_proper_api_version(self):
        self.history();self.assertTrue(urlparse(self.calls[0]).path.startswith('/crm/objects/2026-03/contacts'))
    def test_04_bounds(self):
        self.assertEqual(MAX_EXTRA_GETS,1);self.assertEqual(self.result()['hubspot_get_count'],6)
    def test_05_two_correlations(self):
        r=self.result();self.assertEqual(r['contacts_with_near_update_history'],2)
    def test_06_contact_order_aliases(self):
        self.assertEqual([x['alias'] for x in self.result()['history_details']],['changed_contact_01','changed_contact_02'])
    def test_07_status_not_causal(self):
        r=self.result();self.assertEqual(r['status'],'HISTORY_CORRELATION_OBSERVED_NO_CAUSAL_PROOF');self.assertFalse(r['cause_confirmed'])
    def test_08_base_drift_preserved(self):
        self.assertEqual(self.result()['m5a_status'],'DRIFT_REQUIRES_REVIEW')
    def test_09_read_only(self):
        r=self.result();self.assertEqual((r['crm_writes'],r['postgres_writes'],r['airtable_writes'],r['merges']), (0,0,0,0))
    def test_10_no_secrets_or_values(self):
        text=json.dumps(self.result())
        for secret in ('101','102','Private Test','fictional@example.test','private-user-123',
                       '42', 'sensitive content','another-secret','some-app-secret',self.token):
            self.assertNotIn('"'+secret+'"',text)
        for secret in ('fictional@example.test','private-user-123','some-app-secret','sensitive content'):
            self.assertNotIn(secret,text)
    def test_11_known_source_classes(self):
        self.assertEqual(self.result()['history_details'][0]['near_update_source_classes'],['CRM_UI'])
    def test_12_unknown_source_redacted(self):
        self.raw['results'][0]['propertiesWithHistory']['lifecyclestage'][0]['sourceType']='user@example.test'
        self.assertEqual(self.result()['history_details'][0]['near_update_source_classes'],['OTHER_OR_UNKNOWN'])
    def test_13_missing_history_is_unavailable(self):
        for record in self.raw['results']: record.pop('propertiesWithHistory')
        r=self.result();self.assertEqual((r['status'],r['contacts_with_selected_history']),('HISTORY_UNAVAILABLE_FOR_SELECTED_PROPERTIES',0))
    def test_14_empty_history_is_unavailable(self):
        for record in self.raw['results']: record['propertiesWithHistory']={}
        self.assertEqual(self.result()['contacts_with_selected_history'],0)
    def test_15_far_history_not_correlated(self):
        self.raw['results'][0]['propertiesWithHistory']['lifecyclestage'][0]['timestamp']='2026-11-04T20:00:00Z'
        self.raw['results'][1]['propertiesWithHistory']['hs_lastmodifieddate'][0]['timestamp']='2026-11-05T01:00:00Z'
        self.assertEqual(self.result()['status'],'NO_NEAR_HISTORY_IN_SELECTED_PROPERTIES')
    def test_16_history_future_not_correlated(self):
        for version in (self.v1,self.v2): version['timestamp']='2026-11-08T13:00:00Z'
        self.assertEqual(self.result()['contacts_with_near_update_history'],0)
    def test_17_history_before_baseline_excluded(self):
        self.v1['timestamp']='2026-11-03T10:00:00Z';self.assertEqual(self.result()['contacts_with_near_update_history'],1)
    def test_18_wrong_portal_blocked(self):
        self.live['verified_portal']='888';
        with self.assertRaises(LivePreflightError): self.history()
        self.assertFalse(self.calls)
    def test_19_missing_token_blocked(self):
        with self.assertRaises(LivePreflightError): fetch_selected_history(self.live,'',self.reader)
        self.assertFalse(self.calls)
    def test_20_changed_timestamp_race_blocked(self):
        self.raw['results'][0]['updatedAt']='2026-11-06T02:22:30Z'
        with self.assertRaises(LivePreflightError): self.history()
    def test_21_new_contact_race_blocked(self):
        self.raw['results'].append({'id':'999','updatedAt':'2026-11-05T00:00:00Z'})
        with self.assertRaises(LivePreflightError): self.history()
    def test_22_missing_contact_race_blocked(self):
        self.raw['results'].pop()
        with self.assertRaises(LivePreflightError): self.history()
    def test_23_duplicate_id_blocked(self):
        self.raw['results'].append(copy.deepcopy(self.raw['results'][0]))
        with self.assertRaises(LivePreflightError): self.history()
    def test_24_pagination_blocked(self):
        self.raw['paging']={'next':{'after':'abc'}}
        with self.assertRaises(LivePreflightError): self.history()
    def test_25_malformed_history_blocked(self):
        self.raw['results'][0]['propertiesWithHistory']['lifecyclestage']=[{'value':'bad'}]
        with self.assertRaises(LivePreflightError): self.history()
    def test_26_history_cap_blocked(self):
        self.raw['results'][0]['propertiesWithHistory']['lifecyclestage']=[self.v1]*101
        with self.assertRaises(LivePreflightError): self.history()
    def test_27_history_unexpected_field_blocked(self):
        self.raw['results'][0]['propertiesWithHistory']['email']=[self.v1]
        with self.assertRaises(LivePreflightError): self.history()
    def test_28_no_drift_no_extra_read(self):
        for rid in self.live['records']['contacts']:
            self.live['records']['contacts'][rid]['updated_at']=self.baseline['records']['contacts'][rid]['updated_at']
        r=correlate(self.live,self.baseline,None,self.observed_at)
        self.assertEqual((r['status'],r['extra_history_get_count']),('NO_CONTACT_TIMESTAMP_DRIFT',0))
    def test_29_missing_history_fails_if_changed(self):
        with self.assertRaises(LivePreflightError): correlate(self.live,self.baseline,None,self.observed_at)
    def test_30_source_categories_are_narrow(self):
        self.assertEqual(_category('INTEGRATION'),'INTEGRATION')
        self.assertEqual(_category('unknown-category@example.test'),'OTHER_OR_UNKNOWN')
    def test_31_naive_history_timestamp_blocked(self):
        with self.assertRaises(LivePreflightError): _validated_versions([{'timestamp':'2026-11-05T02:22:30'}])
    def test_32_nonlist_versions_blocked(self):
        with self.assertRaises(LivePreflightError): _validated_versions({'timestamp':'2026-11-05T02:22:30Z'})
    def test_33_history_source_type_wrong_type_blocked(self):
        with self.assertRaises(LivePreflightError): _validated_versions([{'timestamp':'2026-11-05T02:22:30Z','sourceType':123}])
    def test_34_changed_property_preserves_other_drift(self):
        self.live['records']['contacts']['101']['properties']['firstname']='Changed'
        self.assertEqual(self.result()['m5b_status'],'OTHER_DRIFT_ALSO_PRESENT')
    def test_35_report_digest_repeatable(self):
        self.assertEqual(self.result()['report_sha256'],self.result()['report_sha256'])
    def test_36_incorrect_id_blocked(self):
        self.raw['results'][0]['id']='O0001'
        with self.assertRaises(LivePreflightError): self.history()

if __name__=='__main__': unittest.main()
