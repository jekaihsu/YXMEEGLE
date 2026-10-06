"""Daily review enum survives source -> projection unchanged (synthetic data only)."""
import pytest
from .source_projection import daily_index
from .v4_sources import daily_review

CASES=[('已通過','approved'),('已退回','returned'),('待檢核','pending'),('','unverified'),(None,'unverified'),('已審核','unverified')]


def record(raw):
    fields={} if raw is None else {'檢核狀態':raw}
    return {'id':'rec','base_token':'bas','table_id':'tbl','record_id':'rec1','fields':fields}


@pytest.mark.parametrize('raw,expected',CASES)
def test_source_status_maps_to_api_enum(raw,expected):
    assert daily_review(record(raw),[])['status']==expected


def test_projection_returns_review_status_unchanged():
    entries=[{'id':f'd{i}','date':'2026-10-01','review':daily_review(record(raw),[])} for i,(raw,_) in enumerate(CASES)]
    state={'projects':[{'id':'p1','code':'SYN','daily_reports':entries}],'daily_unmatched':[]}
    items={r['id']:r['review']['status'] for r in daily_index(state)['items']}
    assert items=={f'd{i}':expected for i,(_,expected) in enumerate(CASES)}
