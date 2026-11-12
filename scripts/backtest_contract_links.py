"""Backtest exact contract links against a local dump. Print counts only."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.contract_links import parse_records, resolve_item, resolve_line, build_projection, Status


def read(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def adapt(rows,kind,table):
    return [dict(base_token='dump',table_id=table,record_id=r['record_id'],kind=kind,
                 fields={k:v for k,v in r.items() if k!='record_id'}) for r in rows]


def backtest(data_dir):
    reporting={r['record_id']:r for r in read(data_dir/'fill.ndjson')}
    for row in read(data_dir/'fill2.ndjson'):
        reporting.setdefault(row['record_id'],{}).update(row)
    records=(adapt(read(data_dir/'detail2.ndjson'),'contract','contract')+
             adapt(list(reporting.values()),'reporting','reporting')+
             adapt(read(data_dir/'confirm2.ndjson'),'confirmation','confirmation'))
    parsed=parse_records(records);known=Counter();unlinked=Counter();lines=Counter()
    for item in parsed.items:
        result=resolve_item(item,parsed.lines,ignore_native=True)
        if item.native_link_present:
            if result.status==Status.UNIQUE:
                known['unique_correct' if item.native_line_ids==(result.line_id,) else 'unique_wrong']+=1
            else: known[result.status.value]+=1
        elif result.status==Status.AMBIGUOUS:
            unlinked['ambiguous_same_qty' if result.same_quantity else 'ambiguous_different_qty']+=1
        else: unlinked[result.status.value]+=1
    for line in parsed.lines: lines[resolve_line(line,parsed.confirmations).status.value]+=1
    return dict(provenance=build_projection(records,{},{}).status,known=dict(total=sum(known.values()),**{k:known[k] for k in ('unique_correct','unique_wrong','ambiguous','none')}),
        unlinked=dict(total=sum(unlinked.values()),**{k:unlinked[k] for k in ('unique','ambiguous_same_qty','ambiguous_different_qty','none')}),
        lines=dict(total=sum(lines.values()),**{k:lines[k] for k in ('unique','ambiguous','none')}))


if __name__=='__main__':
    print(json.dumps(backtest(Path(sys.argv[1])),sort_keys=True))
