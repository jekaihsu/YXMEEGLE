import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
const bundle=await build({entryPoints:['src/homeLayout.ts'],bundle:true,write:false,platform:'node',format:'esm'});
const file=new URL('./.home-layout-test.mjs',import.meta.url);
await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
for(const user of [{role:'pm'},{role:'manager'},{role:'member',department:'專案管理'},{department:'PM'},{department:'業務部'},{department:'管理部'}]){
 assert.equal(m.resolvePersona(user,false),'company');
 assert.deepEqual(m.availableViews(user,false),['company','assign','mine']);
}
assert.equal(m.resolvePersona({role:'member',department:'外業組'},true),'assign');
assert.deepEqual(m.availableViews({role:'member'},true),['assign','mine']);
for(const manager of [false,null]){
 assert.equal(m.resolvePersona({role:'member'},manager),'mine');
 assert.deepEqual(m.availableViews({role:'member'},manager),['mine']);
}
assert.equal(m.resolvePersona(null,null),'mine');
const defaults={version:2,view:null,layouts:{mine:{order:['kpi','work','confirmation','deadlines','leave','trips'],hidden:[]},assign:{order:['kpi','allocation','workload','delegated','absence','impact','work'],hidden:[]},company:{order:['kpi','attention','confirmation','cases','qualityTrend','qualityGroups','funnel','receivables','achievement','statuses','groups','instruments','vehicles','leave','trips','absence','links'],hidden:[]}}};
for(const raw of [null,'bad','[]','{"version":1,"order":["work"]}','{"version":3}'])assert.deepEqual(m.parseHomeLayout(raw),defaults);
assert.deepEqual(m.parseHomeLayout(JSON.stringify({version:2,view:'alien',layouts:{mine:{order:['leave','leave','groups',null],hidden:['work','work','cases']},assign:{order:null,hidden:[]}}})),{...defaults,layouts:{...defaults.layouts,mine:{order:['leave','kpi','work','confirmation','deadlines','trips'],hidden:['work']}}});
assert.equal(m.parseHomeLayout('{"version":2,"view":"assign"}').view,'assign');
assert.deepEqual(m.moveHomeCard({order:['work','confirmation'],hidden:[]},'work',1),{order:['confirmation','work'],hidden:[]});
assert.equal(m.homeLayoutKey('w','u','pm','demo'),'yx.home.v2:["w","u","pm","demo"]');
console.log('Home layout v2 persona, visibility, defensive parsing and literal defaults passed.');

const saved={order:['impact','work','absence','allocation','workload','delegated','kpi'],hidden:[]};
assert.deepEqual(m.homeSections('assign',saved).map(row=>[row.id,row.cards]),[['people',['impact','absence','workload']],['todo',['work','allocation','delegated']]]);
assert.deepEqual(m.homeSections('company',{order:['links','cases','confirmation','absence','groups'],hidden:[]}).map(row=>[row.id,row.cards]),[['todo',['cases','confirmation']],['progress',['groups']],['people',['absence']],['shortcuts',['links']]]);
assert.deepEqual(m.homeSections('mine',{order:['trips','work','leave','confirmation'],hidden:[]}).map(row=>[row.id,row.cards]),[['todo',['work','confirmation']],['people',['trips','leave']]]);
assert.deepEqual(m.homeSections('assign',{...saved,hidden:['impact','absence','workload','allocation']}).map(row=>[row.id,row.cards]),[['todo',['work','delegated']]]);
assert.deepEqual(m.moveHomeCard(saved,'impact',1).order,['absence','work','impact','allocation','workload','delegated','kpi']);
assert.deepEqual(m.moveHomeCard(saved,'allocation',-1).order,['impact','allocation','absence','work','workload','delegated','kpi']);
assert.deepEqual(m.moveHomeCard(saved,'impact',-1).order,['impact','work','absence','allocation','workload','delegated','kpi']);
assert.deepEqual(m.moveHomeCard(saved,'delegated',1).order,['impact','work','absence','allocation','workload','delegated','kpi']);
assert.deepEqual(m.parseHomeLayout(JSON.stringify({version:2,view:'assign',layouts:{assign:{order:['trips','delegated','leave','kpi','allocation','workload','work'],hidden:['leave','workload']}}})).layouts.assign,{order:['delegated','kpi','allocation','workload','work','absence','impact'],hidden:['workload']});
console.log('Home sections: 9 literal grouping, visibility, section-edge moves and saved v2 checks passed.');

assert.deepEqual(m.SECTION_ORDER.company,['todo','quality','business','progress','resources','people','shortcuts']);
assert.equal(m.HOME_CARDS.cases.section,'todo');
const oldOrder=['kpi','groups','cases','statuses','links','confirmation','leave','trips','absence'];
assert.deepEqual(m.parseHomeLayout(JSON.stringify({version:2,layouts:{company:{order:oldOrder,hidden:['cases']}}})).layouts.company,{order:[...oldOrder,'attention','qualityTrend','qualityGroups','funnel','receivables','achievement','instruments','vehicles'],hidden:['cases']});
const pinned={order:['confirmation','cases','attention'],hidden:[]};
assert.deepEqual(m.homeSections('company',pinned)[0].cards,['attention','confirmation','cases']);
assert.deepEqual(m.moveHomeCard(pinned,'attention',-1),pinned);
assert.deepEqual(m.moveHomeCard(pinned,'confirmation',1).order,['cases','confirmation','attention']);
console.log('Home reports layout: 6 literal section order, cases placement and old v2 migration checks passed.');
