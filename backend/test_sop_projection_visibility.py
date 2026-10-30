import pytest
from .test_sop_lark_projection import p


@pytest.mark.parametrize('visibility', ['excluded_history', None])
def test_hidden_cases_never_project(p, visibility):
    p.project.pop('case_visibility', None)
    if visibility is not None:
        p.project['case_visibility'] = visibility
    p.worker.drain()
    assert p.fake.calls == []
