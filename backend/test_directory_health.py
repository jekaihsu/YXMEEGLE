from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
import pytest
from .runtime_health import directory_status,snapshot
from .test_runtime_health import NOW


@pytest.mark.parametrize('age,reported,expected,blocking',[
    (0,'ready','ok',False),(599,'ready','ok',False),(600,'ready','warning',False),
    (900,'ready','warning',False),(901,'ready','stale',True),
    (900.5,'ready','stale',True),
    (-1,'ready','invalid',True),(0,'error','degraded',True),
    (0,'review_required','warning',False),
])
def test_directory_source_freshness(age,reported,expected,blocking):
    status={'status':reported,'app_id':'app','last_success_at':(NOW-timedelta(seconds=age)).isoformat()}
    @contextmanager
    def sessions():
        yield SimpleNamespace(get=lambda model,key:SimpleNamespace(data={'people_directory_status':status}))
    result=directory_status(sessions,object,{'LARK_APP_ID':'app','LARK_WORKER_ORGANIZATION':'tenant'},NOW)
    assert result['status']==expected and result['blocking']==blocking
    assert result['max_age_seconds']==900 and result['recovery_hint']


def test_healthy_worker_cannot_refresh_missing_or_expired_roster():
    worker=object();workspace=object()
    for proof,expected in [({},'missing'),({'status':'ready','app_id':'app','last_success_at':(NOW-timedelta(hours=1)).isoformat()},'stale')]:
        @contextmanager
        def sessions():
            yield SimpleNamespace(get=lambda model,key:SimpleNamespace(data=
                {'status':'ok','at':NOW.isoformat(),'last_success_at':NOW.isoformat()} if model is worker
                else {'people_directory_status':proof}))
        result=snapshot(sessions,worker,{'LARK_APP_ID':'app','LARK_WORKER_ORGANIZATION':'tenant'},now=NOW,workspace_model=workspace)
        assert result['worker']['status']=='ok'
        assert result['directory']['status']==expected and result['directory']['blocking']
        assert result['status']=='attention'
