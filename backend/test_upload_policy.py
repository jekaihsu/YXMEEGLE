import pytest
from fastapi import HTTPException
from .upload_policy import attachment_name


@pytest.mark.parametrize('name',['report\u202efdp.exe','photo\u200b.pdf','file\x00.txt','evil.cmd','evil.PS1','a:stream.pdf'])
def test_dangerous_names_rejected(name):
    with pytest.raises(HTTPException):attachment_name(name)


@pytest.mark.parametrize('name',['測量成果.dwg','觀測.26o','定位.csv','點雲.las','成果.pdf','現場.jpg'])
def test_survey_deliverables_supported(name):
    assert attachment_name(name)==name
