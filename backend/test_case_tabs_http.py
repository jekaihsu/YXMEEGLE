"""Case tabs through HTTP, fed by rows shaped like the live V4 and quote Bases (names anonymized)."""
import time
import pytest
from fastapi.testclient import TestClient
from .app import create_app, WorkspaceRow, AuthRow, BusinessRow
from .policy import upgrade
from .seed import seed
from .source_case_policy import apply_source_reference_policy
from .sources import import_sources
from . import storage
from .test_daily_source_shapes import BASE, OUT_COST, OUT_WORK, link, outdoor_rows, row
from .test_case_basic_data import confirmation, quote

CONF, CONTRACT, ITEM = 'tblmSQrcCs9vPQZx', 'tblobs4qPy2w9MZ6', 'tblwQPYk3c9RvCU7'


def c115264_rows():
    contract = row(CONTRACT, 'contract', 'recvsctWu1D17w',
                   {'所屬成案確認單（日報關聯）': link(CONF, 'recvsnzx3bjtAA'), '合約項次': 1, '合約工作項目': '原地形圖及土方數量計算'})
    items = [row(ITEM, 'reporting', rid, {'來源合約明細（日報關聯）': link(CONTRACT, 'recvsctWu1D17w'),
                                           '工項類別': category, '工項名稱': name, '對應營業額': points})
             for rid, category, name, points in (('recItemOut1', '外業', '導線測量1/20000(2測回)', 4.625),
                                                  ('recItemCtl1', '控制', '地形檢查', 1.25),
                                                  ('recItemRpt1', '報告', '服務建議書(有公版)', 0.0025))]
    cost, work = outdoor_rows(所屬案件=link(CONF, 'recvsnzx3bjtAA'), 出工人='組長甲,組員乙,組員丙')
    return [confirmation(), quote('recvs99lJ624pD', '客戶甲'), contract, *items, cost, work]


@pytest.fixture
def http(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/tabs.db', 'UPLOAD_DIR': str(tmp_path / 'files'),
                      'DEMO_MODE': 'false', 'APP_ENV': 'development', 'SESSION_SECRET': 'case-tabs-only' * 4,
                      'LARK_WORKER_ORGANIZATION': 'boundary', 'LARK_ALLOWED_TENANTS': 'boundary',
                      'WORKSPACE_SHELL_ENABLED': 'true', 'INDEX_TABLES_ENABLED': 'true'})
    state = upgrade(seed()); state['environment'] = 'production'
    state['projects'] = []
    rows = c115264_rows()
    import_sources(state, rows)
    apply_source_reference_policy(state, {'records': rows}, {'id': 'u-manager', 'name': 'm'})
    with app.state.sessions.begin() as db:
        workspace = WorkspaceRow(id='lark-boundary', version=state['version'], data={}); db.add(workspace); db.flush()
        workspace.data = storage.save(db, BusinessRow, workspace.id, state)
        db.add(AuthRow(id='tabs-session', data={'wid': workspace.id, 'expires': time.time() + 3600}))
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps(
        {'mode': 'lark', 'sid': 'tabs-session', 'wid': 'lark-boundary', 'uid': 'u-manager'}))
    return client, next(p['id'] for p in state['projects'] if p['code'] == 'C115264')


def test_case_data_tab_gets_the_quote_company(http):
    client, pid = http
    project = client.get(f'/api/projects/{pid}').json()['project']
    assert project['code'] == 'C115264' and project['client'] == '客戶甲'


def test_task_tab_lists_real_work_items_with_source_points_and_leaves_outdoor_to_its_sop(http):
    client, pid = http
    project = client.get(f'/api/projects/{pid}').json()['project']
    imported = {(n['key'], t['title']): t['points'] for n in project['nodes'] for t in n['tasks'] if t.get('source_identity')}
    assert imported == {('control', '地形檢查'): 1.25, ('report', '服務建議書(有公版)'): 0.0025}


def test_daily_tab_shows_the_taipei_date_the_crew_and_an_honest_basis(http):
    client, pid = http
    result = client.get('/api/daily-reports', params={'project_id': pid}).json()
    assert result['total'] == 1
    item = result['items'][0]
    assert (item['date'], item['department'], item['person'], item['points']) == ('2026-07-15', '外業組', '組長甲、組員乙、組員丙', 0.0)
    assert (item['case_code'], item['match_basis'], item['mapping_status']) == ('C115264', 'source_case_or_link', 'ready')
