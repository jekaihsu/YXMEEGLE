import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
import {ratio} from '../test-contrast.mjs';
const compiled=await build({stdin:{contents:"import React from 'react';import {createRoot} from 'react-dom/client';import {Chart} from './src/assistant/elements/Chart';const root=createRoot(document.getElementById('root'));window.mount=props=>root.render(<Chart {...props}/>);",resolveDir:new URL('..',import.meta.url).pathname,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic'});
const css=(await Promise.all(['design/tokens.css','styles.css','assistant/elements/elements.css'].map(file=>readFile(new URL(`../src/${file}`,import.meta.url),'utf8')))).join('\n');
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const evidence=process.env.ASSISTANT_CHART_EVIDENCE;
if(evidence)await mkdir(evidence,{recursive:true});
const hex=rgb=>'#'+rgb.match(/[\d.]+/g).slice(0,3).map(n=>Math.round(Number(n)).toString(16).padStart(2,'0')).join('');
try{
 const page=await browser.newPage({viewport:{width:900,height:650}});
 await page.setContent(`<html lang="zh-Hant" data-theme="light"><head><style>${css}</style></head><body style="padding:24px;color:var(--label);background:var(--bg)"><div id="root"></div></body></html>`);
 await page.addScriptTag({content:compiled.outputFiles[0].text});
 const mount=async(kind,points)=>{
  await page.evaluate(props=>window.mount(props),{kind,title:'車輛使用統計',points,unit:' 次'});
  await page.waitForFunction(({kind,count})=>document.querySelectorAll('.assistant-chart-point').length===count&&(kind==='bar'?document.querySelector('rect'):document.querySelector('polyline')),{kind,count:points.length});
 };
 for(const theme of ['light','dark']){
  await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
  for(const kind of ['bar','line']){
   await mount(kind,[{label:'車1',value:12},{label:'車2',value:7}]);
   const colors=await page.evaluate(kind=>{
    const s=getComputedStyle(document.querySelector(kind==='bar'?'rect':'polyline'));
    const probe=document.createElement('span');probe.style.color=kind==='bar'?'var(--accent)':'var(--label)';document.body.append(probe);
    const expected=getComputedStyle(probe).color;probe.remove();
    return {actual:kind==='bar'?s.fill:s.stroke,expected,bg:getComputedStyle(document.querySelector('.assistant-chart')).backgroundColor};
   },kind);
   assert.equal(colors.actual,colors.expected,`${theme} single ${kind} uses design color`);
   assert.ok(ratio(hex(colors.actual),hex(colors.bg))>=3,`${theme} single ${kind} contrast`);
   if(evidence&&kind==='bar')await page.screenshot({path:`${evidence}/single-series-bar-${theme}.png`});
  }
  for(const kind of ['bar','line']){
   await mount(kind,Array.from({length:24},(_,i)=>({label:'一月',value:i+1,series:`車組${i+1}`})));
   const colors=await page.evaluate(kind=>({bg:getComputedStyle(document.querySelector('.assistant-chart')).backgroundColor,marks:[...document.querySelectorAll(kind==='bar'?'rect':'polyline')].map(el=>{const s=getComputedStyle(el);return {color:kind==='bar'?s.fill:s.stroke,opacity:Number(s.opacity)}})}),kind);
   for(const [i,mark] of colors.marks.entries()){
    const bg=colors.bg.match(/[\d.]+/g).slice(0,3).map(Number),fg=mark.color.match(/[\d.]+/g).slice(0,3).map(Number);
    const blended=`rgb(${fg.map((c,i)=>c*mark.opacity+bg[i]*(1-mark.opacity)).join(',')})`;
    const contrast=ratio(hex(blended),hex(colors.bg));
    assert.ok(contrast>=3,`${theme} ${kind} series ${i+1} contrast ${contrast.toFixed(2)}:1`);
   }
  }
 }
 await page.evaluate(()=>document.documentElement.dataset.theme='light');
 await mount('line',[{label:'一月',value:12,series:'甲組'},{label:'二月',value:7,series:'甲組'},{label:'一月',value:5,series:'乙組'},{label:'二月',value:10,series:'乙組'}]);
 if(evidence)await page.screenshot({path:`${evidence}/multi-series-line.png`});
 console.log('Chart browser tests passed for token colors and all 24 series in both themes.');
}finally{await browser.close()}
