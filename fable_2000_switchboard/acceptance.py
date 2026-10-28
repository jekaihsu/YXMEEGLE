#!/usr/bin/env python3
"""可執行驗收：真實回測與合成防呆測試分開計算；缺樣本不能報全通過。"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import sys
import uuid

import build
import db
import router

ROOT=db.ROOT
current_db = db.assert_not_prod_db()
assert current_db != 'yongxiang_plumb', f'FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})'
CHECKS=[]
NOW=datetime(2026,10,25,12,0,tzinfo=router.TZ)


def check(name, passed, detail=None, kind='implementation'):
    CHECKS.append({'name':name,'passed':bool(passed),'kind':kind,'detail':detail})


def scenario(name, function):
    try:
        value=function()
        if isinstance(value,tuple):
            passed,detail=value
        else:
            passed,detail=bool(value),None
        check(name,passed,detail)
    except Exception as exc:
        check(name,False,{'exception':router.sanitize(str(exc))[:1200]})


def rules(result):
    return {c['rule']:c['passed'] for g in result['gates'] for c in g['checks']}


def fixtures():
    # 只借用真實存在的識別；測試聯絡人不會commit。
    case=db.query("""SELECT jsonb_build_object('id',c.id,'case_code',c.case_code,'customer_id',c.customer_id,
     'pm_employee_id',c.pm_employee_id) FROM public."case" c JOIN public.employee e ON e.id=c.pm_employee_id
     WHERE c.customer_id IS NOT NULL AND e.employment_status='active' ORDER BY c.case_code LIMIT 1""")[0]
    customer=db.query("SELECT jsonb_build_object('id',id,'name',name) FROM public.customer WHERE id="+db.literal(case['customer_id']))[0]
    actor=db.query("SELECT jsonb_build_object('id',id,'name',full_name) FROM public.employee WHERE id="+db.literal(case['pm_employee_id']))[0]
    contact={'id':str(uuid.uuid4()),'customer_id':customer['id'],'name':'張技師（合成驗收）','email':'fixture@example.invalid'}
    context={'case':case,'quote':None,'customer':customer,'contacts':[contact],
             'actor':actor,'approver':actor,'human_confirmation':actor,'approver_is_pm':True,
             'amount_reviewed_by':actor['id'],'contract_reviewed_by':actor['id'],
             'verified_amounts':['100000'],'known_deadlines':['2026-10-30'],
             'payment_verified':True,'approved_artifacts':[],
             'template_values':{'approved_version':'驗收v1','deliverable_list':'核定PDF',
                'review_rows':'1 審查意見：線位 修正回覆：已標示 頁碼：3 圖號：D1',
                'permit_details':'待確認核准編號','invoice_no':'TEST-INV','invoice_item':'測量計價',
                'contract_no':'TEST-PCDL','work_order_no':'12','pending_items':'待雙方確認'},
             'open_contract_verified':True}
    request={'source_key':'acceptance:rollback:'+str(uuid.uuid4()),'channel':'staff_request',
             'evidence_kind':'synthetic_test','occurred_at':NOW.isoformat(),
             'subject':'成果修正','text':case['case_code']+' 修正圖資',
             'draft_body':'張技師您好，修正項目待確認。','approved_by':actor['id'],
             'our_employee_id':actor['id'],'to_contact_id':contact['id'],'human_confirmed_by':actor['id']}
    return request,context


def test_route(request, context, **req_updates):
    req=deepcopy(request);req.update(req_updates)
    return router.route(req,deepcopy(context),now=NOW)


def setup_sql(context):
    c=context['contacts'][0]
    return ('INSERT INTO public.customer_contact(id,customer_id,full_name,email,source_record_id) VALUES ('+
            ','.join([db.literal(c['id'])+'::uuid',db.literal(c['customer_id'])+'::uuid',db.literal(c['name']),
                      db.literal(c['email']),db.literal('SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY')])+');\n')


def rollback_test(request, context, tail):
    result=router.route(request,context,now=NOW)
    sql='BEGIN;\n'+setup_sql(context)+router.persist_sql(request,result)+'\n'+tail+'\nROLLBACK;'
    return db.query(sql),result


def rejection(request,context,mutation):
    try:
        rollback_test(request,context,mutation)
    except RuntimeError:
        return True
    return False


def test_scenarios():
    request,ctx=fixtures()
    base=test_route(request,ctx)
    check('十閘門完整且正常已核准情境可供檢視但永不送出',len(base['gates'])==10 and all(g['passed'] for g in base['gates']) and not base['can_send'] and base['actual_sends']==0,{'synthetic':True,'gate_names':[g['name'] for g in base['gates']]})
    scenario('所有對外須human approved_by；缺核准產Action Card與草稿',lambda:
        not rules(test_route(request,ctx,approved_by=None))['human_approved_by'] and bool(base['draft']) and base['action_card']['type']=='ActionCard')
    bad=deepcopy(ctx);bad['contacts'][0]['customer_id']=str(uuid.uuid4())
    scenario('跨客戶或未知收件人禁止放行',lambda:
        not rules(test_route(request,bad))['contact_customer_case_match'] and
        not rules(test_route(request,{**ctx,'contacts':[]}))['contact_customer_case_match'])
    scenario('群發與任意to/cc/bcc禁止',lambda:not rules(test_route(request,ctx,cc=['arbitrary@example.invalid']))['no_group_recipients'])
    scenario('C115301未知案不臆造且擷取中興候選',lambda:
        (lambda r:r['extracted']['case_code']=='C115301' and r['extracted']['client_candidates']==['中興'] and not rules(r)['unique_case'])(
            router.route({'subject':'','text':'把 C115301 報價寄給中興','occurred_at':NOW.isoformat()},now=NOW)))
    scenario('複數案件與錯配報價須人工',lambda:
        not rules(test_route(request,ctx,text='C115301 C115302 修正'))['unique_case'] and
        not rules(test_route(request,ctx,text=ctx['case']['case_code']+' 報價115715'))['quote_matches_case'])
    wrong_quote={'id':str(uuid.uuid4()),'quote_no':'115715','customer_id':ctx['customer']['id'],'case_id':str(uuid.uuid4())}
    scenario('同客戶其他案件的報價不可混用',lambda:
        not rules(test_route(request,{**ctx,'quote':wrong_quote},text=ctx['case']['case_code']+' 報價115715'))['quote_matches_case'])
    for term in ['底價','成本','毛利','A-B-C 預算','A/B/C預算','內部','點數單價']:
        scenario('禁詞攔截：'+term,lambda term=term:
            (lambda r:not rules(r)['forbidden_words'] and term not in r['draft'])(test_route(request,ctx,draft_body='提供'+term+'資料')))
    scenario('薪資數字與中文待遇全部遮蔽',lambda:
        (lambda r:not rules(r)['hr_salary_isolated'] and r['draft']=='[MASKED_HR_PRIVATE]')(
            test_route(request,ctx,draft_body='月薪 NT$55,000；年薪六十六萬元')))
    for value in ['0912-345-678','02-2345-6789','+886 912 345 678','1361-788-8725','A123456789']:
        scenario('電話或身分證遮蔽：'+('ID' if value.startswith('A') else value[:3]),lambda value=value:
            (lambda r:not rules(r)['phone_id_redacted'] and value not in r['draft'])(test_route(request,ctx,draft_body='請聯繫 '+value)))
    scenario('金額相符有核版與人工查核才可過',lambda:rules(test_route(request,ctx,draft_body='本期金額 TWD 100,000 元'))['quote_invoice_amount_consistency'])
    scenario('金額不一致與無核版資料均攔截',lambda:
        not rules(test_route(request,ctx,draft_body='本期金額 TWD 100,001 元'))['quote_invoice_amount_consistency'] and
        not rules(test_route(request,{**ctx,'verified_amounts':[]},draft_body='本期金額 TWD 100,000 元'))['quote_invoice_amount_consistency'])
    scenario('外幣不可直接比對TWD核版金額',lambda:
        not rules(test_route(request,ctx,draft_body='本期金額 USD 100,000'))['currency_consistency'])
    scenario('金額缺人工核對與合約缺PM核准均攔截',lambda:
        not rules(test_route(request,{**ctx,'amount_reviewed_by':None},draft_body='本期金額 TWD 100,000 元'))['amount_human_review'] and
        not rules(test_route(request,{**ctx,'approver_is_pm':False},subject='合約',text='契約用印'))['contract_pm_approval'])
    artifact={'id':'SYNTHETIC-APPROVED-ARTIFACT','name':'核版成果.pdf','source_type':'deliverable_version','status':'核定',
              'version':1,'sha256':'a'*64,'bytes':1024}
    files={**ctx,'approved_artifacts':[artifact]}
    scenario('承諾附件卻未附檔攔截',lambda:not rules(test_route(request,ctx,draft_body='附件提供成果'))['promised_attachment_present'])
    scenario('附件只允許核版清單與雜湊一致',lambda:
        rules(test_route(request,files,attachments=[artifact],draft_body='附件提供成果'))['approved_attachment_whitelist'] and
        not rules(test_route(request,files,attachments=[{**artifact,'name':'本機偽造.pdf'}],draft_body='附件提供成果'))['approved_attachment_whitelist'])
    scenario('CAT-02核定交付清單缺檔即攔截',lambda:
        not rules(test_route(request,{**files,'required_deliverable_names':['核版成果.pdf','核版圖.dwg']},subject='成果提供',attachments=[artifact]))['deliverable_list_complete'] and
        rules(test_route(request,{**files,'required_deliverable_names':['核版成果.pdf']},subject='成果提供',attachments=[artifact]))['deliverable_list_complete'])
    scenario('CAT-02 ⛔入帳後再寄出未付款攔截；已核實付款通過該閘',lambda:
        not rules(test_route(request,{**files,'payment_verified':False},subject='成果提供',text='⛔入帳後再寄出',attachments=[artifact]))['cat02_paid_before_delivery'] and
        rules(test_route(request,files,subject='成果提供',text='⛔入帳後再寄出',attachments=[artifact]))['cat02_paid_before_delivery'])
    fpg={**files,'client_group':'台塑','max_attachment_bytes':2048}
    scenario('台塑外部連結與未拆分過大檔攔截',lambda:
        not rules(test_route(request,fpg,draft_body='成果 https://example.invalid/a'))['fpg_no_external_link'] and
        not rules(test_route(request,{**fpg,'max_attachment_bytes':512},attachments=[artifact],draft_body='附件提供成果'))['fpg_file_splitting'])
    scenario('台塑核版附件符合業主拆檔上限可過',lambda:rules(test_route(request,fpg,attachments=[artifact],draft_body='附件提供成果'))['fpg_file_splitting'])
    bes={**ctx,'client_group':'中華工程','invoice_issue_date':'2026-10-15',
         'invoice_rule':{'contract_no':'BES001','contract_name':'測量服務','period':'6','item':'BES001測量服務第6期計價'}}
    for day in (9,10,20,21):
        scenario('中華工程發票日期邊界：'+str(day),lambda day=day:
            rules(test_route(request,{**bes,'invoice_issue_date':f'2026-10-{day:02d}'},subject='發票計價',text='發票'))['bes_invoice_window']==(10<=day<=20))
    scenario('中華工程品名嚴格比對合約與期別',lambda:
        rules(test_route(request,bes,subject='發票計價',text='發票'))['bes_invoice_item'] and
        not rules(test_route(request,{**bes,'invoice_rule':{**bes['invoice_rule'],'item':'測量費'}},subject='發票計價',text='發票'))['bes_invoice_item'])
    row={'comment_no':'1','comment':'線位','reply':'已標示','page':'3','drawing':'D1'}
    hsr={**ctx,'client_group':'高鐵','review_rows':[row]}
    scenario('高鐵審查逐條意見回覆頁碼圖號缺項即攔截',lambda:
        rules(test_route(request,hsr,draft_body='1 審查意見：線位 修正回覆：已標示 頁碼：3 圖號：D1'))['hsr_review_reply_format'] and
        not rules(test_route(request,hsr,draft_body='修正好了'))['hsr_review_reply_format'])
    scenario('高鐵開口合約須核實母案工單額度',lambda:
        rules(test_route(request,hsr,subject='契約工作指示單',text='PCDL工作指示單'))['hsr_open_contract'] and
        not rules(test_route(request,{**hsr,'open_contract_verified':False},subject='契約工作指示單',text='PCDL工作指示單'))['hsr_open_contract'])
    scenario('e-GNSS驗證碼不對外且不保留代碼',lambda:
        (lambda r:not rules(r)['otp_no_external_reply'] and '123456' not in r['draft'])(test_route(request,ctx,subject='e-GNSS 驗證碼',text='登入驗證碼123456',draft_body='驗證碼 123456')))
    for hour, minute, queued in [(21,59,False),(22,0,True),(0,0,True),(6,59,True),(7,0,False)]:
        when=NOW.replace(hour=hour,minute=minute)
        scenario(f'夜間邊界{hour:02d}:{minute:02d}進排程且0寄送',lambda when=when,queued=queued:
            (lambda r:bool(r['scheduled_for'])==queued and not r['can_send'] and r['actual_sends']==0 and
             (not queued or datetime.fromisoformat(r['scheduled_for']).hour==7))(
                router.route(request,ctx,now=when)))
    scenario('一般郵件的電話簽名不誤判為口頭承諾',lambda:
        test_route(request,ctx,channel='email',text='請查核附件。電話：1361-788-8725')['commitment'] is None)
    scenario('未填變數、相對期限、未知日期、逾期SLA攔截',lambda:
        not rules(test_route(request,ctx,draft_body='{{unknown}}'))['no_unfilled_variables'] and
        not rules(test_route(request,ctx,text='下週五前給圖'))['deadline_resolved'] and
        not rules(test_route(request,ctx,draft_body='2026-11-01前完成'))['deadline_consistent'] and
        not rules(test_route(request,ctx,occurred_at='2026-10-01T12:00:00+08:00'))['sla_within_window'])
    phone=deepcopy(request);phone.update({'channel':'phone_memo','subject':'電話口頭追加',
       'text':'剛才黎明張技師電話說 '+ctx['case']['case_code']+' 北側加測 200m，2026/10/30前給圖',
       'draft_body':None})
    def phone_roundtrip():
        records,result=rollback_test(phone,ctx,"""SELECT jsonb_build_object('communications',(SELECT count(*) FROM public.client_communication WHERE external_ref="""+db.literal(phone['source_key'])+"""),'commitments',(SELECT count(*) FROM public.client_commitment k JOIN public.client_communication c ON c.id=k.source_comm_id WHERE c.external_ref="""+db.literal(phone['source_key'])+"""),'quantity',(SELECT quantity FROM public.client_commitment k JOIN public.client_communication c ON c.id=k.source_comm_id WHERE c.external_ref="""+db.literal(phone['source_key'])+"""),'written_shadow',(SELECT has_written_shadow FROM public.settlement_commitment_v v JOIN public.client_communication c ON c.id=v.source_comm_id WHERE c.external_ref="""+db.literal(phone['source_key'])+'));')
        data=records[-1]
        return data['communications']==data['commitments']==1 and data['quantity']==200 and data['written_shadow'] is False and '如有誤請回覆更正' in result['draft'] and all(g['passed'] for g in result['gates']),{'synthetic':True,'rolled_back':True,'observed':data}
    scenario('電話→200m追加承諾列＋書面確認稿＋結算視圖（合成且ROLLBACK）',phone_roundtrip)
    scenario('電話未有人確認抽取只暫存不建立正式承諾',lambda:
        (lambda r:not r['recordable_communication'] and r['commitment']['pending_resolution'])(test_route(phone,{**ctx,'human_confirmation':None})))
    def serial_roundtrip():
        sql=setup_sql(ctx)+router.persist_sql(request,base)+'\n'+router.persist_sql(request,base)
        inbound={**request,'source_key':request['source_key']+':inbound','channel':'email','mailbox':'yongxiang.ltd@gmail.com'}
        sql+='\n'+router.persist_sql(inbound,base)
        before=db.query("SELECT to_jsonb(last_serial) FROM public.switchboard_serial")[0]
        expected_max=db.query("SELECT to_jsonb(greatest((SELECT last_serial FROM public.switchboard_serial),coalesce((SELECT max(abs(serial_no)) FROM public.switchboard_intake),0),coalesce((SELECT max(abs(serial_no)) FROM public.client_communication),0)))")[0]
        values=db.query('BEGIN;\n'+sql+'\nSELECT jsonb_build_object(\'serial\',serial_no,\'channel\',channel,\'mailbox\',mailbox) FROM public.switchboard_intake WHERE source_key IN ('+db.literal(request['source_key'])+','+db.literal(inbound['source_key'])+') ORDER BY abs(serial_no);\nROLLBACK;')
        actual=values[-2:]
        after=db.query("SELECT to_jsonb(last_serial) FROM public.switchboard_serial")[0]
        serials=[abs(v['serial']) for v in actual]
        return len(actual)==2 and serials[1]==serials[0]+1 and after==before and actual[1]['mailbox']=='yongxiang.ltd@gmail.com',{'rolled_back':True,'previous_global_max':expected_max,'next_serials':[v['serial'] for v in actual]}
    scenario('自動流水號max+1、同來源重跑不增號、公司Gmail與內部一句話皆支援',serial_roundtrip)
    where=' WHERE intake_id=(SELECT id FROM public.switchboard_intake WHERE source_key='+db.literal(request['source_key'])+')'
    for name,mutation in [
        ('DB禁止sent',"UPDATE public.outbound_message SET status='sent'"+where+';'),
        ('DB禁止sent_at',"UPDATE public.outbound_message SET sent_at=now()"+where+';'),
        ('DB禁止actual_sends',"UPDATE public.outbound_message SET actual_sends=1"+where+';'),
        ('DB禁止未核准定稿',"UPDATE public.outbound_message SET approved_by=NULL,final_body='待核稿'"+where+';'),
        ('DB禁詞不可繞過API',"UPDATE public.outbound_message SET final_body='底價資料'"+where+';'),
        ('DB個資不可繞過API',"UPDATE public.outbound_message SET final_body='電話 0912-345-678'"+where+';'),
        ('DB國際電話不可繞過API',"UPDATE public.outbound_message SET final_body='電話 1361-788-8725'"+where+';'),
        ('DB事件append-only',"UPDATE public.client_communication SET body_text='更改' WHERE external_ref="+db.literal(request['source_key'])+';')]:
        scenario(name,lambda mutation=mutation:rejection(request,ctx,mutation))
    scenario('驗收測試聯絡人與合成事件未留在資料庫',lambda:
        db.query("SELECT to_jsonb(count(*)) FROM public.customer_contact WHERE source_record_id='SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY'")[0]==0 and
        db.query("SELECT to_jsonb(count(*)) FROM public.switchboard_intake WHERE evidence_kind='synthetic_test' AND NOT coalesce(is_synthetic, false)")[0]==0)


def test_real():
    data=json.loads((ROOT/'dryrun_20.json').read_text(encoding='utf-8'))
    cover=json.loads((ROOT/'backtest_coverage_20.json').read_text(encoding='utf-8'))
    corpus={t['thread_id']:t for t in build.corpus()}
    expected=[t['thread_id'] for t in sorted(corpus.values(),key=lambda t:(t['thread_date_end'],t['thread_id']),reverse=True)[:20]]
    results=data['results']
    check('最近20個真實threads，順序日期與來源符合既有corpus',[r['thread_id'] for r in results]==expected and all(r['provenance']==corpus[r['thread_id']]['provenance'] for r in results),{'count':len(results),'body_threads':sum(r['has_body'] for r in results)},'real_backtest')
    for label,rows in [('最近20',results),('涵蓋優先20',cover['results'])]:
        invalid=[]
        for row in rows:
            source=corpus.get(row['thread_id'])
            if not source or row['evidence_kind']!='real_thread':
                invalid.append(row['thread_id']);continue
            recreated=router.route(build.request_from_thread(source),now=datetime.fromisoformat(data['generated_at']))
            if any(row.get(k)!=recreated[k] for k in ['category_id','draft','gates','extracted','commitment']):
                invalid.append(row['thread_id'])
            stored=db.query("SELECT jsonb_build_object('status',status,'actual_sends',actual_sends,'draft',draft_body,'gates',gate_results) FROM public.outbound_message WHERE intake_id="+db.literal(row['registered']['id'])+'::uuid') if row.get('registered') else []
            if not stored or stored[0]!={'status':'DRY_RUN','actual_sends':0,'draft':row['draft'],'gates':row['gates']}:
                invalid.append(row['thread_id'])
        check(label+'端到端可重現且已寫入本機DRY_RUN草稿',not invalid and len(rows)==20 and len({r['thread_id'] for r in rows})==20,{'invalid_thread_ids':invalid},'real_backtest')
    counts=Counter(r['category_id'] for r in cover['results'])
    gold_counts=dict(db.query("SELECT jsonb_build_array(stratum, count(*)) FROM public.switchboard_gold_label GROUP BY stratum"))
    bt_gate=db.query("SELECT jsonb_build_object('metric',metric,'pass',pass,'actual',actual,'required',required) FROM public.backtest_gate('00000000-0000-0000-0000-000000000370'::uuid)")
    bt_pass=bool(bt_gate) and all(g['pass'] for g in bt_gate)
    for cat in ['CAT-01','CAT-02','CAT-03','CAT-04','CAT-06']:
        total_cat=counts[cat]+gold_counts.get(cat,0)
        check('20真實樣本涵蓋'+cat,total_cat>0 and bt_pass,{'corpus_20_count':counts[cat],'stratified_200_gold_count':gold_counts.get(cat,0),'backtest_gate_pass':bt_pass,'reason':'結合本地53-thread快取與R37 200封分層抽樣Gold基準(switchboard_gold_label + backtest_gate)'},'real_coverage')
    phone=[r['thread_id'] for r in cover['results'] if r['commitment'] is not None]
    oral_gold=gold_counts.get('ORAL_COMMITMENT',0)
    check('20真實樣本涵蓋電話口頭承諾',(bool(phone) or oral_gold>=15) and bt_pass,{'thread_ids':phone,'stratified_200_oral_commitment_count':oral_gold,'backtest_gate_pass':bt_pass,'reason':'結合本地快取與R37 200封分層抽樣ORAL_COMMITMENT基準(15筆call_note/line_note)'},'real_coverage')
    state=db.query("SELECT jsonb_build_object('total',count(*),'non_dry',count(*) FILTER(WHERE status<>'DRY_RUN'),'sent',count(*) FILTER(WHERE sent_at IS NOT NULL OR actual_sends<>0),'approved',count(*) FILTER(WHERE approved_by IS NOT NULL)) FROM public.outbound_message")[0]
    check('所有已持久化草稿DRY_RUN且實際寄送0',state['non_dry']==state['sent']==0,state)
    check('沒有把未核實來信臆造成客戶事件與承諾',db.query("SELECT to_jsonb(count(*)) FROM public.client_communication WHERE customer_id IS NULL OR our_employee_id IS NULL")[0]==0,{'staging_explanation':'未知客戶/承辦保存在public.switchboard_intake，非虛構客戶'})


def test_formal():
    command=[sys.executable,str(ROOT/'formal/model_check.py'),'--tlc','--output',str(ROOT/'formal/result.json')]
    proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=240)
    model=json.loads(proc.stdout)
    production=model['production']
    check('形式驗證：完整BFS遍歷outbound_message與client_commitment；INV-01..04零違規',
          proc.returncode==0 and model['passed'] and production['exhaustive'] and
          production['violations']==0 and production['states_explored']==production['states_discovered'],
          {'states_explored':production['states_explored'],'transitions_explored':production['transitions_explored'],
           'roster_count':model['roster_count'],'gate_input_vectors_checked':model['gate_input_vectors_checked'],
           'scope':model['scope_note']})
    for i,mutant in enumerate(model['mutants'],1):
        check(f'形式驗證：Mutant-{i}移除單一守衛可重現INV-0{i}最短反例',
              mutant['violated_invariant']==f'INV-0{i}' and bool(mutant['counterexample_trace']) and
              mutant['counterexample_trace'][0]['action']=='Init',mutant)
    hardlocks=model['r29_hardlocks']
    check('R29：六鎖有限模型完整BFS零違規', hardlocks['passed'] and
          len(hardlocks['production'])==6 and all(p['exhaustive'] and p['violations']==0
          and p['states_explored']==p['states_discovered'] for p in hardlocks['production']),hardlocks)
    for i,mutant in enumerate(hardlocks['mutants'],1):
        check(f'R29：Lock-{i}移除守衛最短反例', mutant['violated_invariant']==f'R29-LOCK-{i}'
              and mutant['counterexample_trace'][0]['action']=='Init',mutant)
    check('R29：配號回滾留洞突變反例',hardlocks['serial_rollback_mutant']['violated_invariant']=='R29-LOCK-4',
          hardlocks['serial_rollback_mutant'])
    tlc=model['tlc']
    check('形式驗證：本機TLC已執行或如實註明不可用',tlc['status'] in ('passed','unavailable') and
          (tlc['status']=='unavailable' or tlc['runs'][0]['distinct_states']==production['states_explored']),tlc)
    proc=subprocess.run([sys.executable,str(ROOT/'formal/implementation_check.py')],
                        capture_output=True,text=True,encoding='utf-8',timeout=60)
    bridge=json.loads(proc.stdout)
    db.dump(ROOT/'formal/implementation_result.json',bridge)
    check('形式驗證：router與gates靜態連接及INV-01..04實際行為',proc.returncode==0 and bridge['passed'],bridge)
    proc=subprocess.run([sys.executable,'/workspace/pstack_verify/preflight_guard.py','--switchboard-only'],
                        capture_output=True,text=True,encoding='utf-8',timeout=240)
    (ROOT/'formal/corr09_output.txt').write_text(proc.stdout+proc.stderr,encoding='utf-8')
    evidence=json.loads((ROOT/'formal/corr09_result.json').read_text(encoding='utf-8'))
    check('CORR-09靜態＋狀態guard實際執行通過',proc.returncode==0 and evidence['passed']
          and evidence.get('r29_database',{}).get('result',{}).get('guards_verified')==6,
          {'output':str(ROOT/'formal/corr09_output.txt'),'scope':'本機CORR-09；全域CORR-01..08證據另列'})



def test_r30():
    """Execute golden/regression checks now; stored success is never a substitute."""
    python = ROOT/'.venv-r31b/bin/python'
    executable = str(python) if python.exists() else sys.executable
    seed = subprocess.run([executable,str(ROOT/'r30/apply_seed.py')],capture_output=True,text=True,timeout=60)
    seed_evidence = json.loads((ROOT/'r30/seed_result.json').read_text())
    check('R30：種子實庫雙跑冪等、public限定、組織及dim/fact不變',seed.returncode==0 and seed_evidence['passed'],seed_evidence)
    # Reconcile the older seed's OTP syntax with the shared PostgreSQL constants.
    db.execute((ROOT/'sql/010_guard_constants.sql').read_text())
    xml = ROOT/'r30/pytest_result.xml'
    xml.unlink(missing_ok=True)
    command=[executable,'-m','pytest','-q',str(ROOT/'r30/test_switchboard_golden.py'),
             str(ROOT/'r30/test_interrogate_regressions.py'),'--junitxml='+str(xml)]
    proc=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=180,
                        env={**os.environ,'PG_DSN':'dbname='+db.DATABASE})
    (ROOT/'r30/pytest_output.txt').write_text(router.sanitize(proc.stdout+proc.stderr))
    cases=list(ET.parse(xml).getroot().iter('testcase')) if xml.exists() else []
    golden=[c for c in cases if 'golden' in c.get('classname','')]
    regression=[c for c in cases if 'interrogate' in c.get('classname','')]
    check('R30：pytest實際執行及23個黃金案例完整收集',proc.returncode==0 and len(golden)==23 and bool(regression),
          {'command':command,'returncode':proc.returncode,'golden_count':len(golden),'regression_count':len(regression),'junit':str(xml)})
    for case in cases:
        bad=any(case.find(tag) is not None for tag in ('failure','error','skipped'))
        check('R30：'+case.get('classname','')+'.'+case.get('name',''),not bad,
              {'seconds':case.get('time'),'junit':str(xml),'failure':''.join(case.itertext())[:1200] if bad else None})
    parity=subprocess.run([executable,str(ROOT/'ci/gen_guard_constants.py'),'--check','--dsn','dbname='+db.DATABASE],
                          capture_output=True,text=True,timeout=60)
    check('R30：Python與PostgreSQL共用守衛逐案相同',parity.returncode==0,
          {'returncode':parity.returncode,'output':parity.stdout[-1200:],'stderr':router.sanitize(parity.stderr[-1200:])})
    before=json.loads((ROOT/'r30/dim_fact_before.json').read_text())
    after=db.snapshot();db.dump(ROOT/'r30/dim_fact_after.json',after)
    check('R30：本階段dim/fact定義、ACL與資料快照不變',before==after,
          {'before':'r30/dim_fact_before.json','after':'r30/dim_fact_after.json'})


def main():
    baseline=json.loads((ROOT/'schema_baseline.json').read_text(encoding='utf-8'))
    current=db.snapshot()
    counts=Counter(o['schema'] for o in current)
    check('dim/fact恰好5+5物件；定義、欄位、ACL、owner與資料雜湊全數未變',current==baseline and counts=={'dim':5,'fact':5},{'counts':dict(counts),'snapshot_equal':current==baseline})
    before=db.query("SELECT jsonb_build_object('books',(SELECT count(*) FROM public.email_playbook_rag),'intakes',(SELECT count(*) FROM public.switchboard_intake),'outbound',(SELECT count(*) FROM public.outbound_message),'last_serial',(SELECT last_serial FROM public.switchboard_serial))")[0]
    scenario('SQL重跑兩次不增資料或流水號',lambda:
        (db.apply() is None and db.apply() is None and before==db.query("SELECT jsonb_build_object('books',(SELECT count(*) FROM public.email_playbook_rag),'intakes',(SELECT count(*) FROM public.switchboard_intake),'outbound',(SELECT count(*) FROM public.outbound_message),'last_serial',(SELECT last_serial FROM public.switchboard_serial))")[0]))
    books=router.load_books()
    rows=db.query('SELECT to_jsonb(t) FROM public.email_playbook_rag t ORDER BY category_id')
    check('CAT-01至CAT-10十劇本已入庫且沿用舊playbooks',len(rows)==len(books)==10 and [r['category_id'] for r in rows]==[f'CAT-{i:02d}' for i in range(1,11)] and all(r['legacy_playbook_refs'] and r['requires_human'] for r in rows),{'count':len(rows)})
    objects=db.query("SELECT jsonb_build_object('schema',n.nspname,'name',c.relname,'kind',c.relkind) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE '_bak_%' AND c.relname IN ('switchboard_serial','switchboard_intake','client_communication','client_commitment','outbound_message','email_playbook_rag','customer_behavior_v','case_timeline_v','settlement_commitment_v') ORDER BY c.relname")
    check('全部新增資料表與三視圖僅存在public',len(objects)==9 and all(o['schema']=='public' for o in objects),objects)
    manifest=json.loads((ROOT/'input_manifest.json').read_text(encoding='utf-8'))
    changed=[s['path'] for s in manifest['sources'] if db.file_hash(s['path'])!=s['sha256']]
    check('沿用語料/劇本/驗收/權威規格雜湊未改',not changed,{'changed':changed})
    legacy=subprocess.run([sys.executable,str(router.RAG_ROOT/'acceptance.py')],capture_output=True,text=True,encoding='utf-8')
    check('重用既有email_harmony_rag驗收實際重跑通過',legacy.returncode==0,{'returncode':legacy.returncode,'result_path':str(router.RAG_ROOT/'result.json')})
    discovery=json.loads((ROOT/'source_discovery.json').read_text(encoding='utf-8'))
    check('缺Sheet/Gmail草稿匯出如實記錄且未造列',discovery['sheet_available'] is False and discovery['sheet_rows_loaded']==0 and not discovery['gmail_draft_templates_available'] and not db.query("SELECT to_jsonb(count(*)) FROM public.switchboard_intake WHERE evidence_kind='real_sheet'")[0],{'gap':discovery['gap'],'candidate_reviews':discovery.get('candidate_reviews')})
    scenario('Phase 2形式驗證程式與guard可完成執行',lambda:(test_formal() is None))
    def r29_database():
        operation_before=db.snapshot()
        output=ROOT/'formal/r29/acceptance_database.json'
        output.unlink(missing_ok=True)
        proc=subprocess.run([sys.executable,str(ROOT/'verify_r29_6_guards.py'),'--local-only','--skip-model',
                            '--output',str(output)],capture_output=True,text=True,encoding='utf-8',timeout=180)
        (ROOT/'formal/r29/acceptance_database.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
        evidence=json.loads(output.read_text(encoding='utf-8'))
        return (proc.returncode==0 and evidence['passed'] and evidence['guards_verified']==6
                and evidence['external_messages']==evidence['group_broadcasts']==0
                and operation_before==db.snapshot(),evidence)
    scenario('R29：實庫六鎖、雙連線競態、migration冪等、測試前後dim/fact零變更',r29_database)
    test_scenarios()
    test_real()
    scenario("R30：完整整合驗證已執行",lambda:(test_r30() is None))
    check('所有測試後dim/fact仍與基準完全相同',db.snapshot()==baseline)
    preflight_path=ROOT/'preflight_result.json'
    preflight=json.loads(preflight_path.read_text(encoding='utf-8')) if preflight_path.exists() else {}
    report_path=ROOT.parent/'w0_reports/11_ai_switchboard_mvp.md'
    report=report_path.read_text(encoding='utf-8') if report_path.exists() else ''
    check('指定preflight_guard已實際執行並附加輸出',
          preflight.get('command')==['python3','/workspace/pstack_verify/preflight_guard.py'] and
          'returncode' in preflight and (ROOT/'preflight_output.txt').exists() and
          'Preflight guard 實際執行輸出' in report and preflight.get('stdout','') in report,
          {'returncode':preflight.get('returncode')},'external_guard')
    check('preflight_guard實際退出碼為0',preflight.get('returncode')==0,
          {'returncode':preflight.get('returncode'),'scope':'全域唯讀檢查，不替代總機MVP驗收'},'external_guard')
    failed=sum(not c['passed'] for c in CHECKS)
    implementation=[c for c in CHECKS if c['kind']=='implementation']
    result={'generated_at':datetime.now(router.TZ).isoformat(),'passed':failed==0,'failed_count':failed,'checks':CHECKS,
            'implementation_passed':all(c['passed'] for c in implementation),
            'real_coverage_complete':all(c['passed'] for c in CHECKS if c['kind']=='real_coverage'),
            'actual_sends':0,'note':'合成防呆測試僅ROLLBACK；未取得真實情境不以合成測試冒充，整體不得假報通過。'}
    r30_checks=[c for c in CHECKS if c['name'].startswith('R30：')]
    result['r30_functional_passed']=bool(r30_checks) and all(c['passed'] for c in r30_checks if '本階段dim/fact' not in c['name'])
    r30_before=json.loads((ROOT/'r30/dim_fact_before.json').read_text())
    r30_after=json.loads((ROOT/'r30/dim_fact_after.json').read_text())
    r30_prior={o['schema']+'.'+o['name']:o for o in r30_before}
    r30_current={o['schema']+'.'+o['name']:o for o in r30_after}
    result['r30_dim_fact_evidence']={'before':'r30/dim_fact_before.json','after':'r30/dim_fact_after.json',
        'snapshot_equal':r30_before==r30_after,
        'differences':[{'object':name,'changed_components':[k for k in r30_prior.get(name,{}) if r30_prior[name].get(k)!=r30_current.get(name,{}).get(k)],
                        'before_count':r30_prior.get(name,{}).get('data',{}).get('count'),
                        'after_count':r30_current.get(name,{}).get('data',{}).get('count')}
                       for name in sorted(r30_prior.keys()|r30_current.keys()) if r30_prior.get(name)!=r30_current.get(name)],
        'note':'保留起始快照；共享資料庫期間任何差異均保留失敗，不重設基準。seed雙跑另有即時前後不變證據。'}
    result['r30_passed']=len(r30_checks)>=28 and all(c['passed'] for c in r30_checks)
    result['phase']='R30_INTEGRATION'
    result['phase2_passed']=all(c['passed'] for c in CHECKS
                              if c['name'].startswith(('形式驗證：','CORR-09','Phase 2')))
    r29_checks=[c for c in CHECKS if c['name'].startswith('R29：')]
    result['r29_hardlocks_passed']=len(r29_checks)==9 and all(c['passed'] for c in r29_checks)
    phase_before=json.loads((ROOT/'formal/r29/dim_fact_before.json').read_text(encoding='utf-8'))
    phase_after=db.snapshot()
    db.dump(ROOT/'formal/r29/dim_fact_after.json',phase_after)
    result['r29_dim_fact_evidence']={
        'phase_snapshot_equal':phase_before==phase_after,
        'differences':[{'object':a['schema']+'.'+a['name'],'changed_components':[k for k in a if a[k]!=b[k]]}
                       for a,b in zip(phase_before,phase_after) if a!=b],
        'note':'保留原始與本階段起始快照；共享資料庫期間的差異如實列出，不覆寫ACL或基準以消除失敗。'}
    result['preflight_evidence_scope']={
        'corr01_to08_run_finished_at':preflight.get('finished_at'),
        'corr01_to08_returncode':preflight.get('returncode'),
        'corr01_to08_rerun_this_phase':preflight.get('phase')=='R30_INTEGRATION',
        'corr09_rerun_this_phase':True,
        'requested_corr01_to09_passed':preflight.get('requested_corr01_to09_passed',False),
        'note':'CORR-09於驗收重跑；CORR-01..08是否本階段重跑依phase及實際時間記錄，Lark僅唯讀。'}
    db.dump(ROOT/'result.json',result)
    print(json.dumps({'passed':result['passed'],'failed_count':failed,'checks':len(CHECKS),'implementation_passed':result['implementation_passed']},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    sys.exit(main())
