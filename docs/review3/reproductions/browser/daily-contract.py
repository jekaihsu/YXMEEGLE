import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[4]))
from backend.v4_sources import daily_review
from backend.source_projection import daily_index
rows=[]
for i,status in enumerate(('已通過','已退回','待檢核')):
    review=daily_review(dict(base_token='synthetic',table_id='synthetic',record_id=str(i),fields={'檢核狀態':status}),[])
    rows.append(dict(id=str(i),date='2026-10-03',department='demo',person='synthetic',description=status,review=review))
result=daily_index(dict(projects=[dict(id='pA',code='SYNTHETIC',daily_reports=rows)],daily_unmatched=[]),project_id='pA')
Path(__file__).with_name('daily-data.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
print(json.dumps([r['review']['status'] for r in result['items']]))
