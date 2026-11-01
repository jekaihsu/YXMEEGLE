import assert from 'node:assert/strict';
import {mkdir,readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
const directory=new URL('..',import.meta.url).pathname;
const compiled=await build({stdin:{contents:"import React from 'react';import {createRoot} from 'react-dom/client';import {AssistantChat} from './src/assistant/AssistantChat';import {ProjectChatLauncher} from './src/assistant/ProjectChatLauncher';window.mount=drawer=>createRoot(document.getElementById('root')).render(drawer?<ProjectChatLauncher projectId='p1' projectCode='P01' projectName='測試案件'/>:<AssistantChat/>);",resolveDir:directory,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'}});
const css=(await Promise.all(['design/tokens.css','design/glass.css','styles.css','design/controls.css','design/primitives.css','design/picker.css','Assistant.css','assistant/elements/elements.css','assistant/ProjectChatLauncher.css'].map(file=>readFile(new URL(`../src/${file}`,import.meta.url),'utf8')))).join('\n');
const evidence=process.env.ASSISTANT_FOCUS_EVIDENCE;
if(evidence)await mkdir(evidence,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
try{
 for(const drawer of [false,true]){
  const page=await browser.newPage({viewport:{width:1280,height:800}});
  await page.route('http://localhost/focus',route=>route.fulfill({contentType:'text/html',body:`<html lang="zh-Hant" data-theme="light"><head><style>${css}</style></head><body><div id="root"></div></body></html>`}));
  await page.goto('http://localhost/focus');
  await page.evaluate(()=>{window.fetch=async url=>new Response(JSON.stringify(String(url).includes('models')?{default:'claude',models:[{id:'claude',label:'Claude',available:true}]}:{history_available:true,items:[],next_cursor:null}))});
  await page.addScriptTag({content:compiled.outputFiles[0].text});
  await page.evaluate(drawer=>window.mount(drawer),drawer);
  if(drawer)await page.locator('.project-chat-launcher').click();
  const input=page.locator('.assistant-composer textarea');await input.waitFor();
  await input.evaluate(el=>el.blur());
  const styles=()=>page.locator('.assistant-composer').evaluate(el=>{const s=getComputedStyle(el);return {border:s.border,shadow:s.boxShadow,outline:s.outline,padding:s.padding}});
  const baseline=await styles();
  const inputStyles=()=>input.evaluate(el=>{const s=getComputedStyle(el);return {border:s.border,shadow:s.boxShadow,outline:s.outline}});
  const inputBaseline=await inputStyles();
  await input.click();assert.deepEqual(await styles(),baseline,`${drawer?'drawer':'page'} click preserves composer styles`);
  assert.deepEqual(await inputStyles(),inputBaseline,'click preserves textarea styles');
  if(evidence)await page.screenshot({path:`${evidence}/${drawer?'drawer':'page'}-click.png`});
  await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
  assert.equal(await input.evaluate(el=>el===document.activeElement&&el.matches(':focus-visible')),true);
  assert.notEqual((await styles()).shadow,baseline.shadow,`${drawer?'drawer':'page'} keyboard focus shows composer ring`);
  assert.equal((await styles()).border,baseline.border,'keyboard ring does not change the border');
  assert.equal(await page.locator('.assistant-chat').getAttribute('data-input'),'keyboard');
  if(evidence)await page.screenshot({path:`${evidence}/${drawer?'drawer':'page'}-tab.png`});
  await input.click();assert.deepEqual(await styles(),baseline,'pointer clears keyboard ring');
  await page.keyboard.press('ArrowLeft');assert.notEqual((await styles()).shadow,baseline.shadow,'arrow keys enable keyboard ring');
  await page.mouse.move(1,1);assert.deepEqual(await styles(),baseline,'mouse movement clears keyboard ring');
  await page.close();
 }
}finally{await browser.close()}
console.log('Composer browser focus passed in page and drawer for click and keyboard Tab.');
