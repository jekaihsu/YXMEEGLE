"""Approved v0.6 defaults. Published copies are immutable workspace records."""
from copy import deepcopy

VERSION = '2026-09-28.1'
TECHNICAL = {'field', 'control', 'mapping', 'report'}
FINANCIAL = {'pricing', 'settlement'}
CAPABILITIES = ['manage_people','publish_sop','edit_sop','manage_sources','finance_approve','finance_edit','calendar_edit','issue_confirmation','review_mapping','manage_handover','manage_training','approve_capability']
MANAGER_CAPABILITIES = [cap for cap in CAPABILITIES if cap != 'approve_capability']
REQUIREMENTS = {
 'sales': [('demand','業主需求日期與佐證'),('quote','報價單、提出日期及通知紀錄'),('signed','回簽報價單或合約')],
 'pm': [('assignment','各組負責人與核定排程')],
 'confirmation': [('confirmation','核定確認單、工項分組及收件單位'),('group_acceptance','各組確認紀錄')],
 'field': [('dispatch','派工及聯繫紀錄'),('field_report','完工或階段報告'),('permits','適用行政公務辦妥證明')],
 'control': [('deliverable','控制成果、交付數量與日期')],
 'mapping': [('deliverable','圖資成果、交付數量與日期')],
 'report': [('deliverable','報告成果、交付數量與日期')],
 'pricing': [('pricing','計價單'),('client_acceptance','交付與業主確認證據'),('billing_conditions','合約請款條件證據'),('invoice','請款證明')],
 'settlement': [('payments','實際收付款證據'),('settlement','案件結算表'),('closure','結案證明'),('meeting','結案會議紀錄'),('survey','滿意度調查發送證據與回覆狀態')],
}
TITLES = {
 'sales':['業主需求與報價編號','提出報價並通知業主','報價追蹤與回簽'],
 'pm':['指定各組負責人','核定跨組排程','檢核案件電子資料夾'],
 'confirmation':['製作與核定確認單','正式發出並交接 PM','各組確認與修正'],
 'field':['派工前聯繫','外業作業','完工或階段性交付'],
 'control':['控制作業與日報','控制成果及計價數量交付'],
 'mapping':['圖資作業與日報','圖資成果及計價數量交付'],
 'report':['報告編製與日報','報告成果及計價數量交付'],
 'pricing':['核對成果及計價數量','業主確認及請款條件','分批請款'],
 'settlement':['實收與下包付款核對','結算表資料','結案與滿意度調查'],
}

# Stable identities for the already-approved grouped tasks. These are NOT a
# claim that the entire Meegle library/topology has been discovered.
TASK_KEYS={
 'sales':['demand_quote','quote_provide','quote_followup'], 'pm':['assign_owners','approve_schedule','project_folder'],
 'confirmation':['prepare_confirmation','issue_handoff','group_confirmation'],
 'field':['dispatch_prerequisites','field_daily','field_delivery'],
 'control':['control_daily','control_delivery'], 'mapping':['mapping_daily','mapping_delivery'],
 'report':['report_daily','report_delivery'], 'pricing':['pricing_quantity','billing_conditions','billing_batches'],
 'settlement':['payment_reconciliation','settlement_documents','closure_survey'],
}
SOURCE_NODES={
 'demand_quote':['state_14','state_26'], 'quote_provide':['state_15'], 'quote_followup':['state_16','state_25','state_28','state_17'],
 'prepare_confirmation':['state_83','state_4'], 'issue_handoff':['state_4'], 'group_confirmation':['state_39','state_38','state_41'],
 'dispatch_prerequisites':['state_40'], 'field_daily':['state_42','state_78','state_43'], 'field_delivery':['state_44'],
 'control_daily':['state_75'], 'mapping_daily':['state_76'], 'report_daily':['state_77'],
 'control_delivery':['state_47'],'mapping_delivery':['state_47'],'report_delivery':['state_47'],
 'pricing_quantity':['state_55'],'billing_conditions':['state_48','state_56','state_74'],'billing_batches':['state_59'],
 'payment_reconciliation':['state_60','state_72','state_68','state_71'],'settlement_documents':['state_69'],'closure_survey':['state_59','state_70'],
}

def template():
    from .sop_contracts import VERSION as CONTRACT_VERSION, enrich_definition, approved_definitions
    nodes=[]
    for key,titles in TITLES.items():
        definitions=[enrich_definition({'key':task_key,'title':title,'source_node_ids':SOURCE_NODES.get(task_key,[]),
          'source_scope':'template334662-v137' if task_key in SOURCE_NODES else 'approved-local-rule'})
          for task_key,title in zip(TASK_KEYS[key],titles)]
        approved=approved_definitions(key)
        definitions.extend(d for d in approved if d['applicability']=='always')
        nodes.append({'key':key,'tasks':[d['title']for d in definitions],'task_definitions':definitions,
          'deferred_task_definitions':[d for d in approved if d['applicability']!='always'],
          'requirements':[{'key':k,'label':label}for k,label in REQUIREMENTS[key]],'review_mode':'all'})
    return {'id':CONTRACT_VERSION,'version':2,'name':'詠翔核定 SOP（來源契約版）','status':'published',
      'basis':'兩份 Meegle 範本＋四 PDF＋核定決策；條件拓樸完整執行等價尚待驗證',
      'coverage_status':'partial_inventory','runtime_mapping_status':'approved_D4_D5_additions',
      'conditional_defaults_status':'awaiting_authorized_applicability_interface','contract_version':CONTRACT_VERSION,'nodes':nodes}

def defaults():
    return {'timezone':'Asia/Taipei','digest_time':'09:00','cutoff_time':None,'deadline_basis':'scheduled_shift','source_sync_seconds':300,'field_weekday':2,'indoor_weekday':3,'review_weekday':4,'monthly_workday':5,'followup_workdays':5,'daily_backup_days':30,'monthly_backup_months':12,'rpo_hours':24,'rto_hours':8,'external_enabled':False,'drive_root':'','input_base':'','input_table':'','v4_base':'H7W6b0PFWaVF1BsgqXJj3pQ9pXb','quote_base':'JoOqbggsVar0ATsVgbcjh6IIp1g','capability_base':'VwAsbezz9app3YsramgjduLYp2U','test_base':'','test_input_table':'','test_drive_root':'','test_connection_mode':'simulation'}

def upgrade(ws):
    ws.setdefault('policy_version',VERSION)
    ws.setdefault('settings',defaults())
    if 'deadline_basis' not in ws['settings']:
        ws['settings']['legacy_cutoff_time']=ws['settings'].get('cutoff_time')
        ws['settings']['cutoff_time']=None
    for k,v in defaults().items(): ws['settings'].setdefault(k,v)
    candidate=template()
    requirements={node['key']:node['requirements'] for node in candidate['nodes']}
    ws.setdefault('sop_templates',[candidate])
    from .sop_contracts import ensure_draft_candidate
    ensure_draft_candidate(ws,candidate)
    ws.setdefault('node_skip_requests',[])
    for k in ('delegations','jobs','recurring','input_mappings','input_revisions','cost_allocations','daily_unmatched','daily_reviews','handover_requests','sop_requests','archived_projects','training_plans','capability_catalog','capability_awards','learning_standards','work_schedules','approved_leave_delegations','capability_bindings','learning_mappings'):
        ws.setdefault(k,[])
    for u in ws['users']:
        u.setdefault('active',True); u.setdefault('capabilities',MANAGER_CAPABILITIES[:] if u.get('role')=='manager' else [])
        u.setdefault('default_workspace','test' if u.get('role')=='manager' else 'production')
    for p in ws['projects']:
        p.setdefault('execution_status','pending'); p.setdefault('sop_version',VERSION)
        p.setdefault('admin_id',''); p.setdefault('supervisor_id',''); p.setdefault('issuer_ids',[])
        p.setdefault('quotation_id',''); p.setdefault('assistant_id','')
        p.setdefault('evidence',[]); p.setdefault('finance_versions',[]); p.setdefault('payment_batches',[])
        p.setdefault('delivery_batches',[]); p.setdefault('quotes',[]); p.setdefault('quote_reviews',[])
        p.setdefault('issues',[]); p.setdefault('handoffs',[]); p.setdefault('confirmation_issues',[])
        for n in p['nodes']:
            if 'requirements' not in n:
                n['requirements']=deepcopy(requirements.get(n['key'],[]))
            n.setdefault('review_mode','all'); n.setdefault('reviewers',[]); n.setdefault('supervisor_id','')
            n.setdefault('review_cycles',[])
    return ws
