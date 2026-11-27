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
            row['review_key']:row for row in self.api('GET','reviews',query={'store_id':'eq.'+store['id']})})
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
