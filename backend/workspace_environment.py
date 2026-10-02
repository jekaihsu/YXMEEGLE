"""Resolve legacy environments from the server-owned workspace namespace."""
from fastapi import HTTPException


def normalize_environment(state,wid,cfg):
    tenant=cfg.get('LARK_WORKER_ORGANIZATION')
    allowed={x.strip() for x in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if x.strip()}
    expected=None
    if tenant and tenant in allowed:
        if wid=='lark-'+tenant:expected='production'
        elif wid=='test-lark-'+tenant:expected='test'
    if wid.startswith('demo-'):expected='demo'
    if expected is None:
        if wid.startswith(('lark-','test-lark-')):
            raise HTTPException(403,'公司工作區尚未核實租戶設定，禁止讀寫業務資料')
        return state
    existing=state.get('environment')
    if existing not in (None,'',expected):
        raise HTTPException(409,'工作區命名與環境不一致，請由管理員核對；不可自動升為正式')
    state['environment']=expected
    return state
