import assert from 'node:assert/strict';import {build} from 'esbuild';import {readFile,writeFile,unlink} from 'node:fs/promises';
const b=await build({stdin:{contents:"export {attendanceReadPresentation} from './src/peopleAttendance';export {ApiError} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});const p=new URL('./.attendance-denied.mjs',import.meta.url);await writeFile(p,b.outputFiles[0].text);let m;try{m=await import(p.href)}finally{await unlink(p)}
const denied=m.attendanceReadPresentation(new m.ApiError(403,'PRIVATE_ERROR'));
assert.equal(denied.view.status,'needs-permission');assert.equal(denied.error,'');assert.equal(denied.canRetry,false);
assert.equal(m.attendanceReadPresentation(new m.ApiError(500,'PRIVATE_ERROR')).error,'出勤資料暫時無法更新。');
assert.equal(m.attendanceReadPresentation(new m.ApiError(500,'PRIVATE_ERROR'),{as_of:'2026-11-03'}).error,'出勤資料暫時無法更新。已保留上次資料。資料時間：2026-11-03');
assert.match(await readFile('src/UnifiedHome.tsx','utf8'),/attendancePresentation.canRetry/);console.log('attendance 403: needs-permission, no raw error, no retry; retained errors include data time');
