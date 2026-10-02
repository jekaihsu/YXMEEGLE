"""Document type is independent from workflow node and input/output purpose."""
import re
from copy import deepcopy
from .workflow import require, event

DEFAULT_CATEGORIES = [
    {'id':'quote_confirmation','name':'報價／確認單','active':True},
    {'id':'field_raw','name':'外業原始資料','active':True},
    {'id':'photo','name':'照片','active':True},
    {'id':'drawing','name':'圖資圖面','active':True},
    {'id':'report','name':'成果報告','active':True},
    {'id':'evidence','name':'交付佐證','active':True},
    {'id':'other','name':'其他','active':True},
]


def categories(state):
    return deepcopy(state.get('file_categories', DEFAULT_CATEGORIES))


def validate_category(state, category_id):
    require(any(c['id']==category_id and c.get('active',True) for c in categories(state)),
            '文件分類不存在或已停用',422)


def save_category(state, actor, payload):
    require(actor.get('role')=='manager','文件分類僅限管理員維護',403)
    ident=str(payload.get('id','')); name=str(payload.get('name','')).strip()
    require(bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',ident)) and 1<=len(name)<=40,
            '分類代碼或名稱格式不正確',422)
    active=payload.get('active',True); require(type(active) is bool,'active 必須為布林值',422)
    require(ident!='other' or active,'其他分類必須保留供未分類歷史資料使用',422)
    items=categories(state)
    require(not any(c['name']==name and c['id']!=ident for c in items),'分類名稱已存在',409)
    prior=next((c for c in items if c['id']==ident),None)
    value={'id':ident,'name':name,'active':active}
    state['file_categories']=[value if c['id']==ident else c for c in items]+([] if prior else [value])
    event(state,actor,'file_category_save',message='更新文件分類')
