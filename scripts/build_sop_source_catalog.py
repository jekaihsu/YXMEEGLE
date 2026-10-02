"""Build the reviewed PDF catalog, not an executable replacement for live SOPs."""
from pathlib import Path
import json
import hashlib

ROOT=Path(__file__).resolve().parents[1]
DOCS={
 'intake':'專案經理接案SOP20250826(1).pdf',
 'execution':'專案經理案件執行SOP20250826(1).pdf',
 'team':'內外業經理案件執行SOP20250826.pdf',
 'training':'內外業經理教育訓練SOP20250826.pdf',
}
nodes=[];edges=[]
def n(doc,key,title,role,unit,inputs='',outputs='',meegle='',kind='activity',note='',deadline=None):
    nodes.append(dict(id='pdf20250826.'+doc+'.'+key,document=doc,page=1,key=key,title=title,
        kind=kind,source_roles=role.split('|') if role else [],execution_unit=unit,
        inputs=inputs.split('|') if inputs else [],outputs=outputs.split('|') if outputs else [],
        observed_meegle_node_ids=meegle.split('|') if meegle else [],
        meegle_match_basis='single-case title correspondence, not template topology' if meegle else 'not observed',
        source_note=note,source_deadline=deadline,enabled=False,
        disable_reason='learning and salary evaluation disabled by owner' if doc=='training' or kind=='assessment' else 'source catalog; runtime migration and full template verification pending'))
def edge(doc,a,b,condition=None,kind='sequence'):
    edges.append(dict(source=f'pdf20250826.{doc}.{a}',target=f'pdf20250826.{doc}.{b}',condition=condition,kind=kind,evidence=f'{DOCS[doc]} page 1 visible arrow'))

# Explicit shapes in the intake diagram. Do not interpret document legends as tasks.
n('intake','demand','業主提出報價需求','業主','quotation','業主需求','業主往來紀錄表','state_14')
n('intake','number','建立報價編號','報價組','quotation','業主需求','報價編號|報價案件管制表','state_26',deadline={'event':'報價需求','offset_days':0})
n('intake','contact','通知業主報價成立','專案經理','quotation','業主需求','聯絡人及需求期程紀錄','state_28',note='圖中位於提出報價之前；同名 Meegle 節點不能據名稱認為是回簽後通知。',deadline={'event':'報價需求','offset_days':1})
n('intake','subcontract_decision','是否有下包需求','專案經理','quotation','案件需求','下包需求決定','state_29','decision')
n('intake','subcontract_quote','下包提出報價','下包廠商','subcontract_quote','下包需求','下包詢價紀錄與簽呈','state_35')
n('intake','offer','提出報價，同時通知業主已提供報價','報價組','quotation','需求|適用下包報價','報價單|通知紀錄','state_15',deadline={'event':'報價需求','offset_days':3})
n('intake','returned','報價單是否回傳','報價組','quotation','報價單','回傳狀態','state_16','decision')
n('intake','followup','追蹤報價狀況','報價組','quotation','報價單','追蹤紀錄',deadline={'event':'提出報價','offset_days':10})
n('intake','lost_or_expired','業主告知未得標／報價單有效期限到期','','quotation','未得標通知或報價期限','報價失效原因',kind='condition')
n('intake','quote_end','本報價工作結束','','quotation','未得標或到期','報價結束紀錄',kind='terminal',note='只結束報價，不是正式案件結案。')
n('intake','signed','收到回傳單，合約成立','報價組','quotation','回簽報價單或合約','收到回簽日期|回簽合約','state_25')
n('intake','case_identity','建立案件編號、製作案件回傳本','行政','case','回簽合約','工程確認單編號|案件回傳本','state_27',deadline={'event':'回簽合約','offset_days':1})
n('intake','award_contact','得標後聯絡業主','專案經理','case','回簽合約','案件聯絡人|進場條件|工作期程|成果繳交日期形式內容','state_17',deadline={'event':'回簽合約','offset_days':2})
n('intake','confirmation','確認單製作並將確認單傳遞至各單位','專案經理|報價組','confirmation_version','案件資料|成果範圍','確認單|各單位傳遞紀錄','state_4|state_83',deadline={'event':'回簽合約','offset_days':5})
n('intake','permits','執行工務確認單','行政|工務行政','dispatch','進場及工務需求','保險|出入場申請|履約保證金|航拍申請','state_2',note='依適用工務條件逐項；不將公務、計價、結算合併成一個行政完成。')
for a,b in [('demand','number'),('number','contact'),('contact','subcontract_decision'),('subcontract_quote','offer'),('offer','returned'),('followup','lost_or_expired'),('lost_or_expired','quote_end'),('signed','case_identity'),('case_identity','award_contact'),('award_contact','confirmation')]:edge('intake',a,b)
edge('intake','subcontract_decision','subcontract_quote','有');edge('intake','subcontract_decision','offer','無')
edge('intake','returned','signed','有');edge('intake','returned','followup','無')
edge('intake','confirmation','permits',kind='parallel_branch')

n('execution','confirmation','確認單製作並將確認單傳遞至各單位','專案經理|報價組','confirmation_version','回簽合約','確認單|傳遞紀錄','state_4|state_83',deadline={'event':'回簽合約','offset_days':5})
n('execution','permits','執行工務確認單','行政|工務行政','dispatch','適用進場條件','工務行政證明','state_2')
n('execution','field_accept','外業確認單確認','外業經理','confirmation_version','確認單','外業確認紀錄','state_39')
n('execution','field_contact','外業派工前聯繫','專案經理|外業組長','dispatch','派工期程','業主往來紀錄表|Mail或Line聯絡佐證','state_40',deadline={'event':'外業派工','offset_days':-3})
n('execution','revision','確認單修正','','confirmation_version','確認意見','新版確認單','state_41',note='重大範圍/期限變更依後續核定 Lark 原生程序，PDF未列核准席位。')
n('execution','field_work','外業作業','外業組','dispatch','工務證明|派工|確認單','外業成果','state_78|state_42')
n('execution','field_tracking','外業節點追蹤','行政|外業經理','dispatch','工作進度','節點追蹤紀錄','state_43')
n('execution','field_delivery','外業完工或階段性通知','專案經理','delivery_batch','外業成果','完工或階段性通知|長期案件定期通知','state_44',deadline={'event':'外業完工','offset_days':2})
n('execution','indoor_work','內業作業','內業組','contract_item_assignment','確認單|適用外業成果','內業成果','state_45')
n('execution','indoor_tracking','內業節點追蹤','行政|內業經理','contract_item_assignment','內業進度','節點追蹤紀錄','state_46')
n('execution','indoor_accept','內業確認單確認','內業經理','confirmation_version','確認單','內業確認紀錄','state_38')
n('execution','delivery','提交成果及計價數量','工務助理','delivery_batch','本批成果','成果|計價數量|成果繳交日期','state_47',note='後續核定由控制/圖資/報告各組提交，再交行政計價。')
n('execution','client_accept','通知業主成果已繳交、業主確認計價單內容','工務助理','delivery_batch','本批成果與計價數量','通知佐證|業主確認紀錄','state_48',deadline={'event':'成果繳交','offset_days':0})
n('execution','correction','成果是否需補充修改','工務助理','delivery_batch','業主意見|本批成果','補正需求或無需補正紀錄','state_49','decision',deadline={'event':'提交成果','repeat_days':5})
n('execution','billing_condition','是否達成請款條件','專案經理','payment_batch','合約請款條件|本批交付','條件檢核證據','state_56|state_74','decision')
n('execution','pricing','繳交計價單','專案經理','payment_batch','合格請款條件|本批計價數量','計價單','state_55',deadline={'event':'達成計價條件','offset_days':3})
n('execution','invoice','案件請款、進行客戶滿意度調查','行政','payment_batch','計價單','請款證明|滿意度調查發送與回覆狀態','state_59')
n('execution','received','是否入帳','行政','payment_batch','應收資料|實收證明','入帳核對紀錄','state_60|state_72','decision',note='回執/共同核准不是實收付證據；不得用來源狀態或空列表推論已結清。')
n('execution','receivable_tracking','請款情況追蹤','行政','payment_batch','未入帳請款','追蹤紀錄',deadline={'event':'請款','repeat_days':5})
n('execution','subcontract_decision','是否有下包','行政','case','下包範圍|交付資料','適用下包清單','state_61','decision')
n('execution','subcontract_payment','通知下包廠商請款及撥款','行政','subcontract_payment_batch','下包成果及請款','核准|付款證明','state_68')
n('execution','subcontract_tracking','下包入帳追蹤','行政','subcontract_payment_batch','下包請款','下包實收/付款證據|追蹤紀錄','state_71','decision',deadline={'event':'下包請款','repeat_days':5})
n('execution','settlement','案件結算表製作','副總|專案經理|工務助理','case_closure','實收核對|適用下包結清','案件結算表','state_69',note='後續核定 PM＋行政共同確認；原PDF沒有指定某個Base/table/field。')
n('execution','close','案件結束','','case_closure','有效結算表|財務結清|交付完成','結案證明','state_70','terminal')
n('execution','client_contact','執行中業主聯繫','專案經理','recurring','執行中案件','業主往來紀錄','state_50',deadline={'event':'工作期間','repeat_days':5})
n('execution','weekly_field','節點檢討與紀錄（工程）','行政','recurring','外內業進度','節點檢討紀錄','state_51',deadline={'repeat':'weekly'})
n('execution','weekly_pricing','節點檢討與紀錄（計價）','行政','recurring','計價進度','節點檢討紀錄','state_57',deadline={'repeat':'weekly'})
n('execution','assessment_field','考評與結算計算（工程）','行政','assessment','節點檢討','月考評與結算表','state_52','assessment',note='依最新裁示停用考評，不移除獨立案件結算。')
n('execution','assessment_pricing','考評與結算計算（計價）','行政','assessment','節點檢討','月考評與結算表','state_58','assessment')
for a,b in [('confirmation','field_contact'),('field_contact','revision'),('revision','field_work'),('field_work','field_tracking'),('field_tracking','field_delivery'),('field_delivery','indoor_work'),('indoor_work','indoor_tracking'),('indoor_tracking','delivery'),('delivery','client_accept'),('client_accept','correction'),('pricing','invoice'),('invoice','received'),('receivable_tracking','received'),('settlement','close'),('weekly_field','assessment_field'),('weekly_pricing','assessment_pricing')]:edge('execution',a,b)
for a,b in [('confirmation','permits'),('confirmation','field_accept'),('confirmation','indoor_accept'),('confirmation','client_contact'),('field_tracking','weekly_field'),('indoor_tracking','weekly_field'),('pricing','weekly_pricing')]:edge('execution',a,b,kind='parallel_branch')
edge('execution','correction','client_accept','是，補正後重新確認','loop');edge('execution','correction','pricing','否；並須請款條件達成')
edge('execution','billing_condition','pricing','是');edge('execution','received','receivable_tracking','否','loop');edge('execution','received','subcontract_decision','是')
edge('execution','subcontract_decision','settlement','無');edge('execution','subcontract_decision','subcontract_payment','有')
edge('execution','subcontract_payment','subcontract_tracking');edge('execution','subcontract_tracking','settlement','入帳');edge('execution','subcontract_tracking','subcontract_payment','未入帳','loop')

n('team','confirmation','確認單','專案經理','confirmation_version','專案經理簽核','確認單')
n('team','worklist','建立工作總表','內業經理|外業經理','confirmation_version','確認單','內外業工作總表|傳遞資訊查核',deadline={'event':'收到確認單','offset_days':1})
n('team','dispatch','工作分派後傳遞給各組長','內業經理|外業經理','dispatch','工作總表','組長收件與工作分派')
n('team','schedule','工作預排總表','組長','schedule_week','工作分派','預排表|預排及實際節點表',deadline={'field':'週三正常班表下班','indoor':'週四正常班表下班'})
n('team','progress','工作進度管控','內業經理|外業經理','recurring','工作總表|預排表','工進|人力車輛儀器配置|衝突排除',deadline={'repeat':'daily'})
n('team','review','檢討目前工進及工作情況','內業經理|外業經理','dispatch','工進','檢討紀錄|缺失單',kind='decision')
n('team','reschedule','工作預排需調整','專案經理','schedule_version','預排調整需求','新版預排')
n('team','done','工作完成','組長','delivery_batch','本批工作成果','完工資料',kind='milestone')
n('team','signoff','簽核確認單','組長|專案經理','delivery_batch','組長提交完工資料','專案經理簽核確認單',deadline={'event':'工作完成','offset_days':3})
n('team','group_settlement','進行各組案件結算表／阿米巴計算表','內業經理|外業經理','salary_assessment','各組工作成果','各組案件結算表|阿米巴計算成果',kind='assessment',deadline={'repeat':'monthly'},note='涉及薪資/配點，保留原文盤點但不啟用、不回寫；不混成財務結案。')
n('team','node_review','節點檢討與紀錄','行政','recurring','工作進度','節點紀錄')
n('team','monthly_assessment','考評與結算計算','行政','assessment','節點檢討','月考評與結算表','',kind='assessment')
for a,b in [('confirmation','worklist'),('worklist','dispatch'),('dispatch','schedule'),('schedule','progress'),('progress','review'),('reschedule','review'),('done','signoff'),('signoff','group_settlement'),('node_review','monthly_assessment')]:edge('team',a,b)
edge('team','review','done','完成');edge('team','progress','node_review',kind='parallel_branch')

for key,title,role,inputs,outputs in [
 ('demand','教育訓練需求表','專案經理','','需求表'),('plan','教育訓練計畫總表','','需求表|能力地圖','計畫總表'),
 ('capacity','能力地圖','','能力資料','能力地圖'),('progress','檢討目前工進及工作情況','','工作進度','工作空檔'),
 ('delegate','代理人設定','','代理人候選','代理設定'),('training','安排教育訓練','','計畫總表|工作空檔','教育執行紀錄'),
 ('outcome','檢討教育訓練成果及生存線狀況','','教育執行紀錄','計畫更新|能力地圖與生存線差異'),
 ('qualified','檢視代理人能力是否合乎要求','','代理設定|能力地圖','資格檢核'),('accepted','合格代理人','','資格通過','合格代理人')]:
    n('training',key,title,role,'disabled_learning',inputs,outputs,kind='decision' if key in ('progress','outcome','qualified') else 'activity')
for a,b in [('demand','plan'),('capacity','plan'),('plan','training'),('delegate','training'),('training','outcome'),('outcome','plan')]:edge('training',a,b)
edge('training','progress','training','工作空檔');edge('training','qualified','accepted','合格');edge('training','qualified','training','持續訓練','loop');edge('training','qualified','delegate','變更代理人','loop')

identifiers={v['id'] for v in nodes}
assert len(identifiers)==len(nodes)
assert all(e['source'] in identifiers and e['target'] in identifiers for e in edges)
sources={k:{'file':v,'pages':1,'sha256':hashlib.sha256((ROOT/v).read_bytes()).hexdigest(),'review':'text extraction plus rendered full-page visual inspection'} for k,v in DOCS.items()}
schema=json.loads((ROOT/'.runtime/source-private-schema-20260927.json').read_text(encoding='utf-8-sig'))
finance_fields=[{'kind':t['kind'],'table_id':t['table_id'],'fields':[{'name':f['field_name'],'id':f['field_id'],'type':f['type']} for f in t['fields'] if any(w in f['field_name'] for w in ('收款','付款','入帳','結算','合約','契約','實際總成本','預估總成本','請款'))]} for t in schema if t['kind'] in ('confirmation','quote','quote_confirmation','contract')]
result={'schema_version':1,'catalog_version':'pdf20250826-reviewed-20260928','runtime_enabled':False,
 'purpose':'source evidence catalog; not imported historical cases and not a published workflow migration',
 'sources':sources,'nodes':nodes,'edges':edges,
 'artifacts':{'intake':['業主往來紀錄表','報價案件管制表','工務確認單','下包詢價紀錄與簽呈'],
              'team':['內外業工作總表(含節點)','內外業預排(含完成節點與檢討)','預排調整與節點控管','人力車輛儀器配置','工進掌握與工作衝突排除','完工確認單','阿米巴計算成果'],
              'training':['教育訓練計畫總表','教育執行紀錄','各組教育訓練目標','各組教育訓練執行紀錄','能力地圖與生存線差異']},
 'disabled_assessment_metrics':['報價逾期次數','違反SOP次數','案件逾期次數','客戶滿意度評分','總營業額達成率','預排確認','繳交資料完整率','工作良率','教育訓練執行次數','能力地圖達成率'],
 'overrides':['learning/training/capability/salary assessment disabled','normal shift end replaces fixed 17:00','ordinary deliverables confirmed locally; major approvals use native Lark','structured Input remains Base; files remain Drive','PM and designated admin jointly verify financial stages'],
 'completion_scopes':{'quotation':'a quote outcome, not case closure','dispatch':'one scheduled assignment','delivery_batch':'one immutable set of task/material snapshots; additional batch does not erase prior approval','payment_batch':'one claim and its receipts; approval does not equal payment','case_closure':'all applicable delivery obligations and authoritative financial closure plus required confirmations'},
 'templates':[{'id':'334662','status':'one case inventory only','sample_workitem':'24602542','observed_nodes':52,'observed_subtasks':51},{'id':'566082','status':'not read; CLI login pending'}],
 'finance_schema_candidates':finance_fields,
 'unresolved':['Both full native template definitions/edges/required Input fields','PDF day offsets calendar/workday semantics follow separately approved policy; original PDF does not specify','Exact full node arrow joining/branch predicates where crossing lines lack junction markers','Payment ledger and settlement source table/field mapping is not specified in the four PDFs','Satisfaction unanswered allowed per later decision, never fabricate rating','No source/API entitlement can be inferred from a PDF artifact name']}
path=ROOT/'docs'/'SOP_CANONICAL_SOURCE_CATALOG_20260928.json'
path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# 四份 PDF 與 Meegle SOP 來源對照（2026-09-28）','',
 '已逐張閱讀原圖與文字：4 份、各 1 頁。下列 65 個有語意的作業／判斷／里程碑給予穩定來源 ID，69 條可辨識關係另存 JSON。圖例、表單清單、指標不冒充任務。',
 '**這是核對資料，不是已發布的完整替代 SOP。** 不自動匯入 Meegle 舊案，不把原圖箭頭排列硬套成九部門線性完成，也不啟用薪資／訓練／考評。',
 '', '## 可重現原始證據','',
 '`python -X utf8 scripts/extract_sop_evidence.py` 保存逐頁文字、PNG 及 SHA256；`python -X utf8 scripts/build_sop_source_catalog.py` 產生本表與 `SOP_CANONICAL_SOURCE_CATALOG_20260928.json`。',
 '渲染與文字位於 `.runtime/sop-audit-20260928/`。原始 PDF 檔不變。',
 '', '## 已確認的關鍵邊界','',
 '- 報價結束只結束該報價。回簽後建立案號、確認單；多報價可對同確認單，不能把每張報價算成正式案件。',
 '- 外業圖明寫「階段性通知」，成果與計價需以批次為單位；新增下一批不推翻前批已核准交付，修訂前批則明確指定被取代版本。',
 '- 「是否入帳」與下包「未入帳／入帳」是實收付判斷；Lark 核准是核准證明，不等於銀行入帳或帳务結清。',
 '- 案件結算表与月考評／阿米巴表用途不同。案件財務結算保留，後兩者依最新裁示停用。',
 '- 各組進度、工作預排、檢討、業主聯繫可平行或週期執行；部門／角色不是流程階段，不能以行政角色合併公務、請款、結案。',
 '- 原圖「通知業主報價成立」在正式提出報價之前；保留原名與位置，不以同名推論回簽後事件。',
 '- 工期 0／1／2／3／5／10 日取原圖事件錨點；工作日計算與正常班表下班採後續核定政策，不聲稱 PDF 本身已定義工作日。',
 '', '## Meegle 兩範本可驗範圍','',
 '| 範本 | 目前证據 | 尚缺 |','| --- | --- | --- |',
 '| 334662 詠翔接案 SOP | 先前保存案件 24602542 三頁，52 節點、51 子任務 | 範本本體、完整拓樸、必填 Input、角色及附件 gate；個案追加不能自動當範本 |',
 '| 566082 詠翔 SOP 精簡版 | 先前可見範本 ID／名稱 | 尚無範本本體及任務清單，不能聲稱讀完 |',
 '', '本次 CLI auth status：project.larksuite.com 無 local token；預設瀏覽器 callback 不適用目前終端，已由官方 CLI device flow 開獨立 `sopaudit20260928` 登入頁。仍待使用者登入；不使用新應用密鑰，也沒有碰既有 Lark 管理分頁。',
 '', '## 財務來源與可執行契約','',
 '四 PDF 指定的是「案件結算表」「實際入帳」「下包入帳」及對應交付證明，没有指定唯一 Base/table/field。已核實保存的 schema 可供唯讀來源投影：',
 '', '| 來源 | 已存在欄位 | 能證明／不能推論 |','| --- | --- | --- |',
 '| 報價總表 | 案件已入帳、累計已入帳、累計已請款、案件可請款總額、可請款未請、入帳資料檢核、入帳日期、付款條件 | 可建立來源收款核對摘要；需保留每報價原始識別、金額範圍／稅基，不重複加總；無法單憑勾選證明下包已付 |',
 '| V4 工程確認單 | 案件已入帳、入帳日期、合約總額、預估總成本、實際總成本 | 原始來源宣告與成本摘要；實際成本不等於已付成本 |',
 '| 合約明細工項 | 合約項次、工作項目、單位、數量、原始／報出金額、關聯填報工項 | 建獨立合約工項識別，跨組指派引用同實體；不重複計合約金額，也不回寫薪資配點 |',
 '', '完整欄位 ID/type 僅採已保存 schema，列於 JSON `finance_schema_candidates`。已通知來源 owner 納入唯讀 normalized projection。現阶段未取得付款台帳／下包結清權威欄位，不以本地空 payment_batches 或零差額當結清。',
 '', '正式 gate 接入順序：唯一來源鏈與範圍→有效收付證據／結算表→目前版本 PM＋行政原生財務核准→全部適用交付及前置完成→工作台結案。未對齊來源時回報具體缺項，不設不存在的本地帳務要求來假稱整合完成。',
 '', '## 穩定來源 ID 對照','']
for doc,name in DOCS.items():
    lines += [f'### {name}', '', '| 穩定 ID（前綴 pdf20250826） | 原圖工作 | 原角色 | 完成範圍 | 原 Meegle 對照 |', '| --- | --- | --- | --- | --- |']
    for item in nodes:
        if item['document']!=doc:continue
        lines.append('| '+'.'.join((doc,item['key']))+' | '+item['title']+' | '+'、'.join(item['source_roles'])+' | '+item['execution_unit']+' | '+'、'.join(item['observed_meegle_node_ids'])+' |')
    lines.append('')
lines += ['## 尚未解決而不猜的項目','',
 '1. 兩個原生 Meegle 範本、第二範本特有工項、條件必填欄位及附件仍需真正登入讀取。',
 '2. 圖中無箭頭接點標示的交叉線，僅保存可辨識分支；不把全部視圖順序當依賴 DAG，也不假定所有技術組一律串行。',
 '3. 新來源 catalog 尚未發布到既有案件；既有已核准或已填成果的 SOP 升版須保留原 key、修訂版本與確認歷史。',
 '4. 財務下包結清／稅基／重複報價範圍需明確權威欄位與真資料比對；原 PDF 沒有提供欄位映射，不能發明。','']
(ROOT/'docs'/'SOP_SOURCE_CROSSWALK_20260928.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'nodes':len(nodes),'edges':len(edges),'documents':len(sources),'output':str(path)},ensure_ascii=False))
