// C-STATE: read states stay separate and never collapse into a zero count.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {existsSync,mkdtempSync,rmSync,writeFileSync,readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
// Dependency-free: Node 24 strips the module's erasable TypeScript syntax.
const module=await import('./src/dataState.ts');
const {DATA_STATES,DATA_STATE_LABELS,parseDataState,dataStateCount,describeDataState,hasDataState}=module;

let checks=0;const eq=(actual,expected,message)=>{assert.deepEqual(actual,expected,message);checks++};
const unknown={states:['unknown'],count:null};

eq([...DATA_STATES],['loading','complete_empty','filtered_empty','unlocated','forbidden','read_failed','partial','stale','unknown'],'all nine states exist');
eq(new Set(Object.values(DATA_STATE_LABELS)).size,DATA_STATES.length,'every state has its own label');
for(const state of DATA_STATES){
 const parsed=parseDataState({states:[state],count:null});
 eq(parsed.states,[state],`${state} is preserved`);
 eq(describeDataState(parsed),DATA_STATE_LABELS[state],`${state} renders its own label`);
}

eq(parseDataState({states:['stale','partial'],count:12}),{states:['partial','stale'],count:12},'partial and stale coexist');
const both=parseDataState({states:['partial','stale'],count:12});
eq([hasDataState(both,'partial'),hasDataState(both,'stale')],[true,true],'both flags are readable');
eq(describeDataState(both),'部分資料・資料待更新（12 筆）','both labels and the count render');
for(let i=0;i<DATA_STATES.length;i++)for(let j=i+1;j<DATA_STATES.length;j++){
 const pair=[DATA_STATES[i],DATA_STATES[j]];
 if(pair.join()==='partial,stale')continue;
 eq(parseDataState({states:pair,count:null}),pair.includes('forbidden')?{states:['forbidden']}:unknown,`${pair} cannot coexist`);
}

for(const payload of [{states:['unknown']},{states:['unknown'],count:0},{states:['unknown'],count:4},null,undefined,'0',0,{},{states:[]},{states:['ready'],count:0},{states:['partial','partial'],count:1},{states:['partial'],count:-1},{states:['partial'],count:1.5},{states:['partial'],count:'3'}]){
 const parsed=parseDataState(payload);
 eq(parsed,unknown,`${JSON.stringify(payload)} reads as unknown`);
 eq(dataStateCount(parsed),null,'unknown has no count');
 assert.ok(!/\d/.test(describeDataState(parsed)),'unknown never renders a number');checks++;
}

for(const payload of [{states:['forbidden'],count:3,name:'機密案件'},{states:['forbidden'],count:0},{states:['forbidden','partial'],name:'機密案件'}]){
 const parsed=parseDataState(payload);
 eq(parsed,{states:['forbidden']},'forbidden drops name and count');
 eq(dataStateCount(parsed),null,'forbidden has no count');
 eq(describeDataState(parsed),'沒有權限','forbidden renders no name or number');
}

eq(parseDataState({states:['complete_empty']}),{states:['complete_empty'],count:0},'complete empty is zero');
eq(parseDataState({states:['filtered_empty'],count:0}),{states:['filtered_empty'],count:0},'filtered empty is zero');
eq(parseDataState({states:['filtered_empty'],count:2}),unknown,'a non-zero empty state is contradictory');
eq(describeDataState(parseDataState({states:['complete_empty']}))===describeDataState(parseDataState({states:['filtered_empty']})),false,'empty states render differently');
for(const state of ['loading','unlocated','read_failed'])eq(parseDataState({states:[state],count:0}),unknown,`${state} with a count is contradictory`);
eq(parseDataState({states:['unlocated'],count:null,name:'案件 A'}),{states:['unlocated'],count:null,name:'案件 A'},'name is kept outside forbidden');
eq(describeDataState(parseDataState({states:['stale'],count:0})),'資料待更新（0 筆）','a known stale zero renders as zero');

// Direct values that skipped the parser must still never leak count or name.
for(const direct of [{states:['forbidden'],count:3,name:'機密案件'},{states:['partial','forbidden'],count:2,name:'機密案件'}]){
 eq(dataStateCount(direct),null,'unsafe forbidden cast has no count');
 eq(describeDataState(direct),'沒有權限','unsafe forbidden cast renders no name or number');
 eq(hasDataState(direct,'partial'),false,'unsafe forbidden cast hides other states');
}
for(const direct of [null,undefined,{},{states:'partial',count:3},{states:['ready'],count:3},{states:[],count:3},{states:['unknown'],count:0},{states:['loading'],count:5},{states:['partial'],count:-1},{states:['partial'],count:'3'},{states:['partial'],count:NaN}]){
 const label=describeDataState(direct);
 eq(dataStateCount(direct),null,`${JSON.stringify(direct)} direct value has no count`);
 assert.ok(!/\d/.test(label),`${JSON.stringify(direct)} direct value renders no number`);checks++;
}
eq(describeDataState({states:['partial','stale'],count:0}),'部分資料・資料待更新（0 筆）','a direct known zero still renders');

// Direct values get the parser's validation: duplicates, incompatible pairs,
// non-zero empties and sparse holes all read as unknown with no count.
const sparse=Array(1);
for(const direct of [{states:['partial','partial'],count:7},{states:['partial','complete_empty'],count:7},{states:['complete_empty'],count:7},{states:['filtered_empty'],count:7},{states:['stale','loading'],count:7},{states:sparse,count:7},{states:[,'partial'],count:7},{states:['partial',,'stale'],count:7}]){
 eq(dataStateCount(direct),null,`${JSON.stringify(direct)} direct value exposes no count`);
 eq(describeDataState(direct),DATA_STATE_LABELS.unknown,`${JSON.stringify(direct)} direct value reads as unknown`);
 eq(hasDataState(direct,'unknown'),true,`${JSON.stringify(direct)} direct value has unknown state`);
}
eq(parseDataState({states:sparse,count:7}),unknown,'a sparse states array parses as unknown');
eq(parseDataState({states:['partial',,'stale'],count:7}),unknown,'a sparse array with holes parses as unknown');
eq(dataStateCount({states:['stale','partial'],count:7}),7,'a valid direct partial+stale keeps its count');
eq(describeDataState({states:['stale','partial'],count:7}),'部分資料・資料待更新（7 筆）','a valid direct partial+stale renders ordered with count');

// Compile-time contract: forbidden values with count/name must not type-check.
// Uses a sibling TypeScript binary when present; never installs anything.
const here=dirname(fileURLToPath(import.meta.url));
const tscCandidates=[join(here,'node_modules/.bin/tsc'),...(()=>{try{const root=resolve(here,'../..');return readdirSync(root).map(dir=>join(root,dir,'frontend/node_modules/.bin/tsc'))}catch{return []}})()];
const tsc=tscCandidates.find(existsSync);
if(!tsc)console.log('data state: tsc not found, type-level checks skipped');
else{
 const dir=mkdtempSync(join(tmpdir(),'data-state-types-'));
 try{
  const source=join(here,'src/dataState.ts');
  const run=(name,body)=>{
   const file=join(dir,name);
   writeFileSync(file,`import type {DataState} from ${JSON.stringify(source)};\n${body}\n`);
   try{execFileSync(tsc,['--noEmit','--strict','--target','ES2022','--module','ESNext','--moduleResolution','Bundler','--allowImportingTsExtensions','--skipLibCheck',file],{stdio:'pipe'});return true}catch(error){return String(error.stdout)}
  };
  eq(run('valid.ts',`export const ok:DataState[]=[{states:['forbidden']},{states:['partial','stale'],count:1,name:'a'},{states:['unknown'],count:null}];`),true,'valid states type-check');
  for(const [label,body] of [['count','export const bad:DataState={states:["forbidden"],count:3};'],['name','export const bad:DataState={states:["forbidden"],name:"機密案件"};'],['null count','export const bad:DataState={states:["forbidden"],count:null};'],['mixed','export const bad:DataState={states:["forbidden","partial"],count:1};']])
   assert.notEqual(run(`bad-${label.replace(' ','-')}.ts`,body),true,`forbidden with ${label} must not type-check`),checks++;
 }finally{rmSync(dir,{recursive:true,force:true})}
}

console.log(`data state: ${checks} checks passed`);
