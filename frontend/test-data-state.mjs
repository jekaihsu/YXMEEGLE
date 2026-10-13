// C-STATE: read states stay separate and never collapse into a zero count.
import assert from 'node:assert/strict';
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

console.log(`data state: ${checks} checks passed`);
