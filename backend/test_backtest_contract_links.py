import json


def test_backtest_merges_reporting_projections_and_reuses_resolver(tmp_path):
    from scripts.backtest_contract_links import backtest
    fixtures={'detail2':[dict(record_id='l',工編號碼='X-1',外業數量=2,外業工項='Synthetic')],
              'fill':[{'record_id':'i','工項類別':'外業','基準數量':2,'來源合約明細（日報關聯）':[{'id':'l'}]},
                      dict(record_id='j',工項類別='外業',基準數量=0)],
              'fill2':[dict(record_id='i',工編號碼='X-1',填報工項='X|外業|Synthetic'),dict(record_id='j',工編號碼='X-1',填報工項='X|外業|Synthetic')],
              'confirm2':[dict(record_id='c',工程確認單編號='X')]}
    for name,rows in fixtures.items():
        (tmp_path/(name+'.ndjson')).write_text('\n'.join(json.dumps(r) for r in rows))
    assert backtest(tmp_path)==dict(known=dict(total=1,unique_correct=1,unique_wrong=0,ambiguous=0,none=0),
        unlinked=dict(total=1,unique=1,ambiguous_same_qty=0,ambiguous_different_qty=0,none=0),
        lines=dict(total=1,unique=1,ambiguous=0,none=0))
