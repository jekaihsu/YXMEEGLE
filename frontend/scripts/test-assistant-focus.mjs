import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
const directory=new URL('..',import.meta.url).pathname;
const compiled=await build({stdin:{contents:"import React from 'react';import {createRoot} from 'react-dom/client';import {AssistantChat} from './src/assistant/AssistantChat';import {ProjectChatLauncher} from './src/assistant/ProjectChatLauncher';window.mount=drawer=>createRoot(document.getElementById('root')).render(drawer?<ProjectChatLauncher projectId='p1' projectCode='P01' projectName='測試案件'/>:<AssistantChat/>);",resolveDir:directory,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'}});
const css=(await Promise.all(['design/tokens.css','design/glass.css','styles.css','design/controls.css','design/primitives.css','design/picker.css','Assistant.css','assistant/elements/elements.css','assistant/ProjectChatLauncher.css'].map(file=>readFile(new URL(`../src/${file}`,import.meta.url),'utf8')))).join('\n');
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
try{
 for(const drawer of [false,true]){
  const page=await browser.newPage({viewport:{width:1280,height:800}});
  await page.setContent(`<html lang="zh-Hant" data-theme="light"><head><style>${css}</style></head><body><div id="root"></div></body></html>`);
  await page.evaluate(()=>{window.fetch=async url=>new Response(JSON.stringify(String(url).includes('models')?{default:'claude',models:[{id:'claude',label:'Claude',available:true}]}:{history_available:true,items:[],next_cursor:null}))});
  await page.addScriptTag({content:compiled.outputFiles[0].text});
  await page.evaluate(drawer=>window.mount(drawer),drawer);
  if(drawer)await page.locator('.project-chat-launcher').click();
  const input=page.locator('.assistant-composer textarea');await input.waitFor();
  await input.evaluate(el=>el.blur());
  const styles=()=>page.locator('.assistant-composer').evaluate(el=>{const s=getComputedStyle(el);return {border:s.border,shadow:s.boxShadow,outline:s.outline,padding:s.padding}});
  const baseline=await styles();
  await input.click();assert.deepEqual(await styles(),baseline,`${drawer?'drawer':'page'} click preserves composer styles`);
  await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
  assert.equal(await input.evaluate(el=>el===document.activeElement&&el.matches(':focus-visible')),true);
  assert.deepEqual(await styles(),baseline,`${drawer?'drawer':'page'} keyboard focus preserves composer styles`);
  await page.close();
 }
}finally{await browser.close()}
console.log('Composer browser focus passed in page and drawer for click and keyboard Tab.');
