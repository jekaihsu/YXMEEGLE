"""Explicit remote destinations; isolated test writes never reach company sources."""
from .lark_adapter import RemoteFailure

FORMAL_BASES=frozenset({'JoOqbggsVar0ATsVgbcjh6IIp1g','H7W6b0PFWaVF1BsgqXJj3pQ9pXb','VwAsbezz9app3YsramgjduLYp2U','Sdw1bG1djaHsVGsRPvmjyVWipgg'})


def approved_drive_root(root,cfg):
    """Production file destination: must equal the server-approved root and never the isolated test root."""
    approved=cfg.get('LARK_DRIVE_ROOT')
    if not isinstance(root,str) or not root.strip() or not approved or root!=approved:
        raise RemoteFailure('正式 Drive 根目錄未核定於伺服器，或工作區設定不符','blocked')
    if root==cfg.get('LARK_TEST_DRIVE_ROOT'): raise RemoteFailure('正式 Drive 不得使用隔離測試目錄','blocked')
    return root


def connection_policy(wid,state,cfg,kind,for_verification=False):
    from .capability_write_policy import PAUSED_MESSAGE
    if kind in ('capability','training_record') and not for_verification:
        raise RemoteFailure(PAUSED_MESSAGE,'blocked')
    settings=state['settings']
    simulation={'mode':'simulation','simulated':True,'base_token':None,'drive_root':None}
    if wid.startswith('demo-') or state.get('environment')=='demo': return simulation
    testing=wid.startswith('test-') or state.get('environment')=='test'
    if testing:
        # Notifications, confirmations and HR writes are never live in a test workspace.
        if kind not in ('input','file'): return simulation
        mode=settings.get('test_connection_mode','simulation')
        if mode=='simulation': return simulation
        if mode!='isolated_live': raise RemoteFailure('未知測試連線模式','blocked')
        org=cfg.get('LARK_WORKER_ORGANIZATION')
        if not org or wid!='test-lark-'+org or state.get('environment')!='test': raise RemoteFailure('隔離實測工作區或公司身分不符','blocked')
        if cfg.get('LARK_WORKER_IDENTITY')!='application' or settings.get('external_enabled') is not True: raise RemoteFailure('隔離實測需明確啟用應用連線','blocked')
        result={'mode':'isolated_live','simulated':False,'base_token':None,'drive_root':None}
        if kind=='input':
            target=settings.get('test_base'); configured=cfg.get('LARK_TEST_BASE_TOKEN')
            formal=FORMAL_BASES | {settings.get(k) for k in ('v4_base','quote_base','capability_base','input_base')} | {cfg.get(k) for k in ('LARK_V4_BASE_TOKEN','LARK_QUOTE_BASE_TOKEN','LARK_CAPABILITY_BASE_TOKEN','LARK_INPUT_BASE_TOKEN')}
            if not target or target!=configured or target in formal: raise RemoteFailure('測試 Base 未同時核定於伺服器與工作區，或指向正式來源','blocked')
            table=settings.get('test_input_table')
            if (not table or table!=cfg.get('LARK_TEST_INPUT_TABLE_ID') or
                    table in {settings.get('input_table'),cfg.get('LARK_INPUT_TABLE_ID')}):
                raise RemoteFailure('測試 Input 表未同時核定於伺服器與工作區，或混用正式表','blocked')
            result.update(base_token=target,table_id=table)
        else:
            target=settings.get('test_drive_root'); configured=cfg.get('LARK_TEST_DRIVE_ROOT')
            formal={settings.get('drive_root'),cfg.get('LARK_DRIVE_ROOT')}
            if not target or target!=configured or target in formal: raise RemoteFailure('測試 Drive 目錄未同時核定於伺服器與工作區，或指向正式目錄','blocked')
            result['drive_root']=target
        return result
    org=cfg.get('LARK_WORKER_ORGANIZATION')
    if not org or wid!='lark-'+org or not for_verification and settings.get('external_enabled') is not True: raise RemoteFailure('正式外部連線未啟用或組織不符','blocked')
    result={'mode':'production','simulated':False,'base_token':None,'drive_root':approved_drive_root(settings.get('drive_root'),cfg) if kind=='file' else None}
    if kind=='input':
        target=settings.get('input_base');table=settings.get('input_table')
        protected=FORMAL_BASES | {settings.get(k) for k in ('v4_base','quote_base','capability_base')} | {cfg.get(k) for k in ('LARK_V4_BASE_TOKEN','LARK_QUOTE_BASE_TOKEN','LARK_CAPABILITY_BASE_TOKEN')}
        from .sources import configuration
        protected |= {t.get('base_token') for t in configuration(cfg)}
        if not target or target in protected or target!=cfg.get('LARK_INPUT_BASE_TOKEN') or not table or table!=cfg.get('LARK_INPUT_TABLE_ID'):
            raise RemoteFailure('Input 專用登錄表未同時核定於伺服器與工作區；不得寫回 V4、報價或薪資來源','blocked')
        if target in {settings.get('test_base'),cfg.get('LARK_TEST_BASE_TOKEN')} or table in {settings.get('test_input_table'),cfg.get('LARK_TEST_INPUT_TABLE_ID')}:
            raise RemoteFailure('正式 Input 不得混用隔離測試 Base 或資料表','blocked')
        result.update(base_token=target,table_id=table)
    return result


def require_same_policy(expected,current):
    if current!=expected: raise RemoteFailure('執行期間連線模式或目的已改變，請重新核實','blocked')
