from concurrent.futures import ThreadPoolExecutor
from .test_node_assignment_start_sop import s, h, NODES, TASKS
from .sop_import.routes import register

URL = '/api/projects/p1/sop/ensure'


def setup(s):
    s.who[0] = 'ou_pm'
    register(s.client.app, identity=lambda _: ({'wid': 'lark-company'}, {'id': s.who[0], 'active': True}),
             load_case=lambda *_: (s.state, s.case['project']), sessions=s.sessions, cfg={})


def test_production_ensure_concurrent_nodes_only(s):
    setup(s)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: s.client.post(URL).json(), range(2)))
    assert sorted(r['state'] for r in results) == ['already_started', 'started']
    assert len(s.fake.rows(NODES)) == 4
    assert len(s.fake.rows(TASKS)) == 0
    assert s.client.post(URL).json() == {'state': 'already_started'}
    assert len(s.fake.rows(NODES)) == 4


def test_production_viewer(s):
    setup(s)
    s.who[0] = 'ou_member'
    response = s.client.post(URL)
    assert response.status_code == 403
    assert response.json()['code'] == 'forbidden'
    assert len(s.fake.rows(NODES)) == 0


def test_production_writes_disabled(s):
    setup(s)
    s.state['settings']['external_enabled'] = False
    assert s.client.post(URL).json() == {'state': 'not_ready', 'reason': 'writes_disabled'}
    assert len(s.fake.rows(NODES)) == 0
