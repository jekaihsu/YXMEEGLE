import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const bundle=await build({stdin:{contents:"export * from './src/peopleAttendance'; export {WeeklyAttendanceTable} from './src/AttendanceWorkSchedules';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.people-attendance-test.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let model;
try{model=await import(path.href)}finally{await fs.unlink(path)}
assert.equal(model.taipeiWeek('2026-10-11'),'2026-10-05');
assert.equal(model.taipeiWeek('2026-10-12'),'2026-10-12');
assert.equal(model.taipeiWeek('2026-10-18'),'2026-10-12');
assert.equal(model.attendanceValue(null),'—');
assert.equal(model.attendanceValue(undefined),'—');
assert.equal(model.attendanceValue(0),'0');
const raw={status:'incomplete',days:['2026-10-12'],people:[{id:'ou_fake',name:'Synthetic',group:null,in_service:null,attendance:[null],phone:'PRIVATE'}],trips:[],summary:{people:null,in_service:null,on_leave:null,on_trip:null,trips:null}};
const view=model.parsePeopleAttendance(raw);
assert.equal(view.summary.on_leave,null);
assert.equal(JSON.stringify(view).includes('PRIVATE'),false);
const html=renderToStaticMarkup(React.createElement(model.WeeklyAttendanceTable,{days:view.days,people:view.people}));
assert.equal((html.match(/—/g)??[]).length,2);
for(const status of ['needs-permission','not-connected','read-failed','garbage']){
 const parsed=model.parsePeopleAttendance({...raw,status,summary:{people:0,on_leave:0,on_trip:0,trips:0}});
 assert.equal(parsed.summary.on_trip,null);
}
assert.equal(model.parsePeopleAttendance({...raw,status:'ok',summary:{trips:0}}).summary.trips,0);
assert.equal(model.parsePeopleAttendance({...raw,summary:{trips:-1}}).summary.trips,null);
console.log('people attendance view contracts passed');
