import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const bundled=await build({stdin:{contents:"export * from './src/assignDrawerModel'; export {NodeAssignmentError} from './src/nodeAssignmentApi';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const people=[{open_id:'ou_a'},{open_id:'ou_b'}];
const base={assignee:'ou_a',due:'2026-10-20'};
test('T10 an unlisted or invalid candidate and a bad date are rejected before any request',()=>{
 assert.deepEqual(Object.keys(m.validateDraft(base,{assignee:'ou_gone',due:'2026-13-40'},people)).sort(),['assignee','due']);
 assert.deepEqual(m.validateDraft(base,{assignee:'ou_b',due:'2026-10-21'},people),{});
 assert.deepEqual(m.validateDraft({assignee:'ou_old',due:''},{assignee:'ou_old',due:''},people),{});
 assert.deepEqual(m.validateDraft(base,{assignee:'',due:''},people),{});
});
test('only changed fields are sent and clearing maps to null as the existing editor does',()=>{
 assert.deepEqual(m.patchOf(base,{assignee:'ou_b',due:base.due}),{assignee_open_id:'ou_b'});
 assert.deepEqual(m.patchOf(base,{assignee:'',due:''}),{assignee_open_id:null,deadline:null});
 assert.deepEqual(m.patchOf(base,base),{});
});
test('failures are classified: conflict, revoked, unknown outcome, field validation',()=>{
 const E=(status,code,fields)=>new m.NodeAssignmentError(status,'x',code,fields);
 assert.equal(m.classifyFailure(E(409,'revision_conflict')).kind,'conflict');
 assert.equal(m.classifyFailure(E(403,'forbidden')).kind,'revoked');
 assert.equal(m.classifyFailure(E(408,'client_timeout')).kind,'unknown');
 assert.equal(m.classifyFailure(E(502,'outcome_unknown')).kind,'unknown');
 assert.equal(m.classifyFailure(E(409,'readback_mismatch')).kind,'unknown');
 assert.equal(m.classifyFailure(new TypeError('fetch failed')).kind,'unknown');
 const v=m.classifyFailure(E(422,undefined,{deadline:'日期格式錯誤'}));assert.equal(v.kind,'validation');assert.equal(v.fields.due,'日期格式錯誤');
});
test('T23 a read-back that saved the executor but not the deadline is reported field by field',()=>{
 const draft={assignee:'ou_b',due:'2026-10-25'};
 const latest={assignee:'ou_b',due:'2026-10-20'};
 assert.deepEqual(m.fieldOutcomes(base,draft,latest),{assignee:'saved',due:'unsaved'});
 assert.equal(m.verdict(base,draft,latest,'r1','r2'),'partial');
 assert.equal(m.verdict(base,draft,draft,'r1','r2'),'applied');
 assert.equal(m.verdict(base,draft,base,'r1','r1'),'not_applied');
 assert.equal(m.verdict(base,draft,{assignee:'ou_a',due:'2026-11-01'},'r1','r2'),'moved');
});
test('T13 a single-field change that landed counts as applied so it is not sent twice',()=>{
 const draft={assignee:'ou_b',due:base.due};
 assert.equal(m.verdict(base,draft,draft,'r1','r2'),'applied');
});
