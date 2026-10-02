"""Produce a review-only SOP inventory from saved, read-only Meegle responses."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
nodes = []
for page in range(1, 4):
    data = json.loads((root / '.runtime' / f'meegle-nodes-24602542-p{page}.json').read_text(encoding='utf-8-sig'))
    nodes.extend(data['list'])
assert len(nodes) == 52 and len({n['basic']['node_key'] for n in nodes}) == 52
subtasks = sum(len(n.get('sub_tasks', [])) for n in nodes)
lines = [
    '# Meegle SOP 原始節點盤點：第一批', '',
    '日期：2026-09-25｜用途：原始名稱核對，尚未核定新節點歸屬。', '',
    '來源：詠翔業務管理系統／業務流程／詠翔接案SOP（template 334662），工作項 24602542。',
    f'已讀完三頁，共 52 個節點、{subtasks} 個子任務實例。',
    '這是單一案件的完整節點清單，可能含個案追加項目；不是全空間正式 SOP 範本已盤點完成。API 順序不代表流程拓樸順序。',
    '另一個已發現範本「詠翔SOP精簡版」（566082）尚待讀取比對。', '',
    '| 原節點 ID | 原節點名称 | 本案子任務（保留原文） |',
    '| --- | --- | --- |',
]
def esc(value):
    return str(value).replace('|', '\\|').replace('\r', '').replace('\n', '<br>')
for node in nodes:
    tasks = '<br>'.join(esc(t['sub_task_name']) for t in node.get('sub_tasks', [])) or '本案未列子任務'
    lines.append(f"| {esc(node['basic']['node_key'])} | {esc(node['basic']['name'])} | {tasks} |")
lines += ['', '注意：Start、是、否、有等可能為流程分支；需取得拓樸及條件後對應為系統規則，不能直接當作同名 SOP 合併。同名不同 ID 的節點也保留至核對完成。',
          'Input 欄位、說明、附件及完成條件另需補讀，清單未宣稱已涵蓋完整功能。', '']
target = root / 'docs' / 'MEEGLE_SOP_INVENTORY_01.md'
target.write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps({'nodes': len(nodes), 'subtasks': subtasks, 'output': str(target)}, ensure_ascii=True))
