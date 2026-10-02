"""Prepare an inactive, existing-workbench-tab variant without running a browser."""
from pathlib import Path
import json

root=Path(__file__).resolve().parents[1]
source=root/'.runtime/isolated-input-acceptance-browser-step.js'
target=root/'.runtime/isolated-input-acceptance-workbench-tab.js'
code=source.read_text(encoding='utf-8')
old=" if(new URL(page.url()).origin!==expected.origin)throw Error('Wrong browser origin');"
new=""" const candidates=page.context().pages().filter(candidate=>{
  try{return new URL(candidate.url()).origin===expected.origin}catch{return false}
 });
 if(!candidates.length)throw Error('No existing workbench tab; do not select an unrelated app or create a new session');
 page=candidates[0]; // Existing tab only; no navigation, focus or change to the user's current tab.
 if(page.isClosed())throw Error('Workbench tab closed');"""
if code.count(old)!=1 or 'const EXECUTE=false;' not in code:
    raise SystemExit('Unexpected source or enabled source; preserve checkpoint and review manually')
target.write_text(code.replace(old,new),encoding='utf-8')
print(json.dumps({'prepared':True,'executed':False,'default_execute':False,'file':str(target.relative_to(root))}))
