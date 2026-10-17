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


def span_dataset():
    raw=FixtureReader(FIXTURES).read()
    from datetime import datetime
    def ms(s): return int(datetime.fromisoformat(s+'T00:00:00+08:00').timestamp()*1000)
    raw['plan']['records']=[{'record_id':str(i),'fields':{'開始日期':ms(a),'結束日期':ms(b),'業別':'外業','組別':g,'案件':[{'text_arr':['C01','C02','C000000']}],'條類型':t}} for i,(a,b,g,t) in enumerate([
        ('2026-10-11','2026-10-14','水深A組','出工'),('2026-10-12','2026-10-12','水深B組','出工'),
        ('2026-10-15','2026-10-14','水深A組','出工'),('2026-10-16','2026-10-18','水深A組','休假')])]
    return raw


def test_multiday_case_dates_group_normalization_unplanned_and_diff():
    raw=span_dataset();d=c.normalize(raw)
    r=c.progress(d,week='2026-10-12',sort='diff')
    assert r['kpi']['planned_days']==8
    assert r['kpi']['achievement']==1/8
    assert r['kpi']['unplanned_days']==0
    assert [g['group'] for g in r['by_group']]==['水深A','水深B']
    assert c.progress(d,week='2026-10-12',group='水深A組')['kpi']['planned_days']==8
    assert r['items'][0]['diff']==-4
    assert c.progress(d,week='2026-10-05')['kpi']['planned_days']==2
    assert any(g['id']=='plan-negative-span' for g in c.report_gaps(d,'progress'))
    raw['plan']['records']=[]
    r=c.progress(c.normalize(raw),week='2026-10-12')
    assert r['kpi']['unplanned_days']==1 and r['kpi']['achievement'] is None


def test_sales_null_groups_zero_fallback_weighting_outliers_and_remaining():
    raw=FixtureReader(FIXTURES).read()
    raw['case']['records']=[{'record_id':str(i),'fields':f} for i,f in enumerate([
      {'案件編號':'BIG','PM':'A','實際合約金額':0.0,'預期合約金額':1000,'營業額進度':.5},
      {'案件編號':'SMALL','PM':'A','實際合約金額':100,'營業額進度':1},
      {'案件編號':'MISSING','PM':'B'}])]
    d=c.normalize(raw);r=c.sales(d)
    assert r['kpi']['contract_total']==1100
    assert r['by_pm'][0]['progress']==600/1100
    assert r['by_pm'][1]['contract_total'] is None
    assert c.sales(d,pm='B')['by_status'][0]['contract_total'] is None
    messages=' '.join(g['message'] for g in c.report_gaps(d,'sales'))
    assert '1 件實際合約金額為 0，改用預期金額' in messages and 'BIG' in messages
    d=dataset();d['cases']['C01']['f'].update({'預期營業額點數':1,'累計外業營業額點數':20})
    r=c.progress(d,week='2026-10-12')
    assert r['items'][0]['remaining']==-19 and r['kpi']['remaining_points'] is None
    assert any(g['id']=='negative-remaining' for g in r['gaps'])


def test_asset_coverage_invalid_mileage_and_never_used_idle_filter():
    raw=FixtureReader(FIXTURES).read()
    raw['vehicle']['records'].append({'record_id':'unused','fields':{'車牌':'UNUSED'}})
    raw['field_cost']['records'][0]['fields']['結束里程1']=0
    r=c.assets(c.normalize(raw),kind='vehicle',idle_days=14,**{'from':'2026-10-12','to':'2026-10-18'})
    assert [a['id'] for a in r['items']]==['unused']
    assert r['kpi']['mileage_excluded']==1
    assert any('1 / 1 張成本單有車輛紀錄' in g['message'] for g in r['gaps'])


def test_person_group_identity_blank_filter_stable_options_and_status_order():
    raw=FixtureReader(FIXTURES).read();f=raw['field']['records'][0]
    from copy import deepcopy
    blank=deepcopy(f);blank['record_id']='blank'
    for key in ('營業額人員-明細','姓名','此單出工人'): blank['fields'].pop(key,None)
    raw['field']['records'].append(blank)
    d=c.normalize(raw);r=c.review(d,week='2026-10-12')
    assert any(p['person']=='未填' and p['person_key']=='__blank__' for p in r['by_person'])
    assert c.rows_report(d,dept='field',week='2026-10-12',person='__blank__')['total']==1
    assert c.review(d,week='2026-10-12',group='missing')['options']==r['options']
    assert [r['status'] for r in c.rows_report(d,dept='field',week='2026-10-12',sort='status')['items']]==['passed','passed','returned','pending','unset']


def test_unplanned_actual_never_in_achievement_numerator():
    raw=span_dataset()
    raw['field']['records'][0]['fields']['案件編號']='UNPLANNED'
    r=c.progress(c.normalize(raw),week='2026-10-12')
    assert r['kpi']['achievement']==1/8
    assert r['kpi']['unplanned_days']==1
    assert next(x for x in r['items'] if x['case_code']=='UNPLANNED')['achievement'] is None


def test_days_diff_sort_matches_display_and_cross_group_deduplication():
    r=c.progress(c.normalize(span_dataset()),week='2026-10-12',sort='diff',order='desc')
    assert [(x['case_code'],x['diff']) for x in r['items']]==[('C01',-3),('C02',-4)]
    assert sum(g['planned'] for g in r['by_group'])==10
    assert r['kpi']['planned_days']==8


def test_same_person_in_two_groups_has_distinct_ranking_identity():
    raw=FixtureReader(FIXTURES).read()
    raw['field_cost']['records'].append({'record_id':'costB','fields':{'組別':'水深B組'}})
    from copy import deepcopy
    row=deepcopy(raw['field']['records'][0]);row['record_id']='second';row['fields']['所屬成本單']=[{'record_ids':['costB']}]
    raw['field']['records'].append(row)
    result=c.review(c.normalize(raw),week='2026-10-12')
    people=[p for p in result['by_person'] if p['person']=='P01']
    assert {p['group'] for p in people}=={'水深A','水深B'}
    assert len({(p['person_key'],p['group']) for p in people})==2


def test_filter_options_survive_empty_filtered_results():
    d=dataset()
    assert c.sales(d,pm='missing')['options']==c.sales(d)['options']
    params={'kind':'vehicle','from':'2026-10-12','to':'2026-10-18'}
    assert c.assets(d,category='missing',**params)['options']==c.assets(d,**params)['options']
    assert c.progress(d,week='2026-10-12',group='missing')['options']['group']==c.progress(d,week='2026-10-12')['options']['group']
    assert c.progress(d,week='2026-10-12',group='missing')['options']['status']==[]


def test_round2_blank_sales_identity_and_sort():
    raw=FixtureReader(FIXTURES).read()
    raw['case']['records'].append({'record_id':'blank-record','fields':{'實際合約金額':0}})
    d=c.normalize(raw); rows=c.sales(d,sort='code',order='asc')['items']
    assert rows[-1]['id']=='blank-record'
    assert c.sales(d,sort='code',order='desc')['items'][-1]['id']=='blank-record'
    assert rows[-1]['code']=='' and 'blank-record' in rows[-1]['link']
    assert any(g['message']=='1 件案件未填編號' for g in c.report_gaps(d,'sales'))


def test_round2_missing_group_and_blank_options():
    from backend.reports.routes import parameters
    raw=FixtureReader(FIXTURES).read()
    raw['plan']['records'][0]['fields']['組別']=''
    for r in raw['field_cost']['records']: r['fields']['組別']=''
    d=c.normalize(raw)
    assert c.normalize_group('未分組')=='未分組'
    for value in ('','未分組','控制組','水深A組','__blank__','未分組組','A組 組'):
        assert c.normalize_group(c.normalize_group(value))==c.normalize_group(value)
    result=c.progress(d,**parameters('progress',{'week':'2026-10-12','group':'未分組'}))
    assert result['kpi']['planned_days']>0
    assert result['kpi']['actual_days']>0
    assert '__blank__' in result['options']['group']
    assert '' not in result['options']['group']
    assert result['by_group'][0]['matched_days']>=0
    assert c.progress(d,week='2026-10-12',group='__blank__')['total']==result['total']
    assert any(g['id']=='field-group' for g in c.report_gaps(d,'progress'))
    for kind in ('instrument','vehicle'):
        for r in raw[kind]['records']:
            for key in ('狀態','類別','備註'): r['fields'][key]=''
        d=c.normalize(raw)
        args={'kind':kind,'from':'2026-10-12','to':'2026-10-18'}
        result=c.assets(d,**args)
        for key in ('owner','status','category'):
            if '__blank__' in result['options'][key]:
                selected=c.assets(d,**args,**{key:'__blank__'})
                assert selected['total']>0
                assert all(not r[key] for r in selected['items'])
        assert '__blank__' in result['options']['owner']
        if kind=='instrument':
            assert '__blank__' in result['options']['status']
            assert '__blank__' in result['options']['category']


def test_points_report_exposes_achievement_numerator():
    result=c.progress(c.normalize(FixtureReader(FIXTURES).read()),week='2026-10-12')
    assert result['basis']=='points'
    assert result['kpi']['matched_points']==sum(r['matched_points'] for r in result['items'])
    assert result['kpi']['achievement']==result['kpi']['matched_points']/result['kpi']['planned_points']
    for group in result['by_group']:
        if group['planned']:
            assert group['achievement']==group['matched_points']/group['planned']


def test_progress_status_search_counts_and_filtered_totals():
    raw=FixtureReader(FIXTURES).read()
    raw['case']['records'][0]['fields']['狀態']='執行中'
    raw['case']['records'].append({'record_id':'c3','fields':{'案件編號':'ABC','案件名稱':'Alpha','狀態':'已結案'}})
    raw['plan']['records'].append({'record_id':'plan3','fields':{'開始日期':'2026-10-12','業別':'外業','案件':'ABC','預估營業額點數':10}})
    d=c.normalize(raw)
    all_rows=c.progress(d,week='2026-10-12',limit=1)
    assert all_rows['options']['status']==[{'status':'執行中','count':1},{'status':'已結案','count':1}]
    assert sum(x['count'] for x in all_rows['options']['status'])==all_rows['total']==2
    filtered=c.progress(d,week='2026-10-12',status='已結案')
    assert filtered['kpi']['planned_points']==10
    assert filtered['kpi']['actual_points']==0
    assert filtered['total']==1
    assert filtered['options']['status']==all_rows['options']['status']
    assert c.progress(d,week='2026-10-12',q='aLpH')['items'][0]['case_code']=='ABC'
    assert [x['case_code'] for x in c.progress(d,week='2026-10-12',sort='name')['items']]==['ABC','C01']
    assert c.progress(d,week='2026-10-12',scope='open',group='missing')['total']==0


def test_progress_unknown_record_and_payload_budget():
    import json
    from copy import deepcopy
    raw=FixtureReader(FIXTURES).read()
    raw['case']['records']=[]
    unknown=c.progress(c.normalize(raw),week='2026-10-12')['items'][0]
    assert unknown['case_key'] is None and unknown['link'] is None
    raw=FixtureReader(FIXTURES).read()
    original=deepcopy(raw['case']['records'][0])
    raw['case']['records']=[dict(record_id=f'rec{i:014}',fields={**original['fields'],'案件編號':f'C{i:03}','狀態':'執行中'}) for i in range(50)]
    result=c.progress(c.normalize(raw),week='2026-10-12',scope='open')
    baseline=deepcopy(result)
    baseline['options'].pop('status')
    for row in baseline['items']: row.pop('case_key')
    assert len(json.dumps(result).encode())/len(json.dumps(baseline).encode())<1.15
