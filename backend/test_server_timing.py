import re
import pytest
from .test_backend import app, client, act, workspace  # noqa: F401  (fixtures)

ENTRY = re.compile(r'^[a-z]+;dur=\d+(\.\d+)?$')


def check(response, phases):
    header = response.headers['server-timing']
    entries = [e.strip() for e in header.split(',')]
    assert all(ENTRY.match(e) for e in entries), header
    names = [e.split(';')[0] for e in entries]
    assert set(phases) <= set(names) and names[-1] == 'total'


def test_server_timing_on_instrumented_routes(client):
    for path, phases in (('/api/session', ['identity', 'load', 'serialize']),
                         ('/api/workspace', ['identity', 'load', 'project', 'serialize']),
                         ('/api/projects?limit=10', ['identity', 'load', 'project', 'serialize'])):
        first = client.get(path)
        assert first.status_code == 200
        check(first, phases)
    posted = act(client, 'comment_add', {'body': 'timing'})
    assert posted.status_code == 200
    check(posted, ['identity', 'mutate', 'serialize'])


def test_server_timing_leaves_body_and_gzip_intact(client):
    plain = client.get('/api/workspace', headers={'Accept-Encoding': 'identity'})
    zipped = client.get('/api/workspace', headers={'Accept-Encoding': 'gzip'})
    assert zipped.headers['content-encoding'] == 'gzip' and 'server-timing' in zipped.headers
    assert 'server-timing' in plain.headers
    strip = lambda body: {k: v for k, v in body.items() if k not in ('freshness', 'task_capabilities_checked_at')}
    assert strip(plain.json()) == strip(zipped.json())
    assert 'server-timing' not in client.get('/api/health').headers
