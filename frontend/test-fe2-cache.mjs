import assert from 'node:assert/strict';import {readFile,writeFile,unlink} from 'node:fs/promises';import {build} from 'esbuild';
for(const file of ['useProjectProgress.ts','useSopTasks.ts','useStartSop.ts'])assert.match(await readFile('src/'+file,'utf8'),/new SessionCache</,file+' must use bounded session cache');
const b=await build({stdin:{contents:"export {createPageData} from './src/pageData';export {seedProjectProgress,peekProjectProgress} from './src/useProjectProgress';export {SessionCache} from './src/sessionCache';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});const p=new URL('./.cache-test.mjs',import.meta.url);await writeFile(p,b.outputFiles[0].text);let m;try{m=await import(p.href)}finally{await unlink(p)}
const cache=new m.SessionCache(2);cache.set('a',1);cache.set('b',2);assert.equal(cache.get('a'),1);cache.set('c',3);assert.equal(cache.size,2);assert.equal(cache.has('b'),false);m.invalidateSessionEpoch();assert.equal(cache.size,0);console.log('Cache: cap=2, least-recently-used eviction, epoch size=0');

const owner=m.createPageData({workspace:'cache-test',identityFingerprint:'fixture',openId:'one'});
for(let i=0;i<65;i++)m.seedProjectProgress(String(i),{fixture:i},owner);
assert.equal(m.peekProjectProgress('0',owner),undefined,'oldest real progress snapshot is evicted at 64');
assert.equal(m.peekProjectProgress('64',owner).fixture,64);m.invalidateSessionEpoch();assert.equal(m.peekProjectProgress('64',owner),undefined,'epoch clears the real progress module cache');owner.close();
