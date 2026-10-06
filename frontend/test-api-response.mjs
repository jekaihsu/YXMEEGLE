// Verify api() turns unusable HTTP 200 bodies into typed ApiError without leaking the body.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {transform} from 'esbuild';
const {code}=await transform(await fs.readFile('src/api.ts','utf8'),{loader:'ts',format:'esm'});
const {api,ApiError}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
globalThis.window={dispatchEvent(){}};
const respond=(body,status=200)=>{globalThis.fetch=async()=>new Response(body,{status})};
respond(JSON.stringify({ok:1}));
assert.deepEqual(await api('/x'),{ok:1});
for(const body of ['','<html>secret proxy page</html>','{"broken":']){
 respond(body);
 await assert.rejects(api('/x'),e=>{
  assert.ok(e instanceof ApiError);assert.equal(e.status,200);
  assert.ok(!e.message.includes('secret')&&!e.message.includes('broken'));return true});
}
respond('null');
await assert.rejects(api('/x'),e=>e instanceof ApiError);
respond(JSON.stringify({detail:'denied'}),403);
await assert.rejects(api('/x'),e=>e instanceof ApiError&&e.status===403&&e.message==='denied');
respond('<html>secret</html>',502);
await assert.rejects(api('/x'),e=>e instanceof ApiError&&e.status===502&&!e.message.includes('secret'));
console.log('api response tests passed');
