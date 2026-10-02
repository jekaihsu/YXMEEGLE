from copy import deepcopy
import pytest
from .v4_sources import daily_mapping_version,daily_source_version,review_mapping_version
from .operations import daily_evidence_current


def entry():
    return {'id':'daily-1','source_provenance':{'records':[
        {'id':'daily-1','kind':'daily','fields':{'內業工項':['recReport'],'工作內容':'成果一','控制組檢核':False}},
        {'id':'report-1','kind':'reporting','fields':{'來源合約明細（日報關聯）':['recContract'],'備註':'說明'}},
        {'id':'contract-1','kind':'contract','fields':{'所屬成案確認單（日報關聯）':['recConfirm'],'備註':'說明'}},
        {'id':'confirmation-1','kind':'confirmation','fields':{'工程確認單編號':'115001','主管檢核':False}},
    ],'unresolved':[]}}


@pytest.mark.parametrize('index,field,value',[
    (1,'備註','上游說明更正'),(2,'備註','合約說明更正'),(3,'主管檢核',True)])
def test_administrative_or_content_changes_preserve_pairing(index,field,value):
    original=entry();changed=deepcopy(original);changed['source_provenance']['records'][index]['fields'][field]=value
    assert daily_mapping_version(changed)==daily_mapping_version(original)


@pytest.mark.parametrize('index,field,value',[(0,'內業工項',['recOther']),
    (1,'來源合約明細（日報關聯）',['recOther']),(2,'所屬成案確認單（日報關聯）',['recOther']),
    (3,'工程確認單編號','115002')])
def test_identity_or_relationship_changes_require_pairing_again(index,field,value):
    original=entry();changed=deepcopy(original);changed['source_provenance']['records'][index]['fields'][field]=value
    assert daily_mapping_version(changed)!=daily_mapping_version(original)


def test_changed_daily_content_still_invalidates_explicit_delivery_evidence():
    original=entry();evidence={'daily_id':original['id'],'daily_source_version':daily_source_version(original)}
    assert daily_evidence_current({'daily_reports':[original]},evidence)
    changed=deepcopy(original);changed['source_provenance']['records'][0]['fields']['工作內容']='新成果'
    assert daily_mapping_version(changed)!=daily_mapping_version(original)
    assert not daily_evidence_current({'daily_reports':[changed]},evidence)


def test_legacy_pairing_migrates_only_from_saved_snapshot_not_current_fields():
    original=entry();review={'entry':deepcopy(original),'source_version':daily_source_version(original)}
    assert review_mapping_version(review)==daily_mapping_version(original)
    changed=deepcopy(original);changed['source_provenance']['records'][0]['fields']['內業工項']=['recOther']
    assert review_mapping_version(review)!=daily_mapping_version(changed)
    assert review_mapping_version({'source_version':daily_source_version(changed)}) is None
