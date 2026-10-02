from copy import deepcopy
from scripts.formal_data_delta import SUMMARY


def test_directory_heartbeat_is_removed_but_business_change_is_not():
    namespace={};exec(SUMMARY,namespace);summarize=namespace['summarize']
    rows={'workspaces':[{'id':'lark-test','data':{'version':1,'source_status':{'last_sync':'old'}}}],
          'business_records':[{'workspace_id':'lark-test','kind':'users','entity_id':'person','parent_id':'','data':{'id':'person','directory_last_seen_at':'old','role':'member'}}],
          'action_audit':[]}
    baseline=summarize(rows)
    changed=deepcopy(rows);changed['workspaces'][0]['data']['source_status']['last_sync']='new'
    changed['business_records'][0]['data']['directory_last_seen_at']='new'
    result=summarize(changed)
    assert result['normalized_business']==baseline['normalized_business']
    assert result['nonheartbeat_workspace_sha256']==baseline['nonheartbeat_workspace_sha256']
    changed['business_records'][0]['data']['role']='manager'
    assert summarize(changed)['normalized_business']!=baseline['normalized_business']


def test_summary_does_not_return_personal_content():
    namespace={};exec(SUMMARY,namespace)
    rows={'workspaces':[{'id':'lark-test','data':{}}],
          'business_records':[{'workspace_id':'lark-test','kind':'projects','entity_id':'project','parent_id':'','data':{'name':'PRIVATE-CUSTOMER','amount':987654}}],
          'action_audit':[]}
    import json
    result=json.dumps(namespace['summarize'](rows))
    assert 'PRIVATE-CUSTOMER' not in result and '987654' not in result
