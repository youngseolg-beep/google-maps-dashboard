"""Actual SourceWriter/RPC regressions, synthetic isolated PostgREST only."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import types
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4
import ast
import shutil

sys.path.insert(0,str(Path(__file__).resolve().parent))
if importlib.util.find_spec('playwright') is None:
    package = types.ModuleType('playwright')
    sync = types.ModuleType('playwright.sync_api')
    sync.sync_playwright = Mock(side_effect=AssertionError('browser launch forbidden in storage tests'))
    sys.modules['playwright'] = package
    sys.modules['playwright.sync_api'] = sync
import local_review_append_pilot as pilot
import local_review_append_batch as batch
import scraper as production


def card(identity, *, author='Synthetic reviewer', body='Synthetic body', date='2 days ago'):
    return dict(source_id=identity,author=author,body=body,body_scope='PRIMARY',rating=5,date_label=date)


def evidence(records):
    return {hashlib.sha256(r['source_id'].encode()).hexdigest():dict(
        scope='PRIMARY',fingerprint=hashlib.sha256(r['body'].encode()).digest(),click_error=False,
        more_remaining=0,original_remaining=0,more_verified=True,original_verified=True,
        rating_only_verified=r['body']=='' and r.get('body_absence_evidence')=='NO_KNOWN_TEXT_NODES') for r in records}


class WriterPlanning(unittest.TestCase):
    def planning_writer(self):
        writer=pilot.SourceWriter.__new__(pilot.SourceWriter)
        writer.store=dict(id=str(uuid4()),store_name='Fixture',sv='A',country='Synthetic')
        writer.history,writer.known,writer.linked_rows,writer.held,writer.run_id={},set(),set(),{},None
        return writer

    def test_actionable_rejection_is_one_primary_category(self):
        raw=card('rejected')
        proof=evidence([raw])[hashlib.sha256(b'rejected').hexdigest()]
        cases=[({},'body_audit_missing'),
               (dict(proof,click_error=True,more_remaining=1),'body_control_click_failed'),
               (dict(proof,more_remaining=1,original_remaining=1),'more_control_unresolved'),
               (dict(proof,original_remaining=1),'original_control_unresolved'),
               (dict(proof,more_verified=False),'more_resolution_unverified'),
               (dict(proof,original_verified=False),'original_resolution_unverified'),
               (dict(proof,scope='AMBIGUOUS'),'customer_body_scope_unverified'),
               (dict(proof,fingerprint=b'changed'),'body_changed_after_audit')]
        for value,reason in cases:
            with self.subTest(reason=reason):
                writer=self.planning_writer()
                self.assertEqual(writer.plan([raw],{hashlib.sha256(b'rejected').hexdigest():value}),[])
                self.assertEqual(list(writer.held.values()),[reason])
        self.assertEqual(pilot.acceptance_rejection(dict(raw,author='',rating=None),{}),'author_missing')
        self.assertEqual(pilot.acceptance_rejection(dict(raw,rating=None),{}),'rating_missing_or_invalid')

    def test_resolved_more_and_unchanged_original_reach_actual_writer(self):
        raw=card('controls')
        page=Mock()
        node=Mock()
        page.locator.return_value.evaluate_all.return_value=['controls']
        page.locator.return_value.nth.return_value=node
        node.get_attribute.return_value='controls'
        opened={'more':True,'original':True}
        more,original=Mock(),Mock()
        more.click.side_effect=lambda **kw:opened.update(more=False)
        original.click.side_effect=lambda **kw:opened.update(original=False)
        def control(card,pattern):
            which='more' if pattern is pilot.probe.MORE_LABEL else 'original'
            return ((more if which=='more' else original),1,0) if opened[which] else (None,0,0)
        fingerprint=hashlib.sha256(raw['body'].encode()).digest()
        proof={}
        with patch.object(pilot.probe,'blocked',return_value=False),patch.object(pilot.probe,'same_place',return_value=True), \
             patch.object(pilot.probe,'selected',return_value=True),patch.object(pilot.probe,'body_control',side_effect=control), \
             patch.object(pilot.probe,'body_snapshot',return_value=(len(raw['body']),fingerprint,'PRIMARY')), \
             patch.object(pilot.probe,'detail_measure',return_value=1):
            metrics=pilot.probe.audit_body_sample(page,'synthetic',Mock(),evidence_sink=proof)
        self.assertEqual(metrics['more_length_increased'],0)
        self.assertEqual(metrics['original_text_changed'],0)
        value=proof[hashlib.sha256(b'controls').hexdigest()]
        self.assertTrue(value['more_verified'])
        self.assertTrue(value['original_verified'])
        self.assertEqual(len(self.planning_writer().plan([raw],proof)),1)
        value['original_remaining']=1
        self.assertEqual(self.planning_writer().plan([raw],proof),[])

    def test_rating_only_more_requires_resolved_details_and_structural_evidence(self):
        for details_after in (0,3):
            with self.subTest(details_after=details_after):
                raw=card('rating-details',body='')
                raw['body_scope']='NOT_DETECTED'
                page,node,button=Mock(),Mock(),Mock()
                page.locator.return_value.evaluate_all.return_value=[raw['source_id']]
                page.locator.return_value.nth.return_value=node
                node.get_attribute.return_value=raw['source_id']
                node.evaluate.return_value=True
                state={'more':True}
                button.click.side_effect=lambda **kw:state.update(more=False)
                def control(card,pattern):
                    return (button,1,0) if pattern is pilot.probe.MORE_LABEL and state['more'] else (None,0,0)
                proof={}
                with patch.object(pilot.probe,'blocked',return_value=False),patch.object(pilot.probe,'same_place',return_value=True), \
                     patch.object(pilot.probe,'selected',return_value=True),patch.object(pilot.probe,'body_control',side_effect=control), \
                     patch.object(pilot.probe,'body_snapshot',return_value=(0,None,'NOT_DETECTED')), \
                     patch.object(pilot.probe,'detail_measure',side_effect=[0,details_after]):
                    pilot.probe.audit_body_sample(page,'synthetic',Mock(),evidence_sink=proof)
                planned=self.planning_writer().plan([raw],proof)
                self.assertEqual(len(planned),int(details_after>0))
                if planned:
                    self.assertFalse(planned[0]['row']['has_text'])

    @unittest.skipUnless(shutil.which('node'),'Node required for DOM acceptance fixture')
    def test_rating_only_accepts_span_rating_but_rejects_hidden_or_unknown_body(self):
        tree=ast.parse(Path(pilot.probe.__file__).read_text(encoding='utf8'))
        function=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='rating_only_structure')
        source=next(n.value for n in ast.walk(function) if isinstance(n,ast.Constant) and isinstance(n.value,str))
        js=r'''
const source=JSON.parse(require('fs').readFileSync(0,'utf8'));
global.NodeFilter={SHOW_TEXT:4};
        for (const mode of ['rating','hidden','unknown','more','details','owner_more']) {
  const textNodes=['unknown','details'].includes(mode)?[{textContent:'Unrecognized customer content',parentElement:{getClientRects:()=>[1],closest:s=>mode==='details'&&s==='.RfDO5c'?{querySelector:()=>null}:null}}]:[];
  global.document={createTreeWalker:()=>({nextNode:()=>textNodes.shift()||null})};
  const rating={getClientRects:()=>[1],closest:()=>null,getAttribute:()=> '5 stars'};
  const card={
    querySelector:sel=>sel==='.d4r55'?{}:null,
    querySelectorAll:sel=>sel==='[aria-label]'?[rating]:
      sel==='.wiI7pd,.MyEned'&&mode==='hidden'?[{closest:()=>null}]:
      sel==='button,[role="button"]'&&['more','owner_more'].includes(mode)?[{getClientRects:()=>[1],closest:()=>mode==='owner_more'?{}:null,innerText:'More'}]:[]
  };
  console.log(JSON.stringify([mode,eval('('+source+')')(card)]));
}
'''
        result=subprocess.run(['node','-e',js],input=json.dumps(source),text=True,capture_output=True,check=True)
        self.assertEqual(dict(json.loads(line) for line in result.stdout.splitlines()),
                         dict(rating=True,hidden=False,unknown=False,more=False,details=True,owner_more=True))

    @unittest.skipUnless(shutil.which('node'),'Node required for DOM control fixture')
    def test_details_only_more_is_associated_but_owner_more_is_excluded(self):
        tree=ast.parse(Path(pilot.probe.__file__).read_text(encoding='utf8'))
        function=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='body_control')
        source=next(n.args[0].value for n in ast.walk(function) if isinstance(n,ast.Call)
                    and isinstance(n.func,ast.Attribute) and n.func.attr=='evaluate_all')
        js=r'''
const source=JSON.parse(require('fs').readFileSync(0,'utf8'));
global.Node={DOCUMENT_POSITION_FOLLOWING:4};
for(const mode of ['details','owner','unknown']){
 const card={querySelectorAll:()=>[]};
 const region={parentElement:card,querySelector:()=>mode==='unknown'?null:{},querySelectorAll:()=>[]};
 const button={tagName:'BUTTON',classList:{contains:()=>true},hasAttribute:()=>true,
  parentElement:region,getClientRects:()=>[1],contains:()=>false,
  closest:s=>s==='.jftiEf[data-review-id]'?card:mode==='owner'?{}:null};
 console.log(JSON.stringify([mode,eval('('+source+')')([button])]));
}
'''
        result=subprocess.run(['node','-e',js],input=json.dumps(source),text=True,capture_output=True,check=True)
        rows=dict(json.loads(line) for line in result.stdout.splitlines())
        self.assertEqual(len(rows['details']['accepted']),1)
        self.assertEqual(rows['owner']['excluded'],1)
        self.assertEqual(rows['unknown']['unresolved'],1)

    def test_journal_refuses_a_different_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=pilot.AttemptJournal(Path(tmp)/'journal.sqlite3')
            try:
                journal.bind_backend('https://synthetic-a.supabase.co')
                journal.bind_backend('https://synthetic-a.supabase.co')
                with self.assertRaisesRegex(ValueError,'JOURNAL_BACKEND_MISMATCH'):
                    journal.bind_backend('https://synthetic-b.supabase.co')
            finally:
                journal.close()

    def test_unknown_date_and_distinct_same_author_are_retained(self):
        writer = pilot.SourceWriter.__new__(pilot.SourceWriter)
        writer.store = dict(id=str(uuid4()),store_name='Fixture',sv='A',country='Synthetic')
        writer.history, writer.known, writer.linked_rows, writer.held, writer.run_id = {},set(),set(),{},None
        rows = [card('one',date=None),card('two',body='Different')]
        items = writer.plan(rows,evidence(rows))
        self.assertEqual(len(items),2)
        self.assertIsNone(items[0]['row']['review_date'])
        self.assertEqual(items[0]['row']['review_date_source'],'unknown')
        self.assertNotEqual(items[0]['row']['review_key'],items[1]['row']['review_key'])

    def test_missing_text_is_not_rating_only(self):
        writer = pilot.SourceWriter.__new__(pilot.SourceWriter)
        writer.store = dict(id=str(uuid4()),store_name='Fixture',sv='A',country='Synthetic')
        writer.history, writer.known, writer.linked_rows, writer.held, writer.run_id = {},set(),set(),{},None
        raw = card('empty',body='')
        self.assertEqual(writer.plan([raw],evidence([raw])),[])
        raw['body_absence_evidence']='NO_KNOWN_TEXT_NODES'
        self.assertFalse(writer.plan([raw],evidence([raw]))[0]['row']['has_text'])


@unittest.skipUnless(os.environ.get('SV_WRITER_TEST_API'),'isolated PostgREST fixture required')
class StorageTests(unittest.TestCase):
    def api(self, method, table, query=None, body=None, prefer=None):
        base=os.environ['SV_WRITER_TEST_API']
        assert urlsplit(base).hostname=='127.0.0.1'
        headers={'Authorization':'Bearer '+os.environ['SV_WRITER_TEST_TOKEN'],
                 'Content-Type':'application/json','Prefer':prefer or 'return=representation'}
        url=base+'/'+table+('?' + urlencode(query) if query else '')
        with urlopen(Request(url, data=json.dumps(body).encode() if body is not None else None,
                             headers=headers,method=method),timeout=10) as response:
            text=response.read()
        return json.loads(text) if text else None

    def setUp(self):
        marker=self.api('GET','sv_writer_fixture')
        self.assertEqual(marker,[{'marker':os.environ['SV_WRITER_TEST_MARKER']}])
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=dict(id=str(uuid4()),store_name='Synthetic fixture '+str(uuid4()),sv='A',country='Synthetic',is_active=True)
        self.api('POST','stores',body=self.store)
        self.patch=patch.object(production,'supabase_request',side_effect=self.api)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.history_patch=patch.object(pilot,'history_snapshot',side_effect=lambda config,store:{
            row['review_key']:pilot.probe.normalize_history_row(row) for row in self.api('GET','reviews',query={'store_id':'eq.'+store['id']})})
        self.history_patch.start()
        self.addCleanup(self.history_patch.stop)
        self.writers=[]
        self.addCleanup(lambda:[w.journal.close() for w in self.writers])

    def writer(self):
        writer=pilot.SourceWriter(None,self.store,Path(self.tmp.name)/'journal.sqlite3',commit=True)
        self.writers.append(writer)
        return writer

    def saved(self):
        return self.api('GET','reviews',query={'store_id':'eq.'+self.store['id'],'order':'id.asc'})

    def test_duplicate_source_and_idempotent_replay_preserve_first_payload(self):
        writer=self.writer()
        raw=card('stable')
        writer.append([raw,raw],evidence([raw]))
        before=self.saved()
        edited=card('stable',body='Changed payload')
        self.writer().append([edited],evidence([edited]))
        self.assertEqual(self.saved(),before)
        self.assertEqual(len(before),1)

    def test_distinct_same_author_rating_only_and_unknown_date(self):
        writer=self.writer()
        rows=[card('one'),card('two',body='Second review'),card('empty',body='',date=None)]
        rows[-1]['body_absence_evidence']='NO_KNOWN_TEXT_NODES'
        writer.append(rows,evidence(rows))
        saved=self.saved()
        self.assertEqual(len(saved),3)
        empty=next(r for r in saved if not r['has_text'])
        self.assertEqual(empty['text'],'')
        self.assertIsNone(empty['review_date'])
        self.assertEqual(empty['review_date_source'],'unknown')

    def test_interrupted_chunk_and_lost_response_recover_after_process_restart(self):
        writer=self.writer()
        raw=card('first')
        writer.append([raw],evidence([raw]))
        before=self.saved()
        second=card('second',body='Other')
        real=self.api
        def lose_response(method,table,**kwargs):
            result=real(method,table,**kwargs)
            if table=='rpc/append_review_sources':
                raise OSError('synthetic response loss')
            return result
        with patch.object(production,'supabase_request',side_effect=lose_response):
            with self.assertRaises(OSError): writer.append([second],evidence([second]))
        self.assertEqual(len(writer.journal.pending_requests(self.store['id'])),1)
        writer.journal.close()
        self.writers.remove(writer)
        child = '''
import json,os
from pathlib import Path
from unittest.mock import patch
import test_live_source_writer as tests
case=tests.StorageTests()
store=json.loads(os.environ['SV_TEST_STORE'])
with patch.object(tests.production,'supabase_request',side_effect=case.api), patch.object(
    tests.pilot,'history_snapshot',side_effect=lambda config,s:{r['review_key']:r for r in case.api('GET','reviews',query={'store_id':'eq.'+s['id']})}):
    writer=tests.pilot.SourceWriter(None,store,Path(os.environ['SV_TEST_JOURNAL']),commit=True)
    assert writer.journal.pending_requests(store['id'])==[]
    writer.journal.close()
'''
        completed=subprocess.run([sys.executable,'-B','-c',child],cwd=Path(__file__).resolve().parent,
            env={**os.environ,'SV_TEST_STORE':json.dumps(self.store),'SV_TEST_JOURNAL':str(Path(self.tmp.name)/'journal.sqlite3')},
            capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        recovered=self.writer()
        self.assertEqual(recovered.journal.pending_requests(self.store['id']),[])
        self.assertEqual(len(self.saved()),2)
        self.assertTrue(all(r in self.saved() for r in before))
        recovered.append([second],evidence([second]))
        self.assertEqual(len(self.saved()),2)

    def test_request_loss_before_commit_replays_exact_envelope(self):
        writer=self.writer()
        raw=card('lost-before-commit')
        with patch.object(production,'supabase_request',side_effect=OSError('offline')):
            with self.assertRaises(OSError):writer.append([raw],evidence([raw]))
        self.assertEqual(len(self.saved()),0)
        self.writer()
        self.assertEqual(len(self.saved()),1)

    def test_legacy_link_preserves_every_historical_field_and_key(self):
        writer=self.writer()
        raw=card('legacy')
        item=writer.plan([raw],evidence([raw]))[0]
        item['row']['review_key']='a'*64
        self.api('POST','reviews',body=item['row'])
        before=self.saved()
        self.writer().append([raw],evidence([raw]))
        self.assertEqual(self.saved(),before)
        self.assertEqual(len(self.writer().known),1)

    def test_relative_date_drift_links_unique_body_without_historical_changes(self):
        writer=self.writer()
        original=card('old-date',date='2 days ago')
        old=writer.plan([original],evidence([original]))[0]['row']
        self.api('POST','reviews',body=old)
        before=self.saved()
        current=card('live-source',date='3 weeks ago',author='SYNTHETIC REVIEWER')
        writer=self.writer()
        writer.append([current],evidence([current]))
        self.assertEqual(self.saved(),before)
        self.assertEqual(writer.outcomes,{'linked_legacy':1})
        self.assertFalse(writer.held)

    def test_legacy_date_fallback_preserves_the_rpc_preimage(self):
        writer=self.writer()
        raw=card('fallback')
        old=writer.plan([raw],evidence([raw]))[0]['row']
        old.update(date='',relative_date='2 days ago')
        self.api('POST','reviews',body=old)
        before=self.saved()
        current=card('new-live-id',date='3 weeks ago')
        writer=self.writer()
        writer.append([current],evidence([current]))
        self.assertEqual(self.saved(),before)
        self.assertEqual(writer.outcomes,{'linked_legacy':1})

    def test_legacy_whitespace_difference_links_without_rewriting_text(self):
        writer=self.writer()
        raw=card('whitespace')
        old=writer.plan([raw],evidence([raw]))[0]['row']
        old['text']='Synthetic\n\n body'
        self.api('POST','reviews',body=old)
        before=self.saved()
        writer=self.writer()
        writer.append([raw],evidence([raw]))
        self.assertEqual(self.saved(),before)
        self.assertEqual(writer.outcomes,{'linked_legacy':1})

    def test_multiple_whitespace_equivalent_targets_remain_held(self):
        writer=self.writer()
        raw=card('whitespace-ambiguous')
        old=writer.plan([raw],evidence([raw]))[0]['row']
        self.api('POST','reviews',body=[dict(old,review_key='e'*64),dict(old,text='Synthetic\n body',review_key='f'*64)])
        writer=self.writer()
        writer.append([raw],evidence([raw]))
        self.assertEqual(len(self.saved()),2)
        self.assertEqual(list(writer.held.values()),['legacy_identity_ambiguous'])

    def test_conflicting_absolute_dates_are_held(self):
        writer=self.writer()
        raw=card('old-calendar',date='2026-11-01')
        old=writer.plan([raw],evidence([raw]))[0]['row']
        self.api('POST','reviews',body=old)
        current=card('different-calendar',date='2026-11-02')
        writer=self.writer()
        writer.append([current],evidence([current]))
        self.assertEqual(len(self.saved()),1)
        self.assertEqual(list(writer.held.values()),['legacy_absolute_date_conflict'])

    def test_ambiguous_legacy_dates_do_not_block_independent_new_review(self):
        writer=self.writer()
        original=card('old-date')
        old=writer.plan([original],evidence([original]))[0]['row']
        first=dict(old,review_key='c'*64,date='2 days ago')
        second=dict(old,review_key='d'*64,date='3 days ago')
        self.api('POST','reviews',body=[first,second])
        before=self.saved()
        ambiguous=card('ambiguous',date='3 weeks ago')
        valid=card('valid-new',author='Different synthetic reviewer')
        writer=self.writer()
        writer.append([ambiguous,valid],evidence([ambiguous,valid]))
        self.assertEqual(writer.outcomes,{'inserted':1})
        self.assertEqual(list(writer.held.values()),['legacy_identity_ambiguous'])
        self.assertEqual(len(self.saved()),3)
        self.assertTrue(all(row in self.saved() for row in before))

    def test_rating_only_legacy_date_drift_remains_ambiguous(self):
        writer=self.writer()
        raw=card('old-rating',body='')
        raw['body_absence_evidence']='NO_KNOWN_TEXT_NODES'
        old=writer.plan([raw],evidence([raw]))[0]['row']
        self.api('POST','reviews',body=old)
        changed=dict(raw,source_id='live-rating',date_label='3 weeks ago')
        writer=self.writer()
        writer.append([changed],evidence([changed]))
        self.assertEqual(len(self.saved()),1)
        self.assertEqual(list(writer.held.values()),['legacy_rating_only_date_unverified'])

    def test_more_than_100_and_partial_run_do_not_skip_boundary(self):
        writer=self.writer()
        old=[card('old'+str(i),author='Old '+str(i)) for i in range(30)]
        writer.append(old,evidence(old))
        prior=[production.hash_google_source_review_id(self.store['id'],r['source_id']) for r in old]
        self.assertTrue(writer.finish(prior,newest_verified=True,complete=True))
        writer=self.writer()
        new=[card('new'+str(i),author='New '+str(i)) for i in range(151)]
        writer.append(new[:100],evidence(new[:100]))
        new_ids=[production.hash_google_source_review_id(self.store['id'],r['source_id']) for r in new]
        self.assertFalse(writer.finish(new_ids[:100],newest_verified=True,complete=False))
        writer=self.writer()
        writer.append(new,evidence(new))
        observed=new_ids+prior
        self.assertTrue(writer.boundary(observed))
        self.assertFalse(writer.finish(observed,newest_verified=False,complete=False))
        self.assertTrue(writer.finish(observed,newest_verified=True,complete=False))
        self.assertEqual(len(self.saved()),181)

    def test_daily_observed_frontier_preserves_old_backlog_without_advancing_db_baseline(self):
        writer=self.writer()
        old=[card('old-head'+str(i),author='Old '+str(i)) for i in range(31)]
        proof=evidence(old)
        proof.pop(hashlib.sha256(old[0]['source_id'].encode()).hexdigest())
        writer.append(old,proof)
        prior=[production.hash_google_source_review_id(self.store['id'],r['source_id']) for r in old]
        writer.observed=prior
        progress=writer.save_progress(newest_verified=True,complete=True,finished=True)
        self.assertTrue(progress['observed_frontier_saved'])
        self.assertEqual(progress['historical_backlog'],1)
        self.assertFalse(writer.finish(prior,newest_verified=True,complete=True))
        restarted=self.writer()
        new=[card('daily'+str(i),author='Daily '+str(i)) for i in range(5)]
        restarted.append(new,evidence(new))
        restarted.observed=[production.hash_google_source_review_id(self.store['id'],r['source_id']) for r in new]+prior[:30]
        self.assertTrue(restarted.frontier_reached())
        self.assertFalse(restarted.boundary(restarted.observed))
        self.assertFalse(restarted.finish(restarted.observed,newest_verified=True,complete=False))
        progress=restarted.save_progress(newest_verified=True,finished=True)
        self.assertEqual(progress['historical_backlog'],1)
        self.assertEqual(len(self.saved()),35)
        self.assertEqual(self.api('GET','review_source_baselines',query={'store_id':'eq.'+self.store['id']}),[])

    def test_unverified_sort_cannot_save_observed_frontier(self):
        writer=self.writer()
        writer.observed=[f'{i:064x}' for i in range(30)]
        result=writer.save_progress(newest_verified=False,finished=True)
        self.assertFalse(result['observed_frontier_saved'])
        self.assertIsNone(writer.journal.frontier(self.store['id']))
        self.assertEqual(result['historical_backlog'],30)

    def test_partial_history_is_explicit_and_frontier_generation_is_protected(self):
        writer=self.writer()
        writer.observed=[f'{i:064x}' for i in range(30)]
        result=writer.save_progress(newest_verified=True,finished=True)
        self.assertTrue(result['historical_coverage_unknown'])
        left,right=self.writer(),self.writer()
        left.observed=right.observed=writer.observed
        left.save_progress(newest_verified=True,finished=True)
        with self.assertRaisesRegex(ValueError,'LOCAL_FRONTIER_GENERATION_CONFLICT'):
            right.save_progress(newest_verified=True,finished=True)
        missed=self.writer()
        old_head=missed.daily_frontier['head']
        missed.observed=[f'{i:064x}' for i in range(100,130)]
        result=missed.save_progress(newest_verified=True,finished=True)
        self.assertFalse(result['observed_frontier_saved'])
        self.assertEqual(missed.journal.frontier(self.store['id'])['head'],old_head)

    def test_unresolved_body_blocks_boundary(self):
        writer=self.writer()
        rows=[card(str(i),author=str(i)) for i in range(31)]
        proof=evidence(rows)
        proof.pop(hashlib.sha256(rows[-1]['source_id'].encode()).hexdigest())
        writer.append(rows,proof)
        observed=[production.hash_google_source_review_id(self.store['id'],r['source_id']) for r in rows]
        self.assertFalse(writer.finish(observed,newest_verified=True,complete=True))
        self.assertEqual(len(self.saved()),30)

    def test_concurrent_source_insertion_is_database_idempotent(self):
        writer=self.writer()
        raw=card('parallel')
        items=writer.plan([raw],evidence([raw]))
        def submit(_):
            return self.api('POST','rpc/append_review_sources',body=dict(
                p_operation_id=str(uuid4()),p_store_id=self.store['id'],p_items=items,p_finalize=None))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(r['outcomes'][0]['status'] for r in results),['existing_source','inserted'])
        self.assertEqual(len(self.saved()),1)

    def test_backfill_stream_commits_before_end_and_restart_skips_stored_bodies(self):
        writer=self.writer()
        rows=[card('stream'+str(i),author='Reviewer '+str(i)) for i in range(40)]
        by_id={r['source_id']:r for r in rows}
        page=Mock()
        def fields(*args,selected_ids,**kwargs):
            return {},[by_id[i] for i in selected_ids]
        def audit(*args,selected_ids,evidence_sink,**kwargs):
            evidence_sink.update(evidence([by_id[i] for i in selected_ids]))
            return dict(context_lost=False,identity_mismatch=0)
        with patch.object(pilot.probe,'audit_loaded_fields',side_effect=fields), \
             patch.object(pilot.probe,'audit_body_sample',side_effect=audit) as audit_mock:
            page.locator.return_value.evaluate_all.return_value=[r['source_id'] for r in rows[:20]]
            state=writer.collect_window(page,Mock(),'synthetic',recent=False)
            self.assertEqual(state['committed'],20)
            self.assertEqual(len(self.saved()),20)
            restarted=self.writer()
            page.locator.return_value.evaluate_all.return_value=[r['source_id'] for r in rows]
            state=restarted.collect_window(page,Mock(),'synthetic',recent=False)
            self.assertEqual(state['committed'],40)
            self.assertEqual(audit_mock.call_count,2)
            self.assertEqual(audit_mock.call_args.kwargs['selected_ids'],set(r['source_id'] for r in rows[20:]))
        self.assertEqual(len(self.saved()),40)

    def test_initial_partial_and_stale_generation_do_not_advance(self):
        writer=self.writer()
        rows=[card(str(i),author=str(i)) for i in range(30)]
        writer.append(rows,evidence(rows))
        observed=[production.hash_google_source_review_id(self.store['id'],r['source_id']) for r in rows]
        self.assertFalse(writer.finish(observed,newest_verified=True,complete=False))
        stale=self.writer()
        self.assertTrue(writer.finish(observed,newest_verified=True,complete=True))
        self.assertFalse(stale.finish(observed,newest_verified=True,complete=True))

    def test_unlinked_same_author_distinct_review_stays_held_until_reconciled(self):
        writer=self.writer()
        legacy=card('old')
        row=writer.plan([legacy],evidence([legacy]))[0]['row']
        row['review_key']='b'*64
        self.api('POST','reviews',body=row)
        writer=self.writer()
        new=card('new',body='Distinct legitimate review')
        writer.append([new],evidence([new]))
        self.assertEqual(len(self.saved()),1)
        self.assertTrue(writer.held)
        writer.append([legacy],evidence([legacy]))
        writer.append([new],evidence([new]))
        self.assertEqual(len(self.saved()),2)
        self.assertFalse(writer.held)

    def test_invalid_second_row_rolls_back_first_row_and_receipt(self):
        writer=self.writer()
        rows=[card('first'),card('second',body='second')]
        items=writer.plan(rows,evidence(rows))
        items[1]['row']['store_id']=str(uuid4())
        operation=str(uuid4())
        with self.assertRaises(HTTPError):
            self.api('POST','rpc/append_review_sources',body=dict(
                p_operation_id=operation,p_store_id=self.store['id'],p_items=items,p_finalize=None))
        self.assertEqual(self.saved(),[])
        self.assertEqual(self.api('GET','review_source_receipts',query={'operation_id':'eq.'+operation}),[])
        self.assertEqual(self.writer().known,set())

    def test_same_operation_cannot_be_reused_with_a_different_payload(self):
        writer=self.writer()
        raw=card('receipt')
        request=dict(p_operation_id=str(uuid4()),p_store_id=self.store['id'],
                     p_items=writer.plan([raw],evidence([raw])),p_finalize=None)
        first=self.api('POST','rpc/append_review_sources',body=request)
        self.assertEqual(self.api('POST','rpc/append_review_sources',body=request),first)
        changed=deepcopy(request)
        changed['p_items'][0]['row']['text']='different'
        with self.assertRaises(HTTPError):
            self.api('POST','rpc/append_review_sources',body=changed)
        self.assertEqual(self.saved()[0]['text'],'Synthetic body')

    def test_interruption_between_250_row_chunks_preserves_committed_prefix(self):
        writer=self.writer()
        rows=[card('chunk'+str(i),author='Chunk '+str(i)) for i in range(251)]
        real=self.api
        posts=0
        def interrupt(method,table,**kwargs):
            nonlocal posts
            if table=='rpc/append_review_sources':
                posts+=1
                if posts==2:
                    raise OSError('interrupted before second chunk')
            return real(method,table,**kwargs)
        with patch.object(production,'supabase_request',side_effect=interrupt):
            with self.assertRaises(OSError):writer.append(rows,evidence(rows))
        self.assertEqual(len(self.saved()),250)
        recovered=self.writer()
        self.assertEqual(len(self.saved()),251)
        recovered.append(rows,evidence(rows))
        self.assertEqual(len(self.saved()),251)

    def test_receipts_and_review_rows_are_not_mutable_through_fixture_role(self):
        writer=self.writer()
        raw=card('immutable')
        writer.append([raw],evidence([raw]))
        before=self.saved()
        for method,table,body in [('PATCH','reviews',{'text':'overwritten'}),
                                  ('DELETE','reviews',None),
                                  ('PATCH','review_source_receipts',{'result':{}})]:
            with self.assertRaises(HTTPError):
                self.api(method,table,query={'store_id':'eq.'+self.store['id']},body=body)
        self.assertEqual(self.saved(),before)

    def test_real_batch_callback_uses_the_source_writer(self):
        raw=card('batch')
        page=Mock()
        context=Mock(pages=[])
        def capture(*args,stream,**kwargs):
            self.assertTrue(kwargs['stream_recent'])
            state=stream(page,Mock())
            self.assertEqual(state['observed'],1)
            return dict(status='STREAM_CAPTURE_FINISHED',stop_reason='ROUND_LIMIT',expected_total_user_observed=500)
        page.locator.return_value.evaluate_all.return_value=['batch']
        def audit(*args,evidence_sink,**kwargs):
            evidence_sink.update(evidence([raw]))
            return dict(context_lost=False,identity_mismatch=0)
        task=dict(key='synthetic',store_id=self.store['id'],name=self.store['store_name'],country='Synthetic',pair='fixture',url='https://www.google.com/maps/place/fixture')
        with patch.dict(os.environ,LOCALAPPDATA=self.tmp.name),patch.object(pilot.probe,'verified_db_store',return_value=self.store), \
             patch.object(pilot.probe,'run_once',side_effect=capture), \
             patch.object(pilot.probe,'audit_loaded_fields',return_value=({},[raw])), \
             patch.object(pilot.probe,'audit_body_sample',side_effect=audit):
            Path(self.tmp.name,'SVReviewMaster').mkdir()
            result=batch.run_store(context,None,task,True,None,mode='recent')
        self.assertEqual(result['confirmed_new'],1)
        self.assertTrue(result['coverage_incomplete'])
        self.assertFalse(result['boundary_advanced'])
        self.assertEqual(len(self.saved()),1)


if __name__=='__main__':
    unittest.main(verbosity=2)
