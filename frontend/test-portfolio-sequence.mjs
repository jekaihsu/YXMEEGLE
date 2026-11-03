import assert from 'node:assert/strict';
import {build} from 'esbuild';
const bundle=await build({stdin:{contents:`export {readPortfolioSequence} from './src/portfolioSequence';export {ApiError} from './src/api';`,resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
const m=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const page=(snapshot,ids,next_page=2)=>({snapshot,items:ids.map(id=>({id})),total:3,next_page});
for(const conflicts of [1,2,3]){
 let count=0,calls=[],out=[];
 await m.readPortfolioSequence(page('old',['old']),async(n,token)=>{
  calls.push([n,token]);
  if(n===1)return page(`new${++count}`,['a']);
  if(count<conflicts)throw new m.ApiError(409,'持續更新');
  return page(`new${count}`,['b','c'],null);
 },new AbortController().signal,v=>out.push(v));
 assert.equal(calls.filter(c=>c[0]===1).length,Math.min(conflicts,2));
 const final=out.at(-1);assert.equal(final.complete,conflicts<3);
 assert.deepEqual([...final.first.items,...final.items].map(i=>i.id),conflicts<3?['a','b','c']:['a']);
 assert.equal(!!final.error,conflicts===3);
}
let output;
await m.readPortfolioSequence(page('old',['old']),async()=>({...page('replacement',['a','b','c'],null),page:1,snapshot_replaced:true,stale:true}),new AbortController().signal,v=>output=v);
assert.equal(output.complete,true);assert.equal(output.first.snapshot,'replacement');assert.deepEqual(output.items,[]);
let reads=0;
await m.readPortfolioSequence(page('old',['old']),async(n)=>{reads++;return page(`changed${reads}`,['b'],n===1?2:null)},new AbortController().signal,v=>output=v);
assert.ok(reads<=5);assert.equal(output.complete,false);
const controller=new AbortController();let published=0;
await m.readPortfolioSequence(page('old',['old']),async()=>{controller.abort();return page('old',['b'],null)},controller.signal,()=>published++);
assert.equal(published,0);
for(const status of [401,403,500]){
 let count=0;
 await m.readPortfolioSequence(page('old',['old']),async()=>{count++;throw new m.ApiError(status,'failed')},new AbortController().signal,v=>output=v);
 assert.equal(count,1);assert.equal(output.denied,status!==500);
}
console.log('portfolio sequence passed: two bounded restarts, no mixed rows, atomic replacement, abort and denied');
