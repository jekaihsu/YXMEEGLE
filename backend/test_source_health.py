"""Behavioral checks using synthetic snapshots only; no network or Lark reads."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from .source_health import build_source_health as build


OLD = '2026-10-10T08:00:00+08:00'
NEW = '2026-10-14T08:00:00+08:00'


def snapshot(**changes):
    value = {'configured': True, 'status': 'ready', 'last_sync': OLD,
             'last_attempt_at': NEW, 'message': 'safe synthetic fixture',
             'tables': [{'base_token': 'base-A', 'table_id': 'table-A', 'name': 'Authorized source',
                         'kind': 'quote', 'status': 'ready', 'pages_read': 2,
                         'page_limit': 50, 'record_limit': 10000, 'count': 7}],
             'records': [{'fields': {'secret-value': 'NEVER EMIT RECORD CONTENT'}}]}
    value.update(changes)
    return value


def row(value=None, **options):
    options.setdefault('freshness', {'status': 'fresh'})
    return build(value or snapshot(), diagnostic=True, **options)['sources'][0]


def test_separate_timestamps_and_normalizes_existing_microseconds():
    result = row(snapshot(last_sync=OLD.replace('+08:00', '.123456+08:00')))
    assert result['last_attempt'] == '2026-10-14T08:00:00.000+08:00'
    assert result['last_success'] == '2026-10-10T08:00:00.123+08:00'
    assert 'last_success' not in row(snapshot(last_sync='2026-10-10'))


def test_fetch_time_not_source_updated_even_with_caller_claims():
    value = snapshot(source_updated=NEW, changed_at=NEW)
    value['tables'][0]['source_updated'] = NEW
    result = row(value, freshness={'fetched_at': NEW, 'changed_at': NEW})
    assert result['last_success'] == '2026-10-10T08:00:00.000+08:00'
    assert 'source_updated' not in result


def test_configured_not_read_and_count_does_not_prove_read():
    value = snapshot()
    value['tables'][0].pop('pages_read')
    result = row(value)
    assert result['data_state']['states'] == ['unknown']
    assert not any(key in result for key in ('health', 'located', 'readable', 'last_success', 'loaded_count'))
    value['tables'][0]['pages_read'] = 1
    assert row(value)['readable'] is True


def test_oldest_relevant_snapshot_and_missing_time_is_unknown():
    value = snapshot()
    value['tables'] += [dict(value['tables'][0], table_id='table-B', last_sync=NEW),
                        dict(value['tables'][0], table_id='table-C', last_sync='2026-10-01T00:00:00Z', relevant=False)]
    result = build(value, diagnostic=True)
    assert result['diagnostic']['last_success'] == '2026-10-10T08:00:00.000+08:00'
    value['tables'][1]['last_sync'] = None
    assert build(value, diagnostic=True)['diagnostic']['last_success'] is None


@pytest.mark.parametrize(('partial', 'stale', 'expected'), [
    (True, False, ['partial']), (False, True, ['stale']), (True, True, ['partial', 'stale'])])
def test_partial_vs_stale_independent(partial, stale, expected):
    value = snapshot()
    value['tables'][0]['status'] = 'partial' if partial else 'ready'
    result = build(value, {'status': 'stale' if stale else 'fresh'}, diagnostic=True)
    assert result['page_state']['states'] == expected
    assert result['sources'][0]['data_state']['states'] == expected
    assert 'health' not in result['sources'][0]


def test_read_failure_retains_snapshot_and_safe_current_error():
    value = snapshot(status='error', message='FORBIDDEN_SOURCE_NAME')
    result = build(value, {'status': 'error', 'last_error': 'FORBIDDEN_ID'}, diagnostic=True)
    assert result['page_state'] == {'states': ['read_failed'], 'count': None}
    assert result['sources'][0]['last_success'] == '2026-10-10T08:00:00.000+08:00'
    assert result['sources'][0]['last_attempt'] == '2026-10-14T08:00:00.000+08:00'
    assert result['error'] == 'source_read_failed'
    assert 'FORBIDDEN' not in json.dumps(result)
    assert row()['health'] == 'healthy'


def test_mapped_accepted_never_true_even_with_caller_receipt_strings():
    value = snapshot(receipt='approved', verified_by='owner')
    value['tables'][0].update(mapped=True, accepted=True, receipt={'reference': 'trusted'}, fields=[{'field_id': 'SECRET_FIELD'}])
    result = build(value, diagnostic=True)
    assert result['sources'][0]['mapped'] is False
    assert result['sources'][0]['accepted'] is False
    assert result['diagnostic']['receipt_state'] == 'receipt_missing'
    assert 'SECRET_FIELD' not in json.dumps(result)
    assert 'receipt' not in result['sources'][0]


@pytest.mark.parametrize('unknown', [None, -1, True, '0', 2**53])
def test_unknown_counts_absent_not_zero(unknown):
    value = snapshot()
    value['tables'][0].update(count=unknown, whole_table_count=50, view_count=12, excluded_count=0)
    result = row(value)
    assert not any(k in result for k in ('loaded_count', 'whole_table_count', 'view_count', 'excluded_count'))
    assert row()['loaded_count'] == 7


def test_non_diagnostic_output_has_no_ids_names_counts_or_source_inventory():
    value = snapshot()
    result = build(value, {'status': 'fresh'})
    assert result == {'page_state': None, 'sources': []}
    privileged = build(value, diagnostic=True)
    assert privileged['sources'][0]['name'] == 'Authorized source'
    assert privileged['diagnostic']['sources'][0]['table_id'] == 'table-A'
    assert 'table_id' not in privileged['sources'][0]
    assert 'NEVER EMIT' not in json.dumps(privileged)


@pytest.mark.parametrize('deny', [{'authorized': False}, {'authorized': 'true'}, {'status': 'forbidden'}, {'status': 'unauthorized'}])
def test_forbidden_source_leaks_nothing(deny):
    value = snapshot()
    value['tables'].append(dict(value['tables'][0], table_id='HIDDEN_ID', name='HIDDEN_NAME', count=819, **deny))
    result = build(value, diagnostic=True)
    assert len(result['sources']) == 1
    assert 'HIDDEN' not in json.dumps(result)
    assert '819' not in json.dumps(result)
    value.update(deny)
    assert build(value, diagnostic=True) == {'page_state': {'states': ['forbidden']}, 'sources': []}


def test_deterministic_ordering_full_identity_and_duplicate_fail_closed():
    value = snapshot()
    value['tables'] += [dict(value['tables'][0], base_token='base-B'), dict(value['tables'][0], table_id='table-B')]
    original = deepcopy(value)
    result = build(value, diagnostic=True)
    assert len({r['key'] for r in result['sources']}) == 3
    value['tables'].reverse()
    assert build(value, diagnostic=True) == result
    assert value == {**original, 'tables': list(reversed(original['tables']))}
    value['tables'].append(dict(value['tables'][0]))
    assert len(build(value, diagnostic=True)['sources']) == 2
    assert build(value)['page_state']['states'] == ['unknown']


def test_retry_only_existing_authorized_sources_dataset():
    result = row(read_authorized=True)
    assert result['retry_handle'] == {'dataset': 'sources'}
    assert 'retry_handle' not in row(read_authorized='true')
    value = snapshot()
    value['tables'][0]['retry_handle'] = {'dataset': 'roster', 'url': '/wide-scope'}
    assert row(value, read_authorized=True)['retry_handle'] == {'dataset': 'sources'}


def test_empty_visible_read_loading_and_blocked_stay_distinct():
    value = snapshot()
    value['tables'][0]['count'] = 0
    assert build(value)['page_state'] == {'states': ['unknown'], 'count': None}
    assert build(value, {'status': 'refreshing'})['page_state']['states'] == ['loading']
    blocked = build(value, {'status': 'blocked'}, diagnostic=True)
    assert blocked['page_state'] == {'states': ['read_failed'], 'count': None}
    assert blocked['error'] == 'blocked'
    assert blocked['sources'][0]['last_success'] == '2026-10-10T08:00:00.000+08:00'
    value['tables'][0]['pages_read'] = 0
    assert build(value)['page_state']['states'] == ['unknown']


def test_clean_read_page_absent_and_source_healthy_only_from_evidence():
    result = build(snapshot(), {'status': 'fresh'}, diagnostic=True)
    assert result['page_state'] is None
    assert result['sources'][0]['health'] == 'healthy'
    value = snapshot(status='never')
    value['tables'][0]['status'] = 'never'
    assert build(value)['page_state']['states'] == ['unknown']


def test_cross_language_real_frontend_view_model():
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable: cross-language check not-run')
    module = (Path(__file__).resolve().parents[1] / 'frontend/src/sourceHealthView.ts').as_uri()
    value = snapshot()
    value['tables'].append(dict(value['tables'][0], table_id='table-B', last_sync=NEW, status='partial'))
    result = build(value, {'status': 'stale'}, diagnostic=True, read_authorized=True)
    script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {buildSourceHealthView} = await import(process.argv[1]);
const input = JSON.parse(readFileSync(0, 'utf8'));
const view = buildSourceHealthView(input, {diagnosticCapability: true});
assert.deepEqual(view.page.states, ['partial', 'stale']);
assert.equal(view.diagnostic.rows.length, 2);
assert.equal(view.diagnostic.summary.last_success.value, '2026-10-10T08:00:00.000+08:00');
assert.equal(view.diagnostic.rows[0].mapped, false);
assert.equal(view.diagnostic.rows[0].accepted, false);
assert.equal(view.diagnostic.rows[0].source_updated.value, null);
assert.equal(view.diagnostic.rows[0].identifiers.table, null);
assert.deepEqual(view.diagnostic.rows[0].retry.handle, {dataset: 'sources'});
const details = new Map(input.diagnostic.sources.map(s => [s.key, s]));
const merged = {...input, sources: input.sources.map(s => ({...s, ...details.get(s.key)}))};
assert.equal(buildSourceHealthView(merged, {diagnosticCapability: true}).diagnostic.rows[0].identifiers.table !== null, true);
assert.equal(buildSourceHealthView(input, {diagnosticCapability: false}).diagnostic, null);
console.log('real sourceHealthView assertions passed');
'''
    check = subprocess.run([node, '--input-type=module', '-e', script, module], input=json.dumps(result), text=True, capture_output=True, timeout=30)
    assert check.returncode == 0, check.stdout + check.stderr
    assert check.stdout.strip() == 'real sourceHealthView assertions passed'


@pytest.mark.parametrize('freshness', [{}, {'status': 'never'}, {'status': 'unconfigured'}])
def test_unknown_freshness_cannot_claim_healthy(freshness):
    result = build(snapshot(), freshness, diagnostic=True)
    assert result['page_state']['states'] == ['unknown']
    assert result['sources'][0]['data_state']['states'] == ['unknown']
    assert result['sources'][0]['readable'] is True
    assert result['sources'][0]['last_success'] == '2026-10-10T08:00:00.000+08:00'
    assert 'health' not in result['sources'][0]


def test_healthy_and_complete_empty_sources_leave_page_clean():
    value = snapshot()
    value['tables'].append(dict(value['tables'][0], table_id='table-B', count=0))
    result = build(value, {'status': 'fresh'}, diagnostic=True, viewer_filtered=False)
    assert result['page_state'] is None
    assert result['sources'][0]['health'] == 'healthy'
    assert result['sources'][1]['data_state'] == {'states': ['complete_empty'], 'count': 0}


def test_empty_read_without_filter_fact_is_unknown_without_count():
    value = snapshot()
    value['tables'][0]['count'] = 0
    result = build(value, {'status': 'fresh'}, diagnostic=True)
    assert result['page_state'] == {'states': ['unknown'], 'count': None}
    assert result['sources'][0]['data_state'] == {'states': ['unknown'], 'count': None}
    assert 'loaded_count' not in result['sources'][0]


@pytest.mark.parametrize(('viewer_filtered', 'expected'), [
    (False, 'complete_empty'), (True, 'filtered_empty'),
    (None, 'unknown'), ('true', 'unknown'), (0, 'unknown')])
def test_empty_scope_requires_explicit_boolean_filter_fact(viewer_filtered, expected):
    value = snapshot()
    value['tables'][0]['count'] = 0
    result = build(value, {'status': 'fresh'}, diagnostic=True, viewer_filtered=viewer_filtered)
    assert result['page_state'] == {'states': [expected], 'count': None if expected == 'unknown' else 0}
    assert result['sources'][0]['data_state'] == result['page_state']


@pytest.mark.parametrize(('viewer_filtered', 'expected'), [(False, 'complete_empty'), (True, 'filtered_empty')])
def test_all_relevant_empty_sources_aggregate_to_proven_empty(viewer_filtered, expected):
    value = snapshot()
    value['tables'][0]['count'] = 0
    value['tables'].append(dict(value['tables'][0], table_id='table-B'))
    result = build(value, {'status': 'fresh'}, diagnostic=True, viewer_filtered=viewer_filtered)
    assert result['page_state'] == {'states': [expected], 'count': 0}
    assert [r['data_state'] for r in result['sources']] == [result['page_state'], result['page_state']]


@pytest.mark.parametrize('freshness', [{}, {'status': 'unconfigured'}])
def test_empty_with_filter_fact_still_requires_freshness(freshness):
    value = snapshot()
    value['tables'][0]['count'] = 0
    assert build(value, freshness, viewer_filtered=False)['page_state'] == {'states': ['unknown'], 'count': None}


@pytest.mark.parametrize(('status', 'expected'), [('never', ['unknown']), ('partial', ['partial']), ('error', ['read_failed'])])
def test_empty_does_not_override_another_sources_real_state(status, expected):
    value = snapshot()
    value['tables'][0]['status'] = status
    value['tables'].append(dict(snapshot()['tables'][0], table_id='table-B', count=0))
    result = build(value, {'status': 'fresh'}, diagnostic=True, viewer_filtered=False)
    assert result['page_state'] == {'states': expected, 'count': None}
    assert result['sources'][0]['data_state']['states'] == expected


def test_summaries_exclude_dropped_duplicate_and_malformed_identities():
    value = snapshot()
    value['tables'] += [dict(value['tables'][0], table_id='table-B', last_sync=NEW, count=3),
                        dict(value['tables'][0], last_sync='2026-09-01T00:00:00Z', count=999),
                        dict(value['tables'][0], base_token=None, count=998),
                        dict(value['tables'][0], table_id='   ', count=997)]
    result = build(value, {'status': 'fresh'}, diagnostic=True)
    assert result['diagnostic']['last_success'] == '2026-10-14T08:00:00.000+08:00'
    assert [r['loaded_count'] for r in result['sources']] == [3]
    assert [r['table_id'] for r in result['diagnostic']['sources']] == ['table-B']
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable: cross-language summary check not-run')
    module = (Path(__file__).resolve().parents[1] / 'frontend/src/sourceHealthView.ts').as_uri()
    script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {buildSourceHealthView} = await import(process.argv[1]);
const input = JSON.parse(readFileSync(0, 'utf8'));
const view = buildSourceHealthView(input, {diagnosticCapability: true});
assert.equal(view.diagnostic.summary.last_success.value, '2026-10-14T08:00:00.000+08:00');
assert.equal(view.diagnostic.summary.last_success.value, input.diagnostic.last_success);
assert.deepEqual(view.diagnostic.rows.map(r => r.counts.loaded), [3]);
console.log('summary and counts agree');
'''
    check = subprocess.run([node, '--input-type=module', '-e', script, module], input=json.dumps(result), text=True, capture_output=True, timeout=30)
    assert check.returncode == 0, check.stdout + check.stderr
    assert check.stdout.strip() == 'summary and counts agree'


def test_application_blocked_read_retains_diagnostics_and_safe_category():
    value = snapshot()
    freshness = {'status': 'blocked', 'last_error': 'SECRET_SERVICE_403'}
    result = build(value, freshness, diagnostic=True)
    assert result['page_state'] == {'states': ['read_failed'], 'count': None}
    assert result['error'] == 'blocked'
    assert result['sources'][0]['data_state'] == {'states': ['read_failed'], 'count': None}
    assert result['sources'][0]['last_success'] == '2026-10-10T08:00:00.000+08:00'
    assert result['sources'][0]['loaded_count'] == 7
    assert 'SECRET_SERVICE' not in json.dumps(result)
    assert build(value, freshness) == {'page_state': {'states': ['read_failed'], 'count': None}, 'sources': [], 'error': 'blocked'}
    value['authorized'] = False
    assert build(value, freshness, diagnostic=True) == {'page_state': {'states': ['forbidden']}, 'sources': []}


def test_current_read_failed_is_distinct_from_retained_read_evidence():
    result = row(snapshot(status='error'), freshness={'status': 'error'})
    assert result['located'] is True
    assert result['readable'] is True
    assert result['last_success'] == '2026-10-10T08:00:00.000+08:00'
    assert result['data_state'] == {'states': ['read_failed'], 'count': None}
    assert 'health' not in result


@pytest.mark.parametrize(('age', 'expected'), [(59, None), (60, ['stale']), (61, ['stale'])])
def test_age_at_or_above_ttl_is_stale_even_with_fresh_status(age, expected):
    result = build(snapshot(), {'status': 'fresh', 'age_seconds': age, 'ttl_seconds': 60}, diagnostic=True)
    if expected is None:
        assert result['page_state'] is None
        assert result['sources'][0]['health'] == 'healthy'
    else:
        assert result['page_state'] == {'states': expected, 'count': None}
        assert result['sources'][0]['data_state'] == result['page_state']


HISTORICAL = {'last_error': 'SYNTHETIC_PRIOR_FAILURE'}


@pytest.mark.parametrize('base', [{}, {'status': 'refreshing', 'age_seconds': 561600, 'ttl_seconds': 60}])
def test_active_refresh_wins_over_historical_last_error(base):
    freshness = dict(base, status='refreshing', **HISTORICAL)
    result = build(snapshot(), freshness, diagnostic=True)
    assert result['page_state'] == {'states': ['loading'], 'count': None}
    assert 'error' not in result
    # Retained rows are neither healthy nor current while loading.
    assert result['sources'][0]['data_state'] == {'states': ['loading'], 'count': None}
    assert 'health' not in result['sources'][0]
    assert result['sources'][0]['last_success'] == '2026-10-10T08:00:00.000+08:00'
    assert 'SYNTHETIC_PRIOR' not in json.dumps(result)
    assert build(snapshot(), freshness)['page_state'] == {'states': ['loading'], 'count': None}


@pytest.mark.parametrize('freshness', [
    {'status': 'blocked', **HISTORICAL}, {'status': 'error'}, {'status': 'stale', **HISTORICAL}, dict(HISTORICAL)])
def test_failure_without_active_lease_is_read_failed(freshness):
    result = build(snapshot(), freshness, diagnostic=True)
    assert result['page_state'] == {'states': ['read_failed'], 'count': None}
    assert 'health' not in result['sources'][0]


@pytest.mark.parametrize('change', [{'status': 'error'}, {'tables': [dict(snapshot()['tables'][0], status='read_failed')]}])
def test_explicit_error_beats_refreshing(change):
    result = build(snapshot(**change), {'status': 'refreshing'}, diagnostic=True)
    assert result['page_state'] == {'states': ['read_failed'], 'count': None}


@pytest.mark.parametrize('change', [{'status': 'forbidden'}, {'authorized': False}])
def test_forbidden_snapshot_stays_forbidden_while_refreshing(change):
    result = build(snapshot(**change), {'status': 'refreshing', **HISTORICAL}, diagnostic=True)
    assert result == {'page_state': {'states': ['forbidden']}, 'sources': []}


def test_forbidden_table_is_absent_while_refreshing():
    value = snapshot()
    value['tables'].append(dict(value['tables'][0], table_id='table-F', name='HIDDEN_NAME', status='forbidden'))
    text = json.dumps(build(value, {'status': 'refreshing', **HISTORICAL}, diagnostic=True))
    assert 'table-F' not in text and 'HIDDEN_NAME' not in text


@pytest.mark.parametrize('freshness', [
    {'status': 'fresh', 'age_seconds': 561600, 'ttl_seconds': 60}, {'status': 'stale', 'age_seconds': 561600}])
def test_six_and_half_day_old_cache_without_lease_is_never_healthy(freshness):
    result = build(snapshot(), freshness, diagnostic=True)
    assert result['page_state'] == {'states': ['stale'], 'count': None}
    assert result['page_state'] is not None
    assert 'health' not in result['sources'][0]
