import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const b=await build({stdin:{contents:"export * from './src/sopActionReasons';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const m=await import('data:text/javascript;base64,'+Buffer.from(b.outputFiles[0].text).toString('base64'));
const task=(over={})=>({id:'t',title:'T',state:'pending',applicability:'applicable',participants:{executor:'u1'},allowedActions:['block'],completionBlockedReason:null,assignmentBlockedReason:undefined,...over});
const group=(v,label)=>v.unavailable.find(g=>g.actions.some(a=>a.label===label));

test('P4b reason present: the server-supplied reason is shown for that action, by kind',()=>{
 const stage=m.sopActionView(task({completionBlockedReason:'node_not_enrolled'}),true);
 assert.equal(group(stage,'完成').kind,'stage_closed');assert.match(group(stage,'完成').reason,/流程階段尚未開放/);
 const dep=m.sopActionView(task({completionBlockedReason:'completion_evidence_missing'}),true);
 assert.equal(group(dep,'完成').kind,'dependency');assert.match(group(dep,'完成').reason,/前置條件未完成/);
 const un=m.sopActionView(task({completionBlockedReason:'participant_unresolved'}),true);assert.equal(group(un,'完成').kind,'unassigned');
 const off=m.sopActionView(task({assignmentBlockedReason:'import_unavailable'}),true);
 assert.equal(group(off,'編輯任務內容').kind,'writes_disabled');assert.equal(group(off,'開始').kind,'writes_disabled');
 const perm=m.sopActionView(task({assignmentBlockedReason:'forbidden'}),true);assert.equal(group(perm,'開始').kind,'no_permission');
 const unknown=m.sopActionView(task({assignmentBlockedReason:'some_new_code'}),true);
 assert.match(group(unknown,'開始').reason,/伺服器回報原因代碼「some_new_code」，尚無對應說明/,'an unknown code is quoted, not turned into a rule');
 assert.equal(group(stage,'完成').hint,undefined,'a stated reason needs no refresh hint');
 const stale=m.sopActionView(task({allowedActions:['edit','start']}),false);
 assert.deepEqual([...new Set(stale.unavailable.map(g=>g.kind))],['stale']);assert.match(stale.unavailable[0].hint,/重新整理/);
});
test('P4b reason absent: says the system gave no reason, never an unmet condition or a permission claim',()=>{
 const v=m.sopActionView(task(),true);
 const g=group(v,'開始');assert.equal(g.kind,'no_reason');assert.match(g.reason,/系統未提供原因/);
 assert.doesNotMatch(v.unavailable.map(x=>x.reason).join('|'),/條件尚未滿足|沒有.*權限|需管理權限/);
 assert.match(g.hint,/重新整理/);assert.doesNotMatch(g.hint,/聯絡節點負責人/,'no owner in the data, so no owner hint');
 const withOwner=group(m.sopActionView(task(),true,'王小明'),'開始');
 assert.match(withOwner.hint,/聯絡節點負責人 王小明/);
 assert.equal(m.sopActionView(task({participants:{}}),true).completion.kind,'no_reason','unassigned is not guessed as the reason');
});
test('P4b dedup grouping: actions sharing a reason appear once under it, distinct reasons stay separate',()=>{
 const v=m.sopActionView(task({completionBlockedReason:'applicability_unresolved'}),true);
 const none=v.unavailable.filter(g=>g.kind==='no_reason');assert.equal(none.length,1);
 assert.deepEqual(none[0].actions.map(a=>a.label).sort(),['封存','開始','編輯任務內容'].sort());
 assert.equal(v.unavailable.length,2,'the dependency reason for 完成 is its own group');
 assert.equal(new Set(v.unavailable.map(g=>g.reason)).size,v.unavailable.length,'no reason text repeats');
 assert.deepEqual(m.uniqueReasons(['A','A ',' ','B']),['A','B']);
});
test('finished tasks state the fact and point to reopen/restore only as an option',()=>{
 assert.match(m.sopActionView(task({state:'done',allowedActions:[]}),true).edit.reason,/已完成.*重新開啟/);
 assert.match(m.sopActionView(task({state:'archived',allowedActions:[]}),true).edit.reason,/已封存.*還原/);
 assert.ok(!m.sopActionView(task({state:'blocked',allowedActions:['resume']}),true).unavailable.flatMap(g=>g.actions).some(a=>a.label==='開始'||a.label==='還原'));
});
