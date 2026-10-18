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
const defaults={version:2,view:null,layouts:{mine:{order:['kpi','work','confirmation','deadlines','leave','trips'],hidden:[]},assign:{order:['kpi','allocation','workload','delegated','leave','trips','work'],hidden:[]},company:{order:['kpi','groups','cases','statuses','links','confirmation','leave','trips'],hidden:[]}}};
for(const raw of [null,'bad','[]','{"version":1,"order":["work"]}','{"version":3}'])assert.deepEqual(m.parseHomeLayout(raw),defaults);
assert.deepEqual(m.parseHomeLayout(JSON.stringify({version:2,view:'alien',layouts:{mine:{order:['leave','leave','groups',null],hidden:['work','work','cases']},assign:{order:null,hidden:[]}}})),{...defaults,layouts:{...defaults.layouts,mine:{order:['leave','kpi','work','confirmation','deadlines','trips'],hidden:['work']}}});
assert.equal(m.parseHomeLayout('{"version":2,"view":"assign"}').view,'assign');
assert.deepEqual(m.moveHomeCard({order:['work','confirmation'],hidden:[]},'work',1),{order:['confirmation','work'],hidden:[]});
assert.equal(m.homeLayoutKey('w','u','pm','demo'),'yx.home.v2:["w","u","pm","demo"]');
console.log('Home layout v2 persona, visibility, defensive parsing and literal defaults passed.');
