import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const bundle=await build({stdin:{contents:"export {AppShell} from './src/AppShell';export {parseRoute} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.route-labels.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const expected={dashboard:'今日工作台',reports:'PM 週報',projects:'案件總覽',quotes:'報價總表',overview:'管理總覽',people:'人員與資源出勤',approvals:'變更與展延',routines:'追蹤與檢討',admin:'管理設定',work:'我的工作',sources:'資料來源',dispatch:'派工調度',project:'案件詳情',confirmations:'案件與確認單',confirmation:'案件與確認單詳情',contract:'合約明細詳情',workitem:'工作項詳情'};
for(const [view,label] of Object.entries(expected)){
 const html=renderToStaticMarkup(React.createElement(ui.AppShell,{s:{user:null},route:{view},error:'',ready:true}));
 assert.match(html,new RegExp(`<strong>${label}</strong></div>`),view);
}
for(const tab of ['assigned','delegated','local']){
 const route=ui.parseRoute(`#view=work&tab=${tab}`);
 for(let reload=0;reload<2;reload++){
  const html=renderToStaticMarkup(React.createElement(ui.AppShell,{s:{user:null},route,error:'',ready:true}));
  assert.match(html,/<strong>我的工作<\/strong><\/div>/,tab);
 }
}
console.log('Every view and all three work tabs have their own breadcrumb label.');
