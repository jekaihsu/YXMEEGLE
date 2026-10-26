import assert from 'node:assert/strict';
import {build} from 'esbuild';
const b=await build({stdin:{contents:"export {buildLabel} from './src/buildIdentity';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node'});
const {buildLabel}=await import('data:text/javascript;base64,'+Buffer.from(b.outputFiles[0].text).toString('base64'));
assert.equal(buildLabel({build:null}),'版本未知');
assert.equal(buildLabel({build:{git_sha:'a'.repeat(40),dirty:false,built_at:'2026-10-26T00:00:00Z',branch:'qa'}}),'版本 aaaaaaa');
assert.equal(buildLabel({build:{git_sha:'a'.repeat(40),dirty:true,built_at:'2026-10-26T00:00:00Z',branch:'qa'}}),'版本 aaaaaaa · 含未提交變更');
assert.equal(buildLabel({build:{git_sha:'NOT_A_SHA',dirty:false}}),'版本未知');
console.log('Build labels handle clean, dirty, absent and malformed identities.');
