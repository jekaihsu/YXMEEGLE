from scripts import sop_import_examples as examples


def test_generator_confirms_selected_indicator(monkeypatch):
    seen = []
    tasks = [{'id': str(n), 'revision': 1, 'origin': {'source_row_key': f'meegle-v137:A:{n}'},
              'suggestion': {'facts_hash': 'facts'}} for n in (12, 15, 1)]
    def call(client, method, url, body=None, expected=200):
        if method == 'GET': return {'tasks': tasks}
        if url.endswith('/sop-import/preview'): return {'preview_id': 'preview'}
        if url.endswith('/suggestions/accept'):
            seen.append(body)
            assert body['confirmed_task_ids'] == ['15']
        return {}
    monkeypatch.setattr(examples, 'call', call)
    examples.suggestions(None, 'project', 'version')
    assert len(seen) == 1
