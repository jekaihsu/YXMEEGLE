// Frontend lifecycle gate: only verified canonical lifecycle may allow work.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
const out=await build({entryPoints:['src/sourceLifecycle.ts'],bundle:true,write:false,platform:'node',format:'esm'});
const path=new URL('./.lifecycle-test-bundle.mjs',import.meta.url);
await fs.writeFile(path,out.outputFiles[0].text);
let m;try{m=await import(path.href)}finally{await fs.unlink(path)}
const l=(o)=>({relationship:'已關聯確認單',state:'mapped',canonical:'執行中',reasons:[],...o});
const bad={blank:l({state:'needs_verification',canonical:null,reasons:['blank']}),
 unknown:l({state:'needs_verification',canonical:null,reasons:['unknown_option']}),
 conflict:l({state:'needs_verification',canonical:null,reasons:['conflict']}),
 forged:l({reasons:['conflict']}),noCanonical:l({canonical:null})};
for(const [k,v] of Object.entries(bad)){
 assert.equal(m.declaredLifecycle({source_lifecycle:v}),null,k);
 assert.equal(m.lifecycleLabel(v),'待核對',k);
 assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:v}),'來源案件狀態待核對',k);
}
assert.equal(m.lifecycleGate({source_kind:'lark'}),'來源案件狀態待核對','missing summary fails closed');
assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:null}),'來源案件狀態待核對');
assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:l()}),'');
assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:l({canonical:'中止'})}),'來源案件已中止');
assert.equal(m.lifecycleGate({source_kind:'demo'}),'','demo cases have no source lifecycle');
console.log('Source lifecycle gate: all checks passed');
