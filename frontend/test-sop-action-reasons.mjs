import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const b=await build({stdin:{contents:"export * from './src/sopActionReasons';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const m=await import('data:text/javascript;base64,'+Buffer.from(b.outputFiles[0].text).toString('base64'));
const task=(over={})=>({id:'t',title:'T',state:'pending',applicability:'applicable',participants:{executor:'u1'},allowedActions:['block'],completionBlockedReason:null,assignmentBlockedReason:undefined,...over});
const text=v=>v.unavailable.map(g=>g.reason).join('|');
test('P4 an editable-looking task that can only be blocked explains the other actions once, grouped',()=>{
 const v=m.sopActionView(task(),true);
 assert.deepEqual(v.available.map(a=>a.label),['標記受阻']);
 assert.equal(v.edit.allowed,false);assert.equal(v.edit.kind,'no_permission');assert.doesNotMatch(v.edit.reason,/需管理權限/);
 const noPerm=v.unavailable.filter(g=>g.kind==='no_permission');assert.equal(noPerm.length,1,'one explanation for every action lacking permission');
 assert.deepEqual(noPerm[0].actions.map(a=>a.label).sort(),['完成','封存','開始','編輯任務內容'].sort());
});
test('unassigned, dependency, stage-not-open, no-permission and stale are distinct reasons',()=>{
 assert.equal(m.sopActionView(task({participants:{}}),true).completion.kind,'unassigned');
 assert.equal(m.sopActionView(task({completionBlockedReason:'completion_evidence_missing'}),true).completion.kind,'dependency');
 assert.equal(m.sopActionView(task({completionBlockedReason:'node_not_enrolled'}),true).completion.kind,'stage_closed');
 assert.equal(m.sopActionView(task({allowedActions:['complete','edit']}),true).completion.allowed,true);
 assert.equal(m.sopActionView(task({allowedActions:['complete']}),true).completion.kind,undefined);
 const stale=m.sopActionView(task({allowedActions:['edit','start','complete']}),false);
 assert.equal(stale.edit.kind,'stale');assert.equal(stale.available.length,0);assert.deepEqual([...new Set(stale.unavailable.map(g=>g.kind))],['stale']);assert.equal(stale.unavailable.length,1,'stale is explained once');
});
test('finished tasks say how to reopen instead of citing permissions',()=>{
 assert.match(m.sopActionView(task({state:'done',allowedActions:[]}),true).edit.reason,/重新開啟/);
 assert.match(m.sopActionView(task({state:'archived',allowedActions:[]}),true).edit.reason,/還原/);
});
test('only actions that make sense for the state are listed and reasons are deduplicated',()=>{
 const v=m.sopActionView(task({state:'blocked',allowedActions:['resume']}),true);
 assert.ok(!v.unavailable.flatMap(g=>g.actions).some(a=>a.label==='開始'||a.label==='還原'));
 assert.deepEqual(m.uniqueReasons(['A','A ',' ','B']),['A','B']);
});
