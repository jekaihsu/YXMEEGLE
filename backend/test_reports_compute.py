from pathlib import Path
from backend.reports import compute as c
from backend.reports.reader import FixtureReader

FIXTURES=Path(__file__).parent/'fixtures'/'reports'

def dataset(): return c.normalize(FixtureReader(FIXTURES).read())

def test_cells_dates_and_numbers():
    assert c.cell([{'text':' 已退回 '}])=='已退回'
    assert c.cell({'text':None,'text_arr':['A','B']})=='A,B'
    assert c.cell({'record_ids':['r1']})=='r1'
    assert c.links([{'record_ids':['r1','r2']}])==['r1','r2']
    assert c.day(46233)=='2026-07-30'
    assert c.day(1791734400000)=='2026-10-12'
    assert c.day('2026-10-12T00:00:00')=='2026-10-12'
    assert c.day('2026-10-11T17:00:00Z')=='2026-10-12'
    assert c.number('nan') is None
    assert c.monday('2026-10-15')=='2026-10-12'


def test_review_rates_groups_flags_and_control():
    d=dataset();result=c.review(d,week='2026-10-12')
    assert result['kpi']==dict(total=4,passed=1,returned=1,pending=1,unset=1,error_rate=.5,pending_rate=.25,coverage=.5)
    assert result['by_group'][0]['group']=='水深A'
    assert result['control']==dict(checked=1,unchecked=1,violated=1)
    office=c.review(d,dept='office',week='2026-10-12')
    assert office['kpi']['error_rate'] is None
    assert office['kpi']['coverage']==0
    assert office['flags']==[dict(flag='⚠案件不符',count=1,share=.5)]
    assert c.review(d,dept='control',week='2026-10-12')['kpi']['total']==1
    assert len(result['trend'])==12
    assert any('1/2' in g['message'] for g in d['gaps'] if g['id']=='office-review-coverage')


def test_rows_filter_page_and_stable_codepoint_sort():
    d=dataset()
    result=c.rows_report(d,dept='field',week='2026-10-12',sort='points',order='desc',offset=0,limit=2)
    assert [r['id'] for r in result['items']]==['f1','f2']
    assert result['total']==4
    assert c.rows_report(d,dept='field',status='returned',flag='違反檢核程序',q='C01')['total']==1
    assert c.rows_report(d,dept='field',person='P01')['total']==4


def test_sales_blanks_assets_links_and_progress():
    d=dataset();sales=c.sales(d)
    assert sales['by_status'][0]['status']=='未填'
    assert sales['kpi']['contract_total']==100
    assert sales['items'][0]['progress_cost']==.2
    assets=c.assets(d,kind='vehicle',**{'from':'2026-10-12','to':'2026-10-18'})
    assert assets['items'][0]['uses']==1
    assert assets['items'][0]['km']==40
    assert assets['items'][0]['idle_days']==6
    instruments=c.assets(d,kind='instrument',**{'from':'2026-10-12','to':'2026-10-18'})
    assert instruments['kpi']['repair']==1
    assert instruments['items'][0]['uses']==1
    progress=c.progress(d,dept='field',week='2026-10-12')
    assert progress['kpi']['planned_points']==8
    assert progress['kpi']['actual_points']==8
    assert progress['items'][0]['achievement']==1
    assert progress['items'][0]['remaining']==12


def test_real_shapes_days_null_sales_and_asset_ownership():
    raw=FixtureReader(FIXTURES).read()
    f=raw['plan']['records'][0]['fields'];f.pop('預估營業額點數');f['案件']=[{'text_arr':['C01','C02','C000000']}]
    raw['case']['records'][0]['fields'].update({'實際合約金額':150,'營業額進度':[{'text':'0.32'}]})
    d=c.normalize(raw);result=c.progress(d,week='2026-10-12')
    assert result['basis']=='days'
    assert result['kpi']['planned_days']==2
    assert result['kpi']['actual_days']==1
    assert result['kpi']['achievement']==.5
    assert {r['case_code'] for r in result['items']}=={'C01','C02'}
    sales=c.sales(d)
    assert sales['kpi']['contract_total']==150
    assert sales['kpi']['billed_total'] is None
    assert sales['kpi']['received_total'] is None
    assert sales['kpi']['unbilled_billable'] is None
    assert sales['items'][0]['progress_revenue']==.32
    assert c.vehicle_owner('詠翔自有')=='自有'
    assert c.vehicle_owner('格上')=='租賃'
    assert c.vehicle_owner('请确认？')=='待確認'
    raw['field_cost']['records'][0]['fields']['結束里程1']=90
    asset=c.assets(c.normalize(raw),kind='vehicle',**{'from':'2026-10-12','to':'2026-10-18'})['items'][0]
    assert asset['uses']==1 and asset['km'] is None
    assert asset['last_used']=='2026-10-12'


def test_vehicle_slots_missing_km_and_unused_assets():
    raw=FixtureReader(FIXTURES).read()
    raw['vehicle']['records'][0]['fields']['第二台車紀錄']=[{'record_ids':['cost2']}]
    raw['vehicle']['records'][0]['fields']['第三台車紀錄']=[{'record_ids':['cost3']}]
    raw['field_cost']['records'].append({'record_id':'cost3','fields':{'工作日期':'2026-10-14','出發里程3':10,'結束里程3':15}})
    raw['field_cost']['records'].append({'record_id':'cost2','fields':{'工作日期':'2026-10-13','出發里程2':30,'結束里程2':37}})
    raw['vehicle']['records'].append({'record_id':'unused','fields':{'車牌':'UNUSED','啟用':True}})
    result=c.assets(c.normalize(raw),kind='vehicle',**{'from':'2026-10-12','to':'2026-10-18'})
    used=next(r for r in result['items'] if r['id']=='v1');unused=next(r for r in result['items'] if r['id']=='unused')
    assert (used['uses'],used['km'],used['last_used'],used['idle_days'])==(3,52,'2026-10-14',4)
    assert unused['last_used'] is None and unused['idle_days'] is None
    assert result['kpi']['in_use']==1 and result['kpi']['idle']==1


def test_progress_open_scope_and_distinct_dates():
    raw=FixtureReader(FIXTURES).read()
    raw['case']['records'].append({'record_id':'c3','fields':{'案件編號':'C03','狀態':'執行中'}})
    d=c.normalize(raw)
    assert c.progress(d,week='2026-10-12')['total']==1
    opened=c.progress(d,week='2026-10-12',scope='open')
    assert opened['total']==2
    assert next(r for r in opened['items'] if r['case_code']=='C03')['remaining'] is None
    assert opened['kpi']['actual_days']==1


def test_polish_gap_scoping_and_unset_sales():
    d=dataset()
    field=c.report_gaps(d,'review','field')
    office=c.report_gaps(d,'review','office')
    assert not any(g['id'].startswith('office') for g in field)
    assert any(g['id']=='office-review-coverage' for g in office)
    for endpoint in ('sales','assets','progress'):
        assert not any(g['id']=='office-review-coverage' for g in c.report_gaps(d,endpoint))
    assert all('field ' not in g['message'] and 'office ' not in g['message'] for g in c.report_gaps(d,'sources'))
    result=c.sales(d,status='未填')
    assert result['total']>0
    assert all(r['status']=='未填' for r in result['items'])
    trend=c.review(d,week='2026-10-12')['trend'][-1]
    assert trend['passed']+trend['returned']==2


def test_gap_department_filters_include_only_relevant_sources():
    d=dataset()
    d['gaps'] += [c.gap('field-date','外業日期缺少 2 筆'),c.gap('office-date','內業日期缺少 3 筆'),c.gap('source-vehicle','車輛來源尚未讀取')]
    for endpoint in ('review','review/rows','progress'):
        field={g['id'] for g in c.report_gaps(d,endpoint,'field')}
        office={g['id'] for g in c.report_gaps(d,endpoint,'office')}
        assert 'field-date' in field and 'office-date' not in field
        assert 'office-date' in office and 'field-date' not in office
        assert 'source-vehicle' not in field|office
    assert 'source-vehicle' in {g['id'] for g in c.report_gaps(d,'assets')}
    assert c.report_gaps(d,'review','control')==c.report_gaps(d,'review','field')
