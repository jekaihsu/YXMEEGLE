// Verify api() turns unusable HTTP 200 bodies into typed ApiError without leaking the body.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {transform} from 'esbuild';
const {code}=await transform(await fs.readFile('src/api.ts','utf8'),{loader:'ts',format:'esm'});
const {api,ApiError}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
let expired=0;
globalThis.window={dispatchEvent(event){assert.equal(event.type,'yx:session-expired');expired++}};
const malformed='服務回應格式不正確，請稍後再試。';
const respond=(body,status=200)=>{globalThis.fetch=async()=>new Response(body,{status})};
respond(JSON.stringify({ok:1}));
assert.deepEqual(await api('/x'),{ok:1});
for(const body of ['','   \n\t','<html>secret proxy page</html>','{"broken":','null','true','42','"text"']){
 respond(body);
 await assert.rejects(api('/x'),e=>{
  assert.ok(e instanceof ApiError);assert.equal(e.status,200);assert.equal(e.message,malformed);
  assert.ok(!e.message.includes('secret')&&!e.message.includes('broken'));return true});
}
respond(JSON.stringify([{id:'valid'}]));
assert.deepEqual(await api('/x'),[{id:'valid'}]);
for(const body of [JSON.stringify({detail:'expired'}),'<html>secret</html>','']){
 respond(body,401);
 await assert.rejects(api('/x'),e=>e instanceof ApiError&&e.status===401);
}
assert.equal(expired,3);
respond('',401);
await assert.rejects(api('/x',undefined,()=>false),e=>e instanceof ApiError&&e.status===401);
assert.equal(expired,3,'stale 401 does not expire the current session');
respond(JSON.stringify({detail:'denied'}),403);
await assert.rejects(api('/x'),e=>e instanceof ApiError&&e.status===403&&e.message==='denied');
respond('<html>secret</html>',502);
await assert.rejects(api('/x'),e=>e instanceof ApiError&&e.status===502&&!e.message.includes('secret'));
console.log('api response tests passed');
