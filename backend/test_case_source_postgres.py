"""Compact source reads preserve JSON values on both supported databases."""
import os

import pytest
from sqlalchemy import Column, JSON, String, MetaData, Table, create_engine, insert, select

from .case_source_reads import CASE_SOURCE_FIELDS, case_source_data


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_compact_json_types_and_hidden_source_metadata(dialect):
    url='sqlite://' if dialect=='sqlite' else os.getenv('CASE_SOURCE_TEST_POSTGRES_URL')
    if not url: pytest.skip('CASE_SOURCE_TEST_POSTGRES_URL is not configured')
    engine=create_engine(url)
    metadata=MetaData()
    rows=Table('case_source_projection_test',metadata,Column('kind',String),Column('data',JSON))
    metadata.create_all(engine)
    try:
        values=[
            {'id':'quote','fields':{'工程編號':'C1','huge':['private']*100},'history':['large']*100,'source_missing':False},
            {'id':'hidden','project_id':'other','fields':{'工程編號':'hidden-code','huge':'secret'},'source_missing':True},
            {'id':'mine','project_id':'p1','fields':{'工程名稱':'本案','零':0,'空':None,'布林':False},'confirmation_ids':['a'],'history':123},
            {'id':'empty'},
        ]
        kinds=['source_quotes','source_confirmations','source_confirmations','contract_items']
        from .source_case_policy import CODE_FIELDS
        with engine.begin() as db:
            db.execute(insert(rows),[{'kind':k,'data':v} for k,v in zip(kinds,values)])
            actual=db.execute(select(case_source_data(rows.c,['p1'],dialect))).scalars().all()
        if dialect=='sqlite':
            import json
            actual=[json.loads(value) for value in actual]
        expected=[{k:v for k,v in row.items() if k in CASE_SOURCE_FIELDS} for row in values]
        for index in (0,1): expected[index]['fields']={k:v for k,v in values[index]['fields'].items() if k in CODE_FIELDS}
        assert actual==expected
    finally:
        metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_sop_projection_preserves_duplicate_quote_policy_facts(dialect):
    from datetime import date
    from .sop_import.quote_facts import case_facts
    url='sqlite://' if dialect=='sqlite' else os.getenv('CASE_SOURCE_TEST_POSTGRES_URL')
    if not url: pytest.skip('CASE_SOURCE_TEST_POSTGRES_URL is not configured')
    engine=create_engine(url)
    metadata=MetaData()
    rows=Table('sop_source_projection_test',metadata,Column('kind',String),Column('data',JSON))
    metadata.create_all(engine)
    values=[{'id':'q1','source_identity':{'base_token':'b','table_id':'t','record_id':'r1'},
             'fields':{'報價編號':'Q1','工程編號':'C115001','狀態':'成案','狀態 (1)':'C',
                       '契約價格(未稅)':12000,'huge':['irrelevant']*1000},'history':['large']*1000},
            {'id':'q2','source_identity':{'base_token':'b','table_id':'t','record_id':'r2'},
             'fields':{'報價編號':'Q1','工程編號':'C115001','確認單回傳開會日期':'2026-10-01',
                       '外業期限':'2026-10-30','案件已入帳':True}}]
    try:
        with engine.begin() as db:
            db.execute(insert(rows),[{'kind':'source_quotes','data':v} for v in values])
            actual=db.execute(select(case_source_data(rows.c,['p1'],dialect,quote_facts=True))).scalars().all()
        if dialect=='sqlite':
            import json
            actual=[json.loads(value) for value in actual]
        project={'id':'p1','quotes':[{'id':'direct','fields':{'報價編號':'Q1'}}]}
        state={'environment':'production','source_visible_record_ids':['b|t|r1','b|t|r2']}
        assert case_facts(project,dict(state,source_quotes=actual),date(2026,10,29)) == case_facts(project,dict(state,source_quotes=values),date(2026,10,29))
        assert all('history' not in row and 'huge' not in row.get('fields',{}) for row in actual)
    finally:
        metadata.drop_all(engine)
        engine.dispose()
