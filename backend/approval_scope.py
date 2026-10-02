"""Business scope of an approval, excluding source refresh and accounting noise."""
from copy import deepcopy
import json

TASK_FIELDS=('id','title','owner_id','required','start_date','due_date','original_due_date',
             'work_item_id','description','input','output','input_task_ids','revision',
             'quantity','unit','source_reassignment_pending')
SOURCE_FIELDS=('工項名稱','填報工項','工項類別','數量','合約數量','單位',
               '來源合約明細（日報關聯）','所屬成案確認單（日報關聯）','所屬案件')

# Explicit work semantics only: financial totals and read timestamps must not
# revoke a waiver, but a revised scope must, even before local task generation.
QUOTE_WORK_FIELDS=SOURCE_FIELDS+('確認範圍','工程內容','工作內容','工作項目',
    '工程項目','工程範圍','施作範圍','計價數量','工項','合約工項','合約明細',
    '合約明細工項','關聯填報工項','所屬成案確認單','工程確認單','確認單',
    '工期','開工日期','完工日期','交付期限','交付成果','成果內容')


def quote_work_scope(quotes):
    result=[]
    for quote in quotes:
        fields=quote.get('fields') or {}
        work={key:deepcopy(fields[key]) for key in QUOTE_WORK_FIELDS if key in fields}
        if not work:continue  # A cost-only mirror is not a new work scope.
        result.append({'id':quote.get('id'), 'fields':work})
    return sorted(result,key=lambda item:json.dumps(item,sort_keys=True,ensure_ascii=False))


def task_scope(task):
    result={key:deepcopy(task.get(key)) for key in TASK_FIELDS if key in task}
    result['source_missing']=bool(task.get('source_missing'))
    for key in ('source_fields','source_snapshot'):
        source=task.get(key)
        if not isinstance(source,dict):continue
        fields=source.get('source_fields',source)
        result[key]={name:deepcopy(fields[name]) for name in SOURCE_FIELDS if name in fields}
        if key=='source_snapshot':
            result[key].update({name:deepcopy(source[name]) for name in ('title','work_item_id') if name in source})
        if not result[key]:result.pop(key)
    return result


def file_scope(document):
    """Delivery identity does not change when its remote copy is verified."""
    keys=('id','file_key','version','name','size','sha256','content_hash','node_id',
          'direction','category_id','withdrawn','superseded_by','source_missing')
    return {key:deepcopy(document[key]) for key in keys if key in document}


def quote_work_scope_v3(quotes):
    # Unknown field names remain in scope. Only explicitly known accounting
    # and refresh fields can be excluded, never an unknown work relationship.
    accounting={'契約價格（未稅）','契約價格(未稅)','契約金額','報價金額','成本',
                '實際成本','實際總成本','總價','單價','稅額','未稅金額','含稅金額',
                '毛利','毛利率','建立時間','最後更新時間','更新時間','同步時間'}
    result=[]
    for entry in quotes:
        work={k:deepcopy(v) for k,v in (entry.get('fields') or {}).items() if k not in accounting}
        if work:result.append({'id':entry.get('id'),'fields':work})
    return sorted(result,key=lambda value:json.dumps(value,sort_keys=True,ensure_ascii=False))
