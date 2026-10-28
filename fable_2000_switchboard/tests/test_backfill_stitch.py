from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import pytest
from backfill_stitch_50k import parse_eml,load_sheet,stitch,main
FIXTURE=Path('/workspace/fable/r30/files/_fixture')

def test_three_stitch_rules_and_external_serial_quarantine():
    mails=[parse_eml(p,{}) for p in sorted((FIXTURE/'eml').glob('*.eml'))]
    forward=next(m for m in mails if m.from_addr=='yongxiang.ltd@gmail.com')
    extra=replace(forward,message_id='<r31b-second-forward@test>',references=[],in_reply_to=None,quoted_hash=None,sent_at=forward.sent_at+timedelta(hours=1))
    links,members,roots,quarantine=stitch(mails+[extra],load_sheet(FIXTURE/'sheet.csv'))
    assert set(l.rule for l in links)=={'references','serial_no','quoted_hash'}
    assert any(q['kind']=='external_serial_claim' for q in quarantine)
    assert extra.message_id in members[6084]
    assert roots[6084]!=forward.message_id

def test_serial_does_not_stitch_across_organizations():
    mails=[parse_eml(p,{}) for p in sorted((FIXTURE/'eml').glob('*.eml'))]
    forward=next(m for m in mails if m.from_addr=='yongxiang.ltd@gmail.com')
    other=replace(forward,message_id='<r31b-other-org@test>',org_id='SJ',references=[],in_reply_to=None,quoted_hash=None)
    links,members,roots,quarantine=stitch(mails+[other],load_sheet(FIXTURE/'sheet.csv'))
    assert not any(l.message_id==other.message_id for l in links)
    assert other.message_id not in members[6084]
    assert any(q['org_id']=='SJ' and q['kind']=='serial_without_original' for q in quarantine)

def test_no_empty_input_can_report_success(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(['--eml-dir',str(tmp_path),'--sheet-csv',str(FIXTURE/'sheet.csv'),'--dry-run'])
    assert exc.value.code!=0
