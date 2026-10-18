import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
const bundle=await build({stdin:{contents:"export * from './src/homePeople';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm'});
const file=new URL('./.home-unknown-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const days=['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'];
const person={id:'a',attendance:[null,'','外勤出差','上午請假','出勤'],in_service:true};
const view={days,people:[person],leaves:[],trips:[],leaves_available:false};
assert.deepEqual(m.weeklyPeople(view,[person],'2026-10-14').map(r=>({cells:r.cells,absenceDays:r.absenceDays})),[{cells:['—','—','出差','請假','在'],absenceDays:['2026-10-14','2026-10-15']}]);
assert.equal(m.absenceCell({...view,leaves_available:true},person,'2026-10-19'),'—');
assert.equal(m.absenceCell({...view,leaves_available:true},person,days[0]),'在');
assert.deepEqual(m.weeklyPeople({...view,leaves:[{person_id:'a',start:days[0],end:days[4]}]},[{...person,in_service:false}],'2026-10-14').map(r=>({cells:r.cells,absenceDays:r.absenceDays})),[{cells:['—','—','—','—','—'],absenceDays:[]}]);
const unknown={...person,attendance:[null,null,null,null,null]};
assert.deepEqual(m.absenceImpact(m.weeklyPeople(view,[unknown],'2026-10-14'),[{id:'task',status:'in_progress',assignees:[{id:'a'}]}],'2026-10-14'),[]);
console.log('PASS 5 unknown attendance behaviors');
