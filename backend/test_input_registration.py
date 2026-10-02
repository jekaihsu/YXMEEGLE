from copy import deepcopy
import pytest
from .input_registration import FIELD_NAMES,make_plan,RegistrationAdapter
from .lark_adapter import RemoteFailure


def fixture():
    destination={'base_token':'dedicated','table_id':'table','fields':{
        key:{'field_id':'fld'+key,'field_name':name} for key,name in FIELD_NAMES.items()}}
    plan=make_plan('lark-company',{'id':'p','code':'115001'},{'id':'n'},
        {'id':'r','project_id':'p','node_id':'n','actor_id':'ou_verified','created_at':'2026-09-29',
         'mapping_id':'m','value':{'text':'交付成果'}},destination)
    return plan,{'base_token':'dedicated','table_id':'table','simulated':False}


class Fake:
    def __init__(self,plan):
        self.plan=plan;self.calls=[];self.rows=[];self.timeout=False;self.lost=False;self.bad_fields=False
    def request(self,method,path,**kwargs):
        self.calls.append((method,path,kwargs))
        if path.endswith('/fields'):
            return {'items':[dict(f,type=2 if self.bad_fields else 1) for f in self.plan['destination']['fields'].values()],'has_more':False}
        if path.endswith('/search'):
            assert method=='POST'
            condition=kwargs['json']['filter']['conditions'][0]
            assert condition=={'field_name':FIELD_NAMES['registration_key'],'operator':'is','value':[self.plan['values']['registration_key']]}
            assert set(kwargs['json']['field_names'])==set(FIELD_NAMES.values())
            return {'items':[deepcopy(row) for row in self.rows if row['fields'].get(FIELD_NAMES['registration_key'])==condition['value'][0]],'has_more':False}
        if method=='GET':return {'items':deepcopy(self.rows)}
        assert method=='POST'
        if not self.lost:self.rows.append({'record_id':'recCreated','fields':deepcopy(kwargs['json']['fields'])})
        if self.timeout:raise RemoteFailure('timeout','outcome_unknown')
        return {'record':{'record_id':'recCreated'}}


def is_write(call):
    return call[0] not in ('GET','HEAD') and not (call[0]=='POST' and call[1].endswith('/records/search'))


def test_append_verified_and_repeated_submission_reads_without_another_write():
    plan,policy=fixture();fake=Fake(plan);adapter=RegistrationAdapter(fake)
    receipt=adapter.submit(plan,policy)
    assert receipt['verified'] and receipt['record_id']=='recCreated'
    assert adapter.submit(plan,policy)==receipt
    assert sum(map(is_write,fake.calls))==1
    assert all(c[0] in ('GET','POST') for c in fake.calls)


def test_live_empty_table_shape_allows_one_append_then_verified_readback():
    plan,policy=fixture()
    class EmptyShape(Fake):
        def request(self,method,path,**kwargs):
            result=super().request(method,path,**kwargs)
            if path.endswith('/records/search') and not self.rows:
                return {'has_more':False,'total':0}  # live GET 2026-09-29
            return result
    fake=EmptyShape(plan)
    assert RegistrationAdapter(fake).submit(plan,policy)['verified']
    assert sum(map(is_write,fake.calls))==1
    fake.rows=[]
    start=len(fake.calls)
    with pytest.raises(RemoteFailure) as caught:RegistrationAdapter(fake).reconcile(plan,policy)
    assert caught.value.status=='outcome_unknown'
    assert not any(map(is_write,fake.calls[start:]))


@pytest.mark.parametrize('shape',[
    {'items':[]},{'items':[],'has_more':None},{'items':[],'has_more':0},
    {'items':[],'has_more':'false'},{'items':[],'has_more':False,'page_token':'next'},
    {'items':[None],'has_more':False},{'items':[{'fields':[]}],'has_more':False},
    {},{'has_more':False},{'total':0},{'has_more':True,'total':0},
    {'has_more':False,'total':1},{'has_more':False,'total':False},
    {'has_more':False,'total':'0'},{'has_more':False,'total':0,'items':None},
    {'has_more':False,'total':0,'page_token':'next'},
])
def test_ambiguous_missing_items_still_blocks_before_create(shape):
    plan,policy=fixture()
    class Broken(Fake):
        def request(self,method,path,**kwargs):
            result=super().request(method,path,**kwargs)
            return shape if path.endswith('/records/search') else result
    fake=Broken(plan)
    with pytest.raises(RemoteFailure) as caught:RegistrationAdapter(fake).submit(plan,policy)
    assert caught.value.status=='blocked'
    assert not any(map(is_write,fake.calls))


def test_missing_items_on_later_page_is_not_an_empty_table():
    plan,policy=fixture()
    class Broken(Fake):
        def request(self,method,path,**kwargs):
            result=super().request(method,path,**kwargs)
            if path.endswith('/records/search'):
                return {'has_more':False,'total':0} if kwargs['params'].get('page_token') else {'items':[],'has_more':True,'page_token':'next'}
            return result
    fake=Broken(plan)
    with pytest.raises(RemoteFailure) as caught:RegistrationAdapter(fake).submit(plan,policy)
    assert caught.value.status=='blocked'
    assert not any(map(is_write,fake.calls))


def test_timeout_after_actual_write_recovers_only_by_readback():
    plan,policy=fixture();fake=Fake(plan);fake.timeout=True
    assert RegistrationAdapter(fake).submit(plan,policy)['verified']
    assert sum(map(is_write,fake.calls))==1


def test_unknown_absent_record_never_creates_during_reconciliation():
    plan,policy=fixture();fake=Fake(plan);fake.timeout=True;fake.lost=True
    adapter=RegistrationAdapter(fake)
    with pytest.raises(RemoteFailure) as caught:adapter.submit(plan,policy)
    assert caught.value.status=='outcome_unknown'
    count=len(fake.calls)
    with pytest.raises(RemoteFailure) as caught:adapter.reconcile(plan,policy)
    assert caught.value.status=='outcome_unknown'
    assert not any(map(is_write,fake.calls[count:]))


@pytest.mark.parametrize('mutation',['duplicate','changed'])
def test_duplicate_or_conflicting_existing_registration_cannot_overwrite(mutation):
    plan,policy=fixture();fake=Fake(plan);adapter=RegistrationAdapter(fake);adapter.submit(plan,policy)
    if mutation=='duplicate':fake.rows.append(deepcopy(fake.rows[0]))
    else:fake.rows[0]['fields'][FIELD_NAMES['content_json']]='外部改版'
    count=len(fake.calls)
    with pytest.raises(RemoteFailure) as caught:adapter.submit(plan,policy)
    assert caught.value.status=='conflict' and not any(map(is_write,fake.calls[count:]))


@pytest.mark.parametrize('mutation',['plan','destination','schema','salary','v3'])
def test_unapproved_or_mutated_input_contract_blocks_before_write(mutation):
    from .input_registration import fingerprint
    plan,policy=fixture();fake=Fake(plan)
    if mutation=='plan':plan['values']['actor_id']='forged'
    elif mutation=='destination':policy['table_id']='wrong'
    elif mutation=='schema':fake.bad_fields=True
    else:
        target='VwAsbezz9app3YsramgjduLYp2U' if mutation=='salary' else 'Sdw1bG1djaHsVGsRPvmjyVWipgg'
        plan['destination']['base_token']=target;policy['base_token']=target
        plan['plan_hash']=fingerprint({k:v for k,v in plan.items() if k!='plan_hash'})
    with pytest.raises(RemoteFailure):RegistrationAdapter(fake).submit(plan,policy)
    assert all(c[0]=='GET' for c in fake.calls)
