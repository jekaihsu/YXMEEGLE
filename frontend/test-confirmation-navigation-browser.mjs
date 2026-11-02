import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
const bundle=await build({stdin:{resolveDir:import.meta.dirname,loader:'tsx',contents:`
import React from 'react';import {createRoot} from 'react-dom/client';
import {CaseDetail} from './src/CaseDetail';import {buildCaseDetailView} from './src/caseDetailView';import {confirmationFixture} from './fixtures/confirmation-detail.mjs';
createRoot(document.getElementById('root')).render(<CaseDetail view={buildCaseDetailView(confirmationFixture())}/>);
`},bundle:true,write:false,platform:'browser',format:'iife',jsx:'automatic',loader:{'.css':'empty'}});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://127.0.0.1:52881/**',r=>r.fulfill({contentType:'text/html',body:`<div id="root"></div><script>${bundle.outputFiles[0].text}</script>`}));
 await page.goto('http://127.0.0.1:52881/#view=confirmation&ctx=retained');
 const original=page.url();const controls=page.getByRole('navigation',{name:'章節快速導覽'}).getByRole('button');assert.equal(await controls.count(),7);
 for(let i=0;i<7;i++){
  await controls.nth(i).focus();await page.keyboard.press('Enter');
  assert.equal(page.url(),original);
  assert.match(await page.evaluate(()=>document.activeElement.id),/^confirmation-section-/);
 }
 assert.deepEqual(errors,[]);console.log('Chrome: seven keyboard section jumps preserve route and focus target');
}finally{await browser.close()}
