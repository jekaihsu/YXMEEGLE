import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=admin&tab=settings',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
window.scrollTo=()=>{};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['./src/App.tsx'],bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.admin-summary-test.mjs',import.meta.url);await writeFile(path,bundle.outputFiles[0].text);const {default:App}=await import(path.href);await unlink(path);
const calls=[];
globalThis.fetch=async url=>{
 calls.push(url);
 const body=url==='/api/session'?{user:{id:'manager',name:'管理員',role:'manager'},users:[],mode:'lark',workspace_id:'fixture',features:{}}:
 {user:{name:'摘要已讀取',role:'manager',permissions:[]},environment:'demo',identity_mode:'unknown',features:{},sources:[],sources_access:'restricted',directory:{status:'restricted',last_success_at:null},datasets:[],node_connection:[],manager_details_available:false};
 return new Response(JSON.stringify(body),{headers:{'content-type':'application/json'}});
};
const root=createRoot(document.getElementById('root'));
try{
 await act(async()=>{root.render(React.createElement(App));await new Promise(resolve=>setTimeout(resolve,30))});
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,30))});
 assert.deepEqual(calls.filter(url=>url==='/api/session'||url==='/api/settings/overview'||url.startsWith('/api/workspace')),['/api/session','/api/settings/overview']);
 assert.match(document.body.textContent,/摘要已讀取/);
}finally{await act(async()=>root.unmount());dom.window.close()}
