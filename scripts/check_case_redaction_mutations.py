"""Manual mutation proof: python scripts/check_case_redaction_mutations.py."""
from pathlib import Path
import json, os, subprocess, sys

ROOT=Path(__file__).resolve().parents[1]
FILES=[ROOT/'backend/case_redaction.py',ROOT/'backend/app.py']
TESTS=['backend/test_case_redaction_plan.py','backend/test_case_redaction_universe.py','backend/test_public_case_http_boundaries.py']


def main():
    originals={p:p.read_text() for p in FILES}; cr,app=FILES
    cases={
        'snapshot-after-filter':(app,'        pre=case_redaction.snapshot(result)\n        filter_visible_cases(result)',
            '        filter_visible_cases(result)\n        pre=case_redaction.snapshot(result)'),
        'apply-off':(app,'case_redaction.apply(out,case_redaction.make_plan(pre,out))','case_redaction.make_plan(pre,out)'),
        'apply-before-private':(app,'        out=filter_private_workspace(result,user)',
            "        case_redaction.apply(result,case_redaction.make_plan(pre,result))\n        out=filter_private_workspace(result,user)"),
        'source-response-off':(app,"            visible=filter_visible_cases(dict(state))",
            "            visible=filter_visible_cases(dict(state))\n            return out"),
        'source-hash-form-off':(cr,'entity_id(ident), identity(ident), source_id(ident)','entity_id(ident), identity(ident)'),
        'pipe-form-off':(cr,'entity_id(ident), identity(ident), source_id(ident)','entity_id(ident), source_id(ident)'),
        'url-form-off':(cr,"for key in ('source_url', 'url'):","for key in ():"),
        'visible-project-form-off':(cr,'admitted.update(forms(p)); allowed_codes.update(codes_of(p))','allowed_codes.update(codes_of(p))'),
        'entity-history-off':(cr,"row.pop('history', None)",'pass'),
        'case-review-off':(cr,"out.pop('source_case_review', None)",'pass'),
        'refs-blacklist':(cr,'value in plan.admitted','value not in plan.hidden'),
        'generic-net-off':(cr,'    hidden, codes = plan.hidden, plan.hidden_codes','    hidden, codes = frozenset(), frozenset()'),
        'generic-container-delete':(cr,'node[key] = None; plan.fallback += 1','node.clear(); return'),
        'global-history-strip':(cr,'    sweep(out, plan)',"    HANDLERS['history'] = lambda node,key,plan: node.pop(key, None)\n    sweep(out, plan)"),
        'visible-project-code-off':(cr,'admitted.update(forms(p)); allowed_codes.update(codes_of(p))','admitted.update(forms(p))'),
        'new-unknown-holder':(app,"        out=filter_private_workspace(result,user)",
            "        out=filter_private_workspace(result,user)\n        out['new_holder']={'case_id':'universe-base/confirmation-table/recCaseB'}"),
        'simulation-bypass-off':(app,"if out.get('environment') not in ('test','demo'):",'if True:'),
    }
    for handler in ('confirmation_ids','quote_ids','source_entity_ids','source_record_ids','unresolved_confirmation_ids',
                    'unresolved_quote_ids','unresolved','quotes','source_record_history','fields','source_conflicts','policy_summary','source_urls','source_id','record_id','blank_sources','source_provenance'):
        cases['handler-'+handler]=(cr,None,handler)
    results=[]
    directory=ROOT/'.runtime/vcc124-implementation/mutations';directory.mkdir(parents=True,exist_ok=True)
    try:
        for name,(path,old,new) in cases.items():
            for p,s in originals.items():p.write_text(s)
            source=originals[path]
            if old is None:source += f"\nHANDLERS.pop({new!r}, None)\n"
            else:
                if old not in source:raise RuntimeError('mutation anchor missing: '+name)
                source=source.replace(old,new,1)
            path.write_text(source)
            completed=subprocess.run([sys.executable,'-m','pytest',*TESTS,'-q','-k','not cost_on_scaled'],cwd=ROOT,text=True,capture_output=True)
            (directory/(name+'.log')).write_text(completed.stdout+completed.stderr)
            results.append(dict(name=name,exit=completed.returncode,detected=completed.returncode==1))
            print(name,completed.returncode,flush=True)
    finally:
        for p,s in originals.items():p.write_text(s)
    (directory/'results.json').write_text(json.dumps(results,indent=2))
    return 0 if all(r['detected'] for r in results) else 1


if __name__=='__main__':sys.exit(main())
