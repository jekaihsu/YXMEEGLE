"""Fixed QA definition GET and offline manifest preparation; never create instances."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.lark_adapter import application_adapter, RemoteFailure
from backend.native_approval import verify_definition, form_items
from backend.native_qa import policy, QAError, ensure

APP='cli_aa3cab98b2789e17'
CODE='E1DEFC43-3E29-4238-AD9D-91ACF8E29091'
NAME='詠翔工作台－串接驗收測試'
DIRECTORY=ROOT/'.runtime/native-qa'
REPORT=DIRECTORY/'definition-probe.json'
MANIFEST=DIRECTORY/'config.json'
PEOPLE_REPORT=DIRECTORY/'people-probe.json'
KNOWN_WEN='ou_e80f907476c052605684f9c79528bf4b'


def configuration(path):
    raw=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    cfg=raw.get('variables',{}).get('data',raw)
    ensure(cfg.get('LARK_APP_ID')==APP,'wrong_application')
    ensure(cfg.get('LARK_WORKER_IDENTITY')=='application','application_identity_required')
    tenant=cfg.get('LARK_WORKER_ORGANIZATION')
    ensure(tenant and tenant in {s.strip() for s in cfg.get('LARK_ALLOWED_TENANTS','').split(',')},'wrong_company')
    inventory=json.loads(cfg.get('LARK_NATIVE_APPROVAL_MAPPINGS_JSON','{}'))
    ensure(all(inventory.get(k,{}).get('approval_code') for k in ('node_skip','change','extension','financial')),
           'complete_production_inventory_required')
    codes={v['approval_code'] for v in inventory.values()}
    codes.update(cfg.get(k) for k in ('LARK_CHANGE_APPROVAL_CODE','LARK_EXTENSION_APPROVAL_CODE',
                                     'LARK_NODE_SKIP_APPROVAL_CODE','LARK_FINANCIAL_APPROVAL_CODE'))
    ensure(CODE not in codes,'production_definition_forbidden')
    return cfg


def inspect_definition(value):
    ensure(value.get('approval_name')==NAME,'qa_definition_name_mismatch')
    fields=form_items(value.get('form'))
    ensure(len(fields)==2,'qa_two_fields_required')
    mapping={'kind':'node_skip','approval_code':CODE,'fields':{},'nodes':[]}
    for logical,title in (('binding','驗收識別'),('content','驗收測試內容')):
        matches=[f for f in fields.values() if f.get('name')==title and f.get('type')=='textarea']
        ensure(len(matches)==1,'qa_paragraph_contract_mismatch')
        mapping['fields'][logical]={k:matches[0][k] for k in ('id','name','type')}
    nodes=value.get('node_list')
    ensure(isinstance(nodes,list),'qa_nodes_missing')
    boundary={}
    for role,title in (('start','Submit'),('end','End')):
        matches=[n for n in nodes if n.get('name')==title and n.get('need_approver') is False]
        ensure(len(matches)==1,'qa_boundary_requires_review')
        boundary[role]={'id':matches[0]['node_id'],'name':title}
    mapping['boundary_nodes']=boundary
    ids={b['id'] for b in boundary.values()}
    approvals=[n for n in nodes if n.get('node_id') not in ids]
    ensure(len(approvals)==1,'qa_single_joint_node_required')
    mapping['nodes']=[{'id':approvals[0]['node_id'],'seats':['pm','supervisor']}]
    verify_definition(value,mapping)
    # No admin IDs, people lists, app secrets, form contents or raw remote errors.
    safe={'approval_name':NAME,'status':value['status'],
          'form':json.dumps(list(mapping['fields'].values()),ensure_ascii=False),
          'node_list':[{k:n[k] for k in ('node_id','name','node_type','need_approver',
                       'approver_chosen_multi','custom_node_id','empty_assignee_list','require_signature') if k in n}
                       for n in nodes]}
    verify_definition(safe,mapping)
    return safe,mapping


def manifest_from_report(report,participants,cfg):
    ensure(report.get('definition_code')==CODE and report.get('app_id')==APP
           and report.get('tenant')==cfg['LARK_WORKER_ORGANIZATION'],'qa_probe_identity_mismatch')
    _,mapping=inspect_definition(report['definition'])
    # A locally asserted name is insufficient: root must save fresh same-app identity evidence.
    ensure(participants.get('app_id')==APP and participants.get('tenant')==cfg['LARK_WORKER_ORGANIZATION'],
           'participant_identity_context_mismatch')
    checked=datetime.fromisoformat(participants['verified_at'].replace('Z','+00:00'))
    ensure(checked.tzinfo is not None and 0<=(datetime.now(timezone.utc)-checked).total_seconds()<=3600,
           'fresh_participant_verification_required')
    ensure(isinstance(participants.get('evidence_ref'),str) and participants['evidence_ref'].strip(),
           'participant_evidence_required')
    selected=participants['participants']
    result={'schema_version':1,'purpose':'native_qa_transport_only','app_id':APP,
            'tenant':cfg['LARK_WORKER_ORGANIZATION'],'definition_name':NAME,'mapping':mapping,
            'participants':selected,'authorization':participants['authorization']}
    policy(result,cfg)  # Validates distinct people, exact allowlist, authorization, protected codes.
    return result


def inspect_people(snapshot,cfg):
    from backend.people_directory import BASE,TABLE_ID
    ensure(snapshot.get('complete') is True and snapshot.get('app_id')==APP
           and snapshot.get('base_token')==BASE and snapshot.get('table_id')==TABLE_ID,
           'same_app_complete_directory_required')
    chosen={}
    for seat,name in (('pm','文乃毅'),('supervisor','鍾智偉')):
        matches=[p for p in snapshot['people'] if p.get('name')==name]
        ensure(len(matches)==1 and matches[0].get('employment_status')=='employed',
               'qa_candidate_missing_duplicate_or_not_employed')
        person=matches[0]
        if seat=='pm':ensure(person['id']==KNOWN_WEN,'known_workbench_identity_mismatch')
        chosen[seat]={k:person[k] for k in ('id','name','record_id','employment_status')}
    ensure(chosen['pm']['id']!=chosen['supervisor']['id'],'qa_distinct_people_required')
    return {'app_id':APP,'tenant':cfg['LARK_WORKER_ORGANIZATION'],'verified_at':snapshot['fetched_at'],
            'source_count':snapshot['source_count'],'complete':True,'selected_fields':snapshot['selected_fields'],
            'candidates':chosen,'qa_seats_only':True,'formal_role_assignment':False,
            'remote_business_writes':False,'database_access':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-config',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('probe',help='Authenticate dedicated app and GET only the fixed QA definition')
    commands.add_parser('people',help='Read the approved same-app four-column roster; no DB sync or writes')
    command=commands.add_parser('manifest',help='Offline only; requires an existing probe and fresh participant evidence')
    command.add_argument('--participants',required=True)
    args=parser.parse_args(argv)
    try:
        cfg=configuration(args.saved_config)
        ensure(Path(args.saved_config).resolve() not in (REPORT.resolve(),MANIFEST.resolve(),PEOPLE_REPORT.resolve()),'configuration_output_collision')
        DIRECTORY.mkdir(parents=True,exist_ok=True)
        if args.command=='people':
            from backend.people_directory import fetch_directory
            adapter=application_adapter(cfg)
            try:result=inspect_people(fetch_directory(adapter,APP),cfg)
            finally:adapter.client.close()
            PEOPLE_REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'ok':True,'report':str(PEOPLE_REPORT),'source_count':result['source_count'],
                              'candidate_names':[p['name'] for p in result['candidates'].values()],
                              'candidate_count':len(result['candidates']),'remote_business_writes':False},ensure_ascii=False))
        elif args.command=='probe':
            adapter=application_adapter(cfg)
            try:
                actual=adapter.request('GET','/approval/v4/approvals/'+CODE,
                                       params={'user_id_type':'open_id','with_admin_id':'false'})
                safe,mapping=inspect_definition(actual)
            finally:adapter.client.close()
            result={'app_id':APP,'tenant':cfg['LARK_WORKER_ORGANIZATION'],'definition_code':CODE,
                    'checked_at':datetime.now(timezone.utc).isoformat(),'definition':safe,'mapping':mapping,
                    'remote_business_writes':False,'instance_access':False}
            REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'ok':True,'report':str(REPORT),'definition':safe,'remote_business_writes':False},ensure_ascii=False))
        else:
            ensure(Path(args.participants).resolve()!=MANIFEST.resolve(),'participant_output_collision')
            result=manifest_from_report(json.loads(REPORT.read_text(encoding='utf-8')),
                json.loads(Path(args.participants).read_text(encoding='utf-8-sig')),cfg)
            # Never overwrite an existing run policy or silently change an attempted UUID's manifest.
            with MANIFEST.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
            print(json.dumps({'ok':True,'manifest':str(MANIFEST),'network_accessed':False,'business_apply_allowed':False}))
        return 0
    except QAError as exc:code=str(exc)
    except FileExistsError:code='existing_manifest_preserved'
    except RemoteFailure:code='remote_definition_not_verified'
    except Exception:code='invalid_configuration_or_probe'
    print(json.dumps({'ok':False,'error':code,'remote_business_writes':False}))
    return 1


if __name__=='__main__':raise SystemExit(main())
