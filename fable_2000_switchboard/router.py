#!/usr/bin/env python3
"""本機分類→欄位抽取→RAG→十閘門→卡片與草稿；沒有 send 函式。"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

import db
import switchboard_engine as engine
from gates import (STRIP_PATTERNS, strip_command_headers, authorized_roster, send_authorized,
                   payment_release_allowed, check_bounce_release_allowed, otp_pull_only_allowed,
                   satcmd_verified, sensitive_draft, commitment_close_allowed)

RAG_ROOT = db.ROOT.parent / 'email_harmony_rag'
sys.path.insert(0, str(RAG_ROOT))
from privacy import PHONE, HR, hr_mask  # 沿用已驗收的遮蔽器

TZ = ZoneInfo('Asia/Taipei')
ID_NUMBER = re.compile(r'(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![A-Za-z0-9])', re.I)
PHONE_TW = re.compile(r'(?<![A-Za-z0-9])(?:09[0-9]{2}[- ]?[0-9]{3}[- ]?[0-9]{3}|0[2-8][- ]?[0-9]{3,4}[- ]?[0-9]{4})(?![A-Za-z0-9])')
PHONE_EXTRA = re.compile(r'(?<![A-Za-z0-9])1[3-9](?:[ ()-]*\d){9}(?![A-Za-z0-9])')
PHONE_LABELED = re.compile(r'((?:電話|电话|手機|手机|phone|tel)[：:\s]*)(\+?\d[\d ()-]{6,}\d)',re.I)
FORBIDDEN = re.compile(r'底價|成本|毛利|A\s*[-/]\s*B\s*[-/]\s*C\s*預算|ABC\s*預算|內部|點數單價', re.I)
VARIABLE = re.compile(r'\{\{\s*([\w]+)\s*\}\}')
MONEY = re.compile(r'(?:NT\$|TWD|USD|EUR|US\$|\$|新[臺台]幣|金額[：:]?)[ \t]*([\d,]+(?:\.\d+)?)[ \t]*(萬)?(?:元)?|(?<![A-Za-z0-9])([\d,]+(?:\.\d+)?)[ \t]*(萬)?元', re.I)
OTP = re.compile(r'驗證碼|验证码|confirmation code|verification code|one.time.password|e-?gnss|eg nss', re.I)
KEYWORDS = {
    'CAT-01': ['詢價','报价','報價','報編','議價','招標','rfq','quotation'],
    'CAT-02': ['成果提供','成果資料','成果交付','成果圖','成果图','成果提送','日報提供','期中成果','期末成果','舊成果'],
    'CAT-03': ['審查','修正','補正','退件','不符合規範','重測','jsa'],
    'CAT-04': ['出入廠','入廠','入厂','作業申請','職安','空域','hsror','進場','进场','核准通知'],
    'CAT-05': ['契約工作指示單','決標','開工','會勘','公文','合約','合同','用印','簽回','contract','加測','追加','口頭承諾'],
    'CAT-06': ['驗收','計價','請款','發票','发票','invoice','payment','入帳','付款','收款','帳款'],
    'CAT-07': ['下包','地政士','代墊','小柯','展洲','世和'],
    'CAT-08': ['海事','離岸','rov','usv','dhl','報關','报关','订单发货','訂單出貨','裝箱'],
    'CAT-09': ['104','1111','履歷','履历','應徵','招聘','招募','薪資','salary','勞保','健保'],
    'CAT-10': ['驗證碼','confirmation code','verification code','password','登入','login','氣象','警報','newsletter','welcome','secure link'],
}


def sanitize(text):
    text = engine.normalize(str(text))
    # 整段薪酬內容不進對外草稿；包含非數字形式的待遇也不可外洩。
    text = '\n\n'.join('[MASKED_HR_PRIVATE]' if HR.search(p) else p
                       for p in re.split(r'\n\s*\n', text))
    text = PHONE.sub('[MASKED_PHONE]', text)
    text = PHONE_TW.sub('[MASKED_PHONE]', text)
    text = PHONE_EXTRA.sub('[MASKED_PHONE]', text)
    text = PHONE_LABELED.sub(lambda m:m[1]+'[MASKED_PHONE]',text)
    text = ID_NUMBER.sub('[MASKED_ID]', text)
    text = FORBIDDEN.sub('[MASKED_INTERNAL]', text)
    for word in engine.FORBIDDEN_WORDS:
        text = re.sub(r'\s*'.join(re.escape(c) for c in word), '[MASKED_INTERNAL]', text, flags=re.I)
    if OTP.search(text):
        text = re.sub(r'(?<!\w)\d{3,6}(?:[- ]\d{3})?(?!\w)', '[MASKED_OTP]', text)
    return text


def amounts(text):
    result = []
    for m in MONEY.finditer(engine.normalize(text)):
        number, wan = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        result.append(Decimal(number.replace(',', '')) * (10000 if wan else 1))
    return result


def keyword_hit(word, text):
    text = engine.normalize(text)
    if word.isascii():
        return bool(re.search(r'(?<![A-Za-z0-9])'+re.escape(word)+r'(?![A-Za-z0-9])', text, re.I))
    if word == '世和':
        return bool(re.search(r'(?<![\u4e00-\u9fff])世和(?![\u4e00-\u9fff])', text))
    return word in text


def taipei_time(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return (parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed).astimezone(TZ)


def money_evidence(text):
    value = engine.normalize(text)
    parsed = amounts(value)
    remaining = MONEY.sub('', value)
    # Contextual bare amounts are parsed exactly; unparsed Chinese monetary numerals block.
    for m in re.finditer(r'(?:計價|應付|本期|總價|報價|金額|費用)[：:\s]*([0-9][0-9,]*(?:[.][0-9]+)?)', remaining):
        parsed.append(Decimal(m[1].replace(',', '')))
    uncertain = bool(re.search(r'[零〇一二兩三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟]+[圓元]|(?:計價|應付|總價|金額|費用)[：:\s]*[零一二三四五六七八九十百千萬億]+', remaining))
    return parsed, uncertain


def classify(subject, body):
    candidates = []
    for code, words in KEYWORDS.items():
        sh = [w for w in words if keyword_hit(w, subject)]
        bh = [w for w in words if keyword_hit(w, body)]
        if sh or bh:
            # CAT-03、07 等具體事件優先；避免「開口合約」蓋過成果提送。
            specificity = {'CAT-03':9,'CAT-07':8,'CAT-04':7,'CAT-02':6,'CAT-06':5}.get(code,0)
            candidates.append({'category_id':code,'score':100*bool(sh)+10*bool(bh)+specificity,
                               'subject_hits':sh,'body_hits':bh})
    candidates.sort(key=lambda c:(-c['score'],c['category_id']))
    return (candidates[0]['category_id'] if candidates else 'CAT-10'), {
        'candidates':candidates, 'requires_manual_classification':not bool(candidates),
        'method':'權威CAT分類的可解釋關鍵詞規則；無命中CAT-10待人工分流，非機率模型'}


def extract(request):
    text = request.get('subject','')+'\n'+request.get('text','')
    cases = sorted(set(x.upper() for x in re.findall(r'(?<![A-Za-z0-9])[ABC]\d{6}(?:-\d{1,3})*(?![A-Za-z0-9])',text,re.I)))
    quotes = sorted(set(re.findall(r'(?:報價(?:編號|號碼|編|單號)?|報編|quote(?:\s*no\.?)?)\s*[:：#]?\s*(\d{6}(?:-\d+)?)',text,re.I)))
    when = taipei_time(request.get('occurred_at') or datetime.now(TZ))
    deadlines = []
    for match in re.finditer(r'(?:(20\d{2})[年/.-])?(\d{1,2})[月/.-](\d{1,2})日?\s*(?:前|截止|到期)',text):
        try:
            deadlines.append(datetime(int(match[1] or when.year),int(match[2]),int(match[3]),tzinfo=TZ).date().isoformat())
        except ValueError:
            pass
    deadlines = sorted(set(deadlines))
    relative = bool(re.search(r'下週|下周|明天|後天|星期|盡快|儘快',text))
    length = re.search(r'(\d+(?:\.\d+)?)\s*(?:公尺|米|m\b)',text,re.I)
    named_client = re.search(r'寄給\s*([^\s，。]+)|剛才\s*([^\s，。]{2,8}?)(?=[張王李陳林吳]技師)',text)
    named_contact = re.search(r'([\u4e00-\u9fff]{1,3}(?:技師|經理|課長|主任|小姐|先生))(?=電話|[，。\s]|$)',text)
    return {'case_code':cases[0] if len(cases)==1 else None,'case_candidates':cases,
            'quote_no':quotes[0] if len(quotes)==1 else None,'quote_candidates':quotes,
            'client':None,'contact':None,'client_candidates':[next(v for v in named_client.groups() if v)] if named_client else [],
            'contact_candidates':[named_contact[1]] if named_contact else [],
            'candidate_policy':'明文名稱只是候選，需客戶/聯絡人資料核實，不能當收件白名單',
            'deadline':deadlines[0] if len(deadlines)==1 and not relative else None,
            'deadline_candidates':deadlines,'relative_deadline_unresolved':relative,
            'attachments':request.get('attachments',[]),'quantity':length[1] if length else None,
            'unit':'m' if length else None,'scope':'北側' if '北側' in text else None}


def resolve_context(fields, request):
    """只取白名單欄位；不讀薪資、電話、統編或身分證。名稱僅作候選。"""
    cases = db.query('SELECT jsonb_build_object(\'id\',id,\'case_code\',case_code,\'customer_id\',customer_id,\'pm_employee_id\',pm_employee_id,\'due_date\',due_date) FROM public."case" WHERE upper(case_code)='+db.literal(fields['case_code'])) if fields['case_code'] else []
    quotes = db.query("SELECT jsonb_build_object('id',id,'quote_no',quote_no,'case_id',case_id,'customer_id',customer_id) FROM public.quote WHERE quote_no="+db.literal(fields['quote_no'])) if fields['quote_no'] else []
    case = cases[0] if len(cases)==1 else None
    quote = quotes[0] if len(quotes)==1 else None
    if not case and quote and quote['case_id']:
        linked = db.query("SELECT jsonb_build_object('id',id,'case_code',case_code,'customer_id',customer_id,'pm_employee_id',pm_employee_id,'due_date',due_date) FROM public.\"case\" WHERE id="+db.literal(quote['case_id']))
        case = linked[0] if linked else None
    ids = {v['customer_id'] for v in (case,quote) if v and v['customer_id']}
    context = {'case':case,'quote':quote,'customer':None,'contacts':[], 'verified_amounts':[],
               'approved_artifacts':[], 'known_deadlines':[], 'schema_gaps':[
                   'quote_version與deliverable無核准狀態欄位，不能宣稱附件已核版',
                   '未接通核准服務；所有擬稿保持DRY_RUN']}
    if len(ids)==1:
        customer_id = next(iter(ids))
        customers = db.query("SELECT jsonb_build_object('id',id,'name',name,'delivery_constraints',delivery_constraints,'invoice_rules',invoice_rules) FROM public.customer WHERE id="+db.literal(customer_id))
        context['customer'] = customers[0] if customers else None
        context['contacts'] = db.query("SELECT jsonb_build_object('id',id,'customer_id',customer_id,'name',full_name,'email',email) FROM public.customer_contact WHERE customer_id="+db.literal(customer_id))
    if case and case['due_date']:
        context['known_deadlines'] = [case['due_date']]
    # 核准、金額、付款與附件皆不採信來信自述；此MVP缺權威核版資料時一律攔截。
    if case:
        invoices = db.query("SELECT jsonb_build_object('id',id,'amount_due',amount_due,'unpaid_amount',unpaid_amount,'paid',paid) FROM public.invoice_paid_v WHERE case_id="+db.literal(case['id']))
        # Allocation/reversal facts are authoritative. Legacy invoice status and
        # paid_amount are retained for R28 consumers, never used to release mail.
        context['payment_verified'] = bool(invoices) and all(i['paid'] is True for i in invoices)
    actor_id = request.get('our_employee_id')
    confirmed_id = request.get('human_confirmed_by')
    for key, value in [('actor',actor_id),('human_confirmation',confirmed_id),('approver',request.get('approved_by'))]:
        rows = db.query("SELECT jsonb_build_object('id',id,'name',full_name,'title',job_title) FROM public.employee WHERE id="+db.literal(value)+" AND employment_status='active'") if value else []
        context[key] = rows[0] if len(rows)==1 else None
    # 角色不可由呼叫者聲稱；僅案件既有PM可作本MVP的PM核准人。
    context['approver_is_pm'] = bool(context.get('approver') and case and context['approver']['id']==case['pm_employee_id'])
    return context


def load_books():
    return json.loads((db.ROOT/'playbooks.json').read_text(encoding='utf-8'))


def route(request, context=None, now=None):
    """context為受信任的內部資料讀取結果；CLI不提供任意context覆寫。"""
    now = taipei_time(now or datetime.now(TZ))
    fields = extract(request)
    category, evidence = classify(request.get('subject',''),request.get('text',''))
    context = resolve_context(fields,request) if context is None else context
    case, customer = context.get('case'), context.get('customer')
    contacts = context.get('contacts',[])
    recipient = next((c for c in contacts if c['id']==request.get('to_contact_id')),None)
    if not recipient and len(contacts)==1:
        recipient = contacts[0]
    fields['client'] = customer.get('name') if customer else None
    fields['contact'] = recipient.get('name') if recipient else None
    book = next(b for b in load_books() if b['category_id']==category)
    raw = request.get('text','')
    phone = request.get('channel')=='phone_memo' or (
        request.get('channel','staff_request')=='staff_request' and
        bool(re.search(r'(?:剛才|剛剛|方才).{0,24}電話|電話.{0,12}(?:說|交辦|要求|承諾)|口頭(?:說|交辦|承諾)|口述',raw)))
    commitment_kind = 'scope_add' if re.search(r'加測|追加|增測',raw) else 'other'
    values = {'client_name':fields['client'],'case_code':case.get('case_code') if case else fields['case_code'],
              'quote_no':fields['quote_no'],'contact_person':fields['contact'],
              'requested_deadline':fields['deadline'],'pm_name':(context.get('actor') or {}).get('name'),
              'scope':((fields['scope'] or '')+' '+(fields['quantity'] or '')+' '+(fields['unit'] or '')).strip() if fields['quantity'] else None}
    for key in ['approved_version','deliverable_list','review_rows','permit_details','invoice_no','invoice_item','contract_no','work_order_no','pending_items']:
        values[key] = context.get('template_values',{}).get(key)
    template = book['reply_template']
    if phone:
        template = '{{contact_person}}您好，依剛才電話，關於 {{case_code}} 的 {{scope}} 加測需求，範圍與 {{requested_deadline}} 期限尚待雙方確認。如有誤請回覆更正。\n{{pm_name}}'
    def fill(match):
        value = values.get(match[1])
        return str(value) if value is not None and str(value).strip() else match[0]
    proposed = request.get('draft_body') if request.get('draft_body') is not None else VARIABLE.sub(fill,template)
    findings = {}
    gates = []
    def gate(name, conditions):
        findings[name] = conditions
        gates.append({'name':name,'passed':all(c['passed'] for c in conditions),'checks':conditions})
    def condition(rule, passed, reason):
        return {'rule':rule,'passed':bool(passed),'reason':reason}
    approver = context.get('approver')
    approved = bool(approver and approver['id']==request.get('approved_by')
                    and approver['id'] in authorized_roster())
    gate('no_send_mode',[
        condition('transport_disabled',True,'此程式沒有寄送實作；資料庫僅允許DRY_RUN與actual_sends=0'),
        condition('human_approved_by',approved,'每份對外草稿必須由在職人員核准；缺核准只產卡片')])
    belongs = bool(recipient and customer and case and recipient.get('customer_id')==customer['id']==case.get('customer_id'))
    valid_email = bool(recipient and re.fullmatch(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+',recipient.get('email') or ''))
    gate('recipient_known_client',[condition('contact_customer_case_match',belongs and valid_email,'只採用customer_contact與案件客戶一致的單一Email'),
                                        condition('no_group_recipients',not request.get('cc') and not request.get('bcc') and not request.get('to'),'不接受來信自述的to/cc/bcc')])
    case_matches = bool(case and (not fields['case_code'] or fields['case_code']==case['case_code']))
    quote = context.get('quote')
    quote_match = not fields['quote_no'] or bool(quote and quote.get('quote_no')==fields['quote_no'] and
        quote.get('customer_id')==case.get('customer_id') and quote.get('case_id')==case.get('id') if case else False)
    gate('case_code_resolved',[condition('unique_case',case_matches and len(fields['case_candidates'])<=1,'案件須由public.case核實；不從名稱猜案'),
                               condition('quote_matches_case',quote_match and len(fields['quote_candidates'])<=1,'報價須與案件客戶及版本一致')])
    money, uncertain_money = money_evidence(proposed)
    financial = category in ('CAT-01','CAT-06','CAT-07','CAT-08') or bool(money)
    refs = {Decimal(str(a)) for a in context.get('verified_amounts',[])}
    gate('amount_requires_human',[
        condition('amount_human_review',not financial or (approved and context.get('amount_reviewed_by')==approver['id']),'報價請款及金額必由人查核'),
        condition('quote_invoice_amount_consistency',not uncertain_money and (not money or (bool(refs) and all(m in refs for m in money))),'每筆金額須等於已核報價/發票資料；沒有資料不能通過'),
        condition('currency_consistency',not re.search(r'USD|US\$|EUR',proposed,re.I) or context.get('verified_currency') in ('USD','EUR'),'外幣不得直接比對TWD報價；需財務核實幣別')])
    contract = category=='CAT-05' or phone or bool(re.search(r'合約|契約|追加|折扣|承諾|交期',raw))
    gate('contract_requires_human',[
        condition('contract_pm_approval',not contract or (approved and context.get('approver_is_pm') and context.get('contract_reviewed_by')==approver['id']),'契約、口頭追加及交期由案件PM核准'),
        condition('phone_extraction_confirmed',not phone or bool(context.get('human_confirmation')),'電話抽取需在職人員確認；未確認僅暫存')])
    hr_leak = bool(HR.search(engine.normalize(proposed)) or '[MASKED_HR_PRIVATE]' in proposed)
    gate('no_hr_private',[
        condition('hr_salary_isolated',not hr_leak and category!='CAT-09','薪資與招募只交授權人資；薪酬段落遮蔽為[MASKED_HR_PRIVATE]'),
        condition('forbidden_words',not FORBIDDEN.search(re.sub(r'\s+', '', engine.normalize(proposed))) and not engine.check_outbound_body(request.get('subject',''), proposed),'禁止底價、成本、毛利、A-B-C/A/B/C預算、內部與點數單價'),
        condition('otp_no_external_reply',not OTP.search(engine.normalize(request.get('subject','')+'\n'+raw+'\n'+proposed)),'e-GNSS等驗證碼只記錄遮蔽事件，禁止對外草稿放行')])
    proposed_pii = engine.normalize(proposed)
    gate('no_raw_phone_id',[condition('phone_id_redacted',not PHONE_TW.search(proposed_pii) and not PHONE.search(proposed_pii) and not PHONE_EXTRA.search(proposed_pii) and not PHONE_LABELED.search(proposed_pii) and not ID_NUMBER.search(proposed_pii) and '{{contact_phone}}' not in proposed,'草稿不得含裸電話、身分證或未填電話變數')])
    attachments = request.get('attachments',[])
    approved_files = {a.get('id'):a for a in context.get('approved_artifacts',[]) if a.get('status') in ('approved','核定','已交付')}
    file_ok = all(isinstance(a,dict) and a.get('id') in approved_files and a==approved_files[a['id']] and bool(re.fullmatch(r'[a-fA-F0-9]{64}',a.get('sha256',''))) and a.get('source_type') in ('quote_version','deliverable_version','official_doc') for a in attachments)
    promised = bool(re.search(r'附件|附上|夾帶|檢附|隨附|請見附',proposed)) or category=='CAT-02'
    marked = bool(request.get('payment_required') or re.search(r'入帳後再寄出',raw+' '+str(request.get('labels',[]))))
    client_text = (fields['client'] or '')+' '+str(context.get('client_group',''))+' '+str((recipient or {}).get('email',''))
    fpg = bool(re.search(r'台塑|南亞|麥電|fpg|fpcc|npc',client_text,re.I))
    bes = '中華工程' in client_text
    hsr = bool(re.search(r'高鐵|thsrc',client_text,re.I))
    constraints = (customer or {}).get('delivery_constraints') or {}
    max_part = context.get('max_attachment_bytes') or ((constraints.get('max_attachment_mb') or 0)*1024*1024)
    parts_ok = all(a.get('bytes') is not None and max_part and 0<a['bytes']<=max_part for a in attachments) if fpg and attachments else False
    invoice_date = context.get('invoice_issue_date')
    try:
        invoice_day = datetime.fromisoformat(invoice_date).day if invoice_date else None
    except (TypeError,ValueError):
        invoice_day = None
    iv = context.get('invoice_rule',{})
    expected_item = f"{iv.get('contract_no','')}{iv.get('contract_name','')}第{iv.get('period','')}期計價"
    review_rows = context.get('review_rows',[])
    review_ok = bool(review_rows) and all(all(row.get(k) for k in ('comment_no','comment','reply','page','drawing')) for row in review_rows)
    required_files = context.get('required_deliverable_names',[])
    gate('attachment_present_if_promised',[
        condition('promised_attachment_present',not promised or bool(attachments),'承諾附件時必有真實核定附件'),
        condition('approved_attachment_whitelist',file_ok,'附件須完全匹配核定檔案識別、版號、雜湊與來源；拒絕任意本機路徑'),
        condition('deliverable_list_complete',category!='CAT-02' or (bool(required_files) and set(required_files)<={a.get('name') for a in attachments if isinstance(a,dict)}),'成果PDF/DWG/照片須與核定交付清單逐項一致；缺清單不得放行'),
        condition('cat02_paid_before_delivery',payment_release_allowed(category,marked,context.get('payment_verified')),'⛔入帳後再寄出：未核實入帳即攔截'),
        condition('fpg_no_external_link',not (fpg or constraints.get('no_links')) or not engine.URL_RE.search(engine.normalize(request.get('subject','')+' '+proposed+' '+str(attachments))),'台塑/南亞/麥電不得只用外部連結'),
        condition('r30_delivery_constraints',not engine.check_delivery_constraints(constraints, request.get('subject','')+' '+proposed+' '+str(attachments), [engine.AttachmentMeta(a.get('name',''),a.get('sha256',''),a.get('bytes') or 0) for a in attachments if isinstance(a,dict)]),'R30種子交付限制：禁連結、大小與公文文號'),
        condition('sealed_paid_before_release',not any(isinstance(a,dict) and (a.get('is_sealed') or str(a.get('name','')).lower().endswith(engine.SEALED_EXT)) for a in attachments) or context.get('payment_verified') is True,'官章版DWG/DXF跨分類均須已核實全額沖帳；不採信來信入帳聲稱'),
        condition('fpg_file_splitting',not fpg or not promised or (bool(attachments) and parts_ok),'台塑附件按業主核定大小拆檔；規格無固定MB值，缺設定就攔截'),
        condition('bes_invoice_window',not bes or category!='CAT-06' or bool(invoice_day and 10<=invoice_day<=20),'中華工程發票日期須10–20日'),
        condition('bes_invoice_item',not bes or category!='CAT-06' or (all(iv.get(k) for k in ('contract_no','contract_name','period')) and iv.get('item')==expected_item),'中華工程品名=合約編號+合約名稱+第X期計價；估驗/計價單兩份並用印'),
        condition('hsr_review_reply_format',not hsr or category!='CAT-03' or (review_ok and all(str(row[k]) in proposed for row in review_rows for k in ('comment_no','comment','reply','page','drawing'))),'高鐵逐條審查意見、回覆、頁碼、圖號；不能宣稱未核實的複測完成'),
        condition('hsr_open_contract',not hsr or category!='CAT-05' or bool(context.get('open_contract_verified') and values.get('contract_no') and values.get('work_order_no')),'高鐵開口合約須查母案、工單號、額度與子案；不自動更動合約')])
    night = now.hour>=22 or now.hour<7
    scheduled = (now+timedelta(days=1) if now.hour>=22 else now).replace(hour=7,minute=0,second=0,microsecond=0) if night else None
    deadline = fields['deadline']
    body_dates = re.findall(r'20\d{2}-\d{2}-\d{2}',proposed)
    known_dates = context.get('known_deadlines',[])
    gate('sla_deadline_check',[
        condition('night_scheduled_queue',not night,'22:00–07:00轉次日/當日07:00排程佇列，仍不發送'),
        condition('deadline_resolved',not fields['relative_deadline_unresolved'] and len(fields['deadline_candidates'])<=1,'相對期限及矛盾日期須人確認'),
        condition('deadline_not_overdue',not deadline or deadline>=now.date().isoformat(),'逾期需重議期限'),
        condition('deadline_consistent',all(d in known_dates for d in body_dates) and (not deadline or deadline in known_dates),'草稿日期須與案件/承諾核實期限一致'),
        condition('sla_within_window',now<=taipei_time(request.get('occurred_at') or now)+timedelta(hours=book['sla_hours']),'建議SLA逾期升級人工；不是歷史推估')])
    missing = sorted(set(VARIABLE.findall(proposed)))
    gate('template_variables_all_filled',[condition('no_unfilled_variables',not missing,'所有變數必有證據；缺值保留{{變數}}並攔截'),
                                        condition('business_category_confirmed',not evidence['requires_manual_classification'] and category not in ('CAT-09','CAT-10'),'無可辨識業務意圖時不產生可放行回覆')])
    draft = sanitize(proposed)
    blockers = [c['rule'] for g in gates for c in g['checks'] if not c['passed']]
    disposition = 'BLOCKED' if any(b != 'night_scheduled_queue' for b in blockers) else ('SCHEDULED' if night else 'READY_FOR_HUMAN_REVIEW')
    if sensitive_draft(proposed):
        disposition = 'BLOCKED_SENSITIVE'
    actor = context.get('actor')
    can_record = bool(customer and actor and (not phone or context.get('human_confirmation')))
    commitment = None
    if phone:
        commitment = {'party':'client','kind':commitment_kind,'description':sanitize(raw),'quantity':fields['quantity'],
                      'unit':fields['unit'],'due_date':deadline,'case_id':case['id'] if case else None,
                      'status':'stated','written_confirm_comm_id':None,
                      'pending_resolution':not can_record or (commitment_kind=='scope_add' and not case),
                      'settlement_card_id':None,'written_confirmation_draft':draft,
                      'lifecycle_status':'OPEN'}
    card = {'type':'ActionCard','version':'1.0','title':'電話承諾與書面確認待核准' if phone else '對外草稿待核准',
            'category_id':category,'disposition':disposition,'requires_human_approval':True,
            'approved_by':approver['id'] if approved else None,'blockers':blockers,
            'missing_variables':missing,'scheduled_for':scheduled.isoformat() if scheduled else None,
            'buttons':[{'action':'review_local','label':'檢視與補齊'},{'action':'approve_local','label':'人工核准（仍僅DRY_RUN）'}],
            'commitment_card':commitment,'draft':draft,'actual_sends':0,'can_send':False}
    return {'category_id':category,'classification_evidence':evidence,'extracted':{**fields,'attachments':sanitize_attachments(attachments)},
            'rag':{'category_id':category,'source_refs':book['source_refs'],'legacy_playbook_refs':book['legacy_playbook_refs'],
                   'example_status':book['example_status'],'grounded_thread_ids':book['grounded_thread_ids']},
            'draft':draft,'gates':gates,'action_card':card,'commitment':commitment,
            'recordable_communication':can_record,'status':'DRY_RUN','actual_sends':0,'can_send':False,
            'send_guard_passed':send_authorized(card['approved_by'],gates),
            'scheduled_for':card['scheduled_for'],'context_gaps':context.get('schema_gaps',[]),
            'resolved':{'customer_id':customer['id'] if customer else None,'contact_id':recipient['id'] if belongs else None,
                        'case_id':case['id'] if case else None,'quote_id':quote['id'] if quote else None,
                        'actor_id':actor['id'] if actor else None,
                        'human_confirmed_by':(context.get('human_confirmation') or {}).get('id')}}


def sanitize_attachments(items):
    return [{k:sanitize(v) if isinstance(v,str) else v for k,v in a.items() if k in ('id','name','version','sha256','source_type','status','bytes')}
            for a in items if isinstance(a,dict)]


def close_commitment(commitment):
    """本機生命週期轉移；結算卡須由人工連結，確認草稿須先存在。"""
    if not commitment_close_allowed(commitment):
        raise ValueError('INV-04：範圍變更／追加結案前須有結算卡與書面確認草稿')
    return {**commitment, 'lifecycle_status':'CLOSED'}


def persist_sql(request, result):
    """由呼叫者包在交易中；相同來源鍵不重編號、不覆寫核准記錄。"""
    key = request.get('source_key')
    if not key:
        raise ValueError('必須提供穩定source_key；不得用隨機值重複匯入')
    kind = request.get('evidence_kind','staff_request')
    channel = 'phone_memo' if result['commitment'] else request.get('channel','staff_request')
    body = sanitize(request.get('text',''))
    payload = {'subject':sanitize(request.get('subject','')),'text':body,'provenance':request.get('provenance',[]),
               'category_id':result['category_id'],'pending_commitment':result['commitment']}
    intake = 'public.switchboard_register('+','.join([
        db.literal(key),db.literal(channel),db.literal(request.get('mailbox')),
        db.literal(request['occurred_at'])+'::timestamptz',db.literal(kind),db.json_sql(payload)])+')'
    statements = [f'SELECT to_jsonb(r) FROM {intake} r;']
    ref = '(SELECT id FROM public.switchboard_intake WHERE source_key='+db.literal(key)+')'
    statements.append('UPDATE public.switchboard_intake SET payload='+db.json_sql(payload)+',channel='+db.literal(channel)+
                      ' WHERE source_key='+db.literal(key)+' AND evidence_kind='+db.literal(kind)+
                      ' AND NOT EXISTS(SELECT 1 FROM public.client_communication WHERE intake_id='+ref+');')
    resolved = result['resolved']
    org_sql = '(SELECT org_id FROM public."case" WHERE id='+db.literal(resolved['case_id'])+'::uuid)'
    org_sql = "coalesce("+org_sql+",'YX')"
    communication = result['recordable_communication']
    if communication:
        statements.append("""INSERT INTO public.client_communication(intake_id,serial_no,direction,channel,occurred_at,
         customer_id,contact_id,case_id,quote_id,our_employee_id,external_ref,thread_key,body_text,attachments,summary_120,human_confirmed_by,org_id)
         SELECT id,serial_no,'inbound',"""+','.join([
          db.literal(channel),db.literal(request['occurred_at'])+'::timestamptz',
          *[db.literal(resolved[k])+'::uuid' for k in ('customer_id','contact_id','case_id','quote_id','actor_id')],
          db.literal(key),db.literal(request.get('thread_id',key)),db.literal(body),db.json_sql(result['extracted']['attachments']),
          db.literal(body[:120]),db.literal(resolved['human_confirmed_by'])+'::uuid',org_sql])+
          ' FROM public.switchboard_intake WHERE source_key='+db.literal(key)+' ON CONFLICT(intake_id) DO NOTHING;')
    commitment = result['commitment']
    if communication and commitment and not commitment['pending_resolution']:
        statements.append('INSERT INTO public.client_commitment(source_comm_id,case_id,quote_id,customer_id,contact_id,party,kind,description,quantity,unit,due_date,owner_employee_id,org_id) SELECT id,'+
          ','.join([*[db.literal(resolved[k])+'::uuid' for k in ('case_id','quote_id','customer_id','contact_id')],
                    db.literal(commitment['party']),db.literal(commitment['kind']),db.literal(commitment['description']),
                    db.literal(commitment['quantity'])+'::numeric',db.literal(commitment['unit']),db.literal(commitment['due_date'])+'::date',
                    db.literal(resolved['actor_id'])+'::uuid',org_sql])+
          ' FROM public.client_communication WHERE intake_id='+ref+' ON CONFLICT(source_comm_id,kind) DO NOTHING;')
    approved = result['action_card']['approved_by'] if not result['action_card']['blockers'] else None
    statements.append('INSERT INTO public.outbound_message(intake_id,to_contact_id,case_id,quote_id,draft_body,attachments,approved_by,approved_at,scheduled_for,gate_results,action_card,comm_id,org_id) VALUES ('+
      ','.join([ref,*[db.literal(resolved[k])+'::uuid' for k in ('contact_id','case_id','quote_id')],db.literal(result['draft']),
                db.json_sql(result['extracted']['attachments']),db.literal(approved)+'::uuid',
                'now()' if approved else 'NULL',db.literal(result['scheduled_for'])+'::timestamptz',
                db.json_sql(result['gates']),db.json_sql(result['action_card']),
                '(SELECT id FROM public.client_communication WHERE intake_id='+ref+')',org_sql])+
      ') ON CONFLICT(intake_id) DO UPDATE SET draft_body=excluded.draft_body,attachments=excluded.attachments,'+
      'gate_results=excluded.gate_results,action_card=excluded.action_card,scheduled_for=excluded.scheduled_for '+
      'WHERE public.outbound_message.approved_by IS NULL;')
    return '\n'.join(statements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True,help='UTF-8 JSON請求檔')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--persist',action='store_true',help='僅寫入本機public暫存/草稿/已確認事件')
    args = parser.parse_args()
    request = json.loads(args.input.read_text(encoding='utf-8'))
    request.setdefault('occurred_at',datetime.now(TZ).isoformat())
    result = route(request)
    if args.persist:
        db.execute('BEGIN;\n'+persist_sql(request,result)+'\nCOMMIT;')
        result['serial_label'] = db.query('SELECT to_jsonb(serial_label) FROM public.switchboard_intake WHERE source_key='+db.literal(request['source_key']))[0]
    db.dump(args.output,result)
    print(json.dumps({'status':'DRY_RUN','actual_sends':0,'output':str(args.output)},ensure_ascii=False))


if __name__=='__main__':
    main()


def classify_as_of(connection, message):
    """Historical evaluation entry point; no current business context is read."""
    from temporal_router import TemporalRouter
    return TemporalRouter(connection).predict(message)
