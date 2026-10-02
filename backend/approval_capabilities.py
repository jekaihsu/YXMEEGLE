"""Public approval capabilities derived from server code, never claimed from tokens."""
import json
import re
from datetime import datetime, timezone

DEFINITION_HEALTH_MAX_AGE_SECONDS = 900
DEFINITION_KINDS = ('change', 'extension', 'node_skip', 'financial')


def definition_health(cfg, evidence, mappings, kind):
    """Fresh read-only health evidence, never business approval authority."""
    from .native_approval import digest
    if not isinstance(evidence, dict) or evidence.get('schema_version') != 1:
        return None
    if not (evidence.get('app_id') == cfg.get('LARK_APP_ID') and cfg.get('LARK_APP_ID')
            and evidence.get('tenant') == cfg.get('LARK_WORKER_ORGANIZATION')
            and cfg.get('LARK_WORKER_ORGANIZATION')
            and evidence.get('workspace_id') == 'lark-' + cfg['LARK_WORKER_ORGANIZATION']
            and evidence.get('mapping_set_hash') == digest(mappings)):
        return None
    by_type = evidence.get('by_type')
    proof = by_type.get(kind) if isinstance(by_type, dict) else None
    if not isinstance(proof, dict) or proof.get('status') != 'verified':
        return None
    if (proof.get('mapping_hash') != digest(mappings.get(kind)) or
            not re.fullmatch(r'[0-9a-f]{64}', str(proof.get('definition_hash') or ''))):
        return None
    try:
        stamp = datetime.fromisoformat(proof['verified_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= DEFINITION_HEALTH_MAX_AGE_SECONDS:
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return {'verified_at': proof['verified_at'], 'definition_hash': proof['definition_hash'],
            'mapping_hash': proof['mapping_hash']}


def approval_connection(cfg, *, simulation_available=False, definition_verification=None):
    try:mappings=json.loads(cfg.get('LARK_NATIVE_APPROVAL_MAPPINGS_JSON','{}'))
    except (ValueError,TypeError):mappings={}
    if not isinstance(mappings,dict):mappings={}
    enabled=str(cfg.get('LARK_NATIVE_APPROVAL_SUBMIT_ENABLED','false')).lower()=='true'
    enabled=enabled and str(cfg.get('DEMO_MODE','false')).lower()!='true' and not simulation_available
    definitions = {
        'change': ('設計變更', 'LARK_CHANGE_APPROVAL_CODE'),
        'extension': ('期限展延', 'LARK_EXTENSION_APPROVAL_CODE'),
        'node_skip': ('節點跳過', 'LARK_NODE_SKIP_APPROVAL_CODE'),
        'financial': ('財務交付', 'LARK_FINANCIAL_APPROVAL_CODE'),
    }
    by_type = {}
    for kind, (label, key) in definitions.items():
        mapping=mappings.get(kind)
        mapped=isinstance(mapping,dict) and mapping.get('kind')==kind and bool(mapping.get('approval_code'))
        configured = mapped or bool(str(cfg.get(key) or '').strip())
        proof = definition_health(cfg, definition_verification, mappings, kind) if not simulation_available and mapped else None
        by_type[kind] = {
            'definition_configured': configured,
            'definition_mapping_verified': bool(proof),
            'verified_at': proof['verified_at'] if proof else None,
            'available': bool(enabled and mapped),
            'simulation_available': bool(simulation_available),
            'status': 'ready_for_verification' if enabled and mapped else 'disabled',
            'blockers': ([] if configured else [{'code': 'definition_missing', 'label': f'尚未指定{label}使用的審批單'}]),
        }
    all_verified = all(value['definition_mapping_verified'] for value in by_type.values())
    return {
        'mode': 'simulation' if simulation_available else 'formal',
        'simulation_available': bool(simulation_available),
        'native_submit': {
            'status': 'ready_for_verification' if enabled else 'disabled', 'available': any(x['available'] for x in by_type.values()),
            'enabled':enabled,'implemented':True,
            'label': '逐筆核對後可送審' if enabled else '正式送審尚未啟用',
            'blockers': [
                *([] if enabled else [{'code':'submission_disabled','label':'正式送審尚未啟用；可查回既有申請'}]),
                *([] if all_verified else [{'code': 'definition_mapping_unverified', 'label': '審批內容與核准流程尚未核對'}]),
                {'code': 'result_binding_unverified', 'label': '尚未確認核准結果對應的案件與版本'},
                {'code': 'end_to_end_unverified', 'label': '尚未完成真實送審與核准回傳驗證'},
            ],
            'by_type': by_type,
        },
        'existing_instance_read': {
            'implemented': True, 'verified': False,
            'label': '可查詢既有審批；查詢結果不會自動核准本案',
        },
        'definition_mapping_verified': all_verified,
        'definition_health_max_age_seconds': DEFINITION_HEALTH_MAX_AGE_SECONDS,
        'trusted_result_binding': False,
    }
