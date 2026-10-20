from ..source_lifecycle import declared
from ..sources import text, link_ids
from .domain import NODE_MAP

NEXT_NODE = {'sales': 'pm', 'pm': 'confirmation', 'confirmation': 'field', 'field': 'control',
             'control': 'mapping', 'mapping': 'report', 'report': 'pricing', 'pricing': 'settlement',
             'settlement': 'settlement'}
SOURCE_STAGE = {'執行中': 'field', '已完工': 'pricing', '已結案': 'settlement'}


def has_confirmation_link(value):
    return bool(link_ids(value)) or isinstance(value, list) and any(
        isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'].startswith('rec') for item in value)


def start_node(project, nodes):
    quotes = [q.get('fields', {}) for q in project.get('quotes', [])]
    sources = project.get('source_records', [])
    quotes += [r.get('fields', {}) for r in sources if r.get('kind') == 'quote']
    lifecycle = project.get('source_lifecycle') or {}
    won = any(text(q.get('狀態')).strip() == '成案' or bool(q.get('回傳單日期')) for q in quotes)
    won = won or any(q.get('kind') == 'won' for q in lifecycle.get('quote_workflow', []))
    confirmed = (any(has_confirmation_link(q.get('此案確認單')) for q in quotes)
                 or any(r.get('kind') in {'confirmation', 'quote_confirmation'} for r in sources)
                 or lifecycle.get('relationship') == '已關聯確認單')
    reached = {'sales'}
    if won:
        reached.add('pm')
    if confirmed:
        reached.add('confirmation')
    source_stage = SOURCE_STAGE.get(declared(project))
    if source_stage:
        reached.add(source_stage)
    for node in nodes:
        key = node.get('key')
        if key not in NEXT_NODE:
            continue
        if node.get('status') in {'in_progress', 'blocked', 'paused', 'in_review'}:
            reached.add(key)
        elif node.get('status') == 'completed':
            reached.add(NEXT_NODE[key])
    return next(key for key in reversed(NODE_MAP.values()) if key in reached)
