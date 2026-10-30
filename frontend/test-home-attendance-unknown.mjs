import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
const bundle=await build({stdin:{contents:"export * from './src/homePeople';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm'});
const file=new URL('./.home-unknown-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const days=['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'];
const person={id:'a',attendance:[null,'','外勤出差','上午請假','出勤'],in_service:true};
const view={days,people:[person],leaves:[],trips:[],leaves_available:false,summary:{on_trip:null}};
assert.deepEqual(m.weeklyPeople(view,[person],'2026-10-14').map(r=>({cells:r.cells,absenceDays:r.absenceDays})),[{cells:['—','—','出差','請假','在'],absenceDays:['2026-10-14','2026-10-15']}]);
assert.equal(m.absenceCell({...view,leaves_available:true},person,'2026-10-19'),'—');
assert.equal(m.absenceCell({...view,leaves_available:true},person,days[0]),'—');
assert.deepEqual(m.weeklyPeople({...view,leaves:[{person_id:'a',start:days[0],end:days[4]}]},[{...person,in_service:false}],'2026-10-14').map(r=>({cells:r.cells,absenceDays:r.absenceDays})),[{cells:['—','—','—','—','—'],absenceDays:[]}]);
const unknown={...person,attendance:[null,null,null,null,null]};
assert.deepEqual(m.absenceImpact(m.weeklyPeople(view,[unknown],'2026-10-14'),[{id:'task',status:'in_progress',assignees:[{id:'a'}]}],'2026-10-14'),[]);
console.log('PASS 5 unknown attendance behaviors');

const matrix=[
 [true,null,['—','出差','請假','在','在','—']],
 [true,0,['在','出差','請假','在','在','在']],
 [false,null,['—','出差','請假','在','在','—']],
 [false,0,['—','出差','請假','在','在','—']],
];
for(const [leaves_available,on_trip,expected] of matrix){
 const source={...view,leaves_available,summary:{on_trip}};
 assert.deepEqual([null,'外勤出差','上午請假','在','其他文字',''].map(cell=>m.absenceCell(source,{...person,attendance:[cell]},days[0])),expected);
}
assert.equal(m.absenceCell({...view,leaves:[{person_id:'a',start:days[0],end:days[4]}]},{...person,attendance:['出差']},days[0]),'出差');
assert.equal(m.absenceCell({...view,trips:[{person_id:'a',kind:'trip',start:days[0],end:days[4]}]},{...person,attendance:['請假']},days[0]),'請假');
assert.equal(m.absenceCell({...view,leaves:[{person_id:'a',start:'2026-10-19',end:'2026-10-19'}]},person,'2026-10-19'),'—');
assert.equal(m.absenceCell({...view,leaves:[{person_id:'a',start:days[0],end:days[0]}]},person,days[0]),'請假');
assert.equal(m.absenceCell({...view,trips:[{person_id:'a',kind:'trip',start:days[0],end:days[0]}]},person,days[0]),'出差');
console.log('PASS 24 attendance matrix cells and 5 precedence/day/approval assertions');
const roster=[{...person,id:'departed',group:'team',in_service:false},{...person,id:'active',group:'team'},{...person,id:'unknown',group:'team',in_service:null}];
assert.deepEqual(m.scopedAttendance({...view,people:roster},'assign','team').people.map(p=>p.id),['active','unknown']);
assert.deepEqual(m.scopedAttendance({...view,people:roster},'company',null).people.map(p=>p.id),['active','unknown']);
assert.deepEqual(m.scopedAttendance({...view,people:[roster[0]]},'assign','team'),{known:false,people:[]});
assert.equal(m.absenceCell({...view,leaves_available:true,summary:{on_trip:0}},roster[2],days[0]),'在');
assert.equal(m.absenceCell(view,roster[2],days[0]),'—');
console.log('PASS 5 active-roster and unknown-service assertions');
