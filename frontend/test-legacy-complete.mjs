import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import {writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','Event','HTMLElement','HTMLTextAreaElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {FlowNodeActions} from './src/FlowActions'; export * from './src/nodeAssignmentApi'; export {buildFlowModel} from './src/flowModel'; export {needsAttention,fieldworkSnapshot} from './src/projectOverviewModel';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.legacy-complete-test.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
let root,mutations=[];
afterEach(async()=>{if(root){await act(async()=>root.unmount());root=null}});
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
async function mount({allowed=true,status='未開始',error=null,busy=false}={}){
 const detail=assignmentFixture().detail;detail.node.derived_status=status;detail.can={legacy_complete:allowed};mutations=[];
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.FlowNodeActions,{detail,busy,error,reason:busy?'儲存中':'',mutate:async m=>{mutations.push(m);return false}})));
 return detail;
}
const click=async element=>act(async()=>element.click());
async function value(text){await act(async()=>{const el=document.querySelector('textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(el,text);el.dispatchEvent(new Event('input',{bubbles:true}))})}
async function submit(){await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))}

for(const status of ['未開始','待處理','進行中','待審核'])test(`permitted legacy ${status} shows secondary direct completion`,async()=>{
 await mount({status});assert.ok(button('直接標記完成'));assert.equal(button('直接標記完成').classList.contains('primary'),false);
});
for(const [name,options] of [['managed',{allowed:false}],['denied employee',{allowed:false}],['done',{status:'已完成'}],['skipped',{status:'略過'}]])test(`${name} has no direct completion control`,async()=>{
 await mount(options);assert.equal(button('直接標記完成'),undefined);
});
test('form validates whitespace and length then submits the reason and revision',async()=>{
 const detail=await mount();await click(button('直接標記完成'));assert.equal(document.querySelector('textarea').required,true);assert.equal(document.querySelector('textarea').maxLength,500);
 await value('   ');await submit();assert.equal(mutations.length,0);assert.match(document.querySelector('[role=alert]').textContent,/請填寫原因/);
 await value('x'.repeat(501));await submit();assert.equal(mutations.length,0);assert.match(document.querySelector('[role=alert]').textContent,/500/);
 await value('  舊案成果已核對  ');await submit();assert.deepEqual(mutations,[{action:'legacy_complete',nodeKey:detail.node.key,reason:'舊案成果已核對',expected_revision:detail.node.revision}]);
});
test('server reason is retained in the form',async()=>{
 await mount({error:new ui.NodeAssignmentError(403,'此案件的舊案分類尚未確認','forbidden')});await click(button('直接標記完成'));assert.equal(document.querySelector('[role=alert]').textContent,'此案件的舊案分類尚未確認');
});
test('busy direct completion cannot be submitted',async()=>{
 await mount({busy:true});assert.equal(button('直接標記完成').disabled,true);
});
test('API sends the reason through the dedicated revision checked operation and parses the audit marker',async()=>{
 const fixture=assignmentFixture();fixture.detail.can.legacy_complete=false;fixture.detail.node.legacy_completion={actor:{open_id:'ou_pm',name:'案件 PM'},at:'2026-10-23T10:00:00+08:00',reason:'舊案核對'};
 let call;globalThis.fetch=async(url,init)=>{call={url,body:JSON.parse(init.body)};return new Response(JSON.stringify(fixture.detail),{status:200,headers:{'Content-Type':'application/json'}})};
 const d=fixture.detail,result=await ui.mutateNodeAssignment('p1',{action:'legacy_complete',nodeKey:d.node.key,reason:'舊案核對',expected_revision:d.node.revision},new AbortController().signal,()=>true,'legacy-request');
 assert.equal(call.url,`/api/projects/p1/node-assignments/nodes/${d.node.key}/legacy_complete`);
 assert.deepEqual(call.body,{reason:'舊案核對',expected_revision:d.node.revision,request_id:'legacy-request'});
 assert.deepEqual(result.node.legacy_completion,d.node.legacy_completion);
});
test('completed node with zero tasks asks for reconciliation and leaves engineering quantity unknown',()=>{
 const {list}=assignmentFixture(),{project}=projectFixture();const field=list.nodes.find(n=>n.key==='field');Object.assign(field,{derived_status:'已完成',tasks:{done:0,total:0},legacy_completion:{actor:{open_id:'ou_pm',name:'PM'},at:'2026-10-23T10:00:00+08:00',reason:'舊案'}});
 const model=ui.buildFlowModel({project,assignments:list,today:'2026-10-23'}),row=model.nodes.find(n=>n.key==='field');
 assert.equal(row.state,'已完成');assert.equal(row.progress.label,'節點已完成');assert.ok(ui.needsAttention(model.nodes).some(i=>i.title==='外業狀態待核對'));
 assert.equal(ui.fieldworkSnapshot(undefined).percent,null);
});
