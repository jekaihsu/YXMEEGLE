// AA (4.5:1) check for accent/label pairs, read from src/design/tokens.css (light = first :root, dark = [data-theme=dark]).
import assert from 'node:assert/strict';
import fs from 'node:fs';
const css=fs.readFileSync(new URL('./src/design/tokens.css',import.meta.url),'utf8');
const block=(start)=>{const i=css.indexOf(start);return css.slice(i,css.indexOf('}',i))};
const vars=(b)=>Object.fromEntries([...b.matchAll(/--([a-z0-9-]+):(#[0-9a-f]{6})\b/gi)].map(m=>[m[1],m[2]]));
const light=vars(block(':root{')),dark={...light,...vars(block(':root[data-theme=dark]{'))};
const lum=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(x=>x<=.03928?x/12.92:((x+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2]};
const ratio=(a,b)=>{const[x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return(x+.05)/(y+.05)};
for(const[name,t]of[['light',light],['dark',dark]])for(const[fg,bg]of[['on-accent','accent'],['accent','bg'],['accent','surface'],['label','bg'],['label-2','bg'],['label-2','surface']]){
 if(!t[fg]||!t[bg])continue;const r=ratio(t[fg],t[bg]);assert(r>=4.5,`${name} ${fg} on ${bg}: ${r.toFixed(2)}`)}
console.log('contrast ok');

// Exercise the real cascade, including the brand rules that previously overrode polish.
import {build} from 'esbuild';
import {createRequire} from 'node:module';
const {chromium}=createRequire(process.env.PLAYWRIGHT_MODULE||'/tmp/shots/node_modules/playwright-core/package.json')('playwright-core');
const bundle=await build({entryPoints:['src/main.tsx'],bundle:true,write:false,outdir:'/tmp/yx-contrast',loader:{'.css':'css'}});
const styles=bundle.outputFiles.filter(f=>f.path.endsWith('.css')).map(f=>f.text).join('\n');
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage();
 await page.setContent(`<style>${styles}</style><main class="workspace" style="background:var(--surface-2)"><div class="workflow"><button class="stage-button completed"><div class="stage-button-top"><strong>已完成階段</strong><svg></svg></div><div class="stage-button-bottom">負責人<small>完成日期</small></div><span class="stage-action-label">查看成果</span></button></div><div class="appearance-control"><div class="ds-segmented"><button aria-checked="true">M</button><button aria-checked="true">深色</button><button aria-checked="true">舒適</button></div></div><div class="workflow"><button class="stage-button in_progress selected"><span class="stage-action-label">待他人處理</span><span class="stage-button-bottom"><small>09/24</small></span></button></div></main>`);
 for(const theme of ['light','dark']){
  await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
  await page.waitForTimeout(350);
  const pairs=await page.evaluate(()=>['.stage-button-top strong','.stage-button-bottom','.stage-button-bottom small','.stage-action-label'].map(selector=>{
   const card=document.querySelector('.workflow .stage-button.completed');
   const rgb=value=>'#'+value.match(/\d+/g).slice(0,3).map(n=>Number(n).toString(16).padStart(2,'0')).join('');
   return {selector,fg:rgb(getComputedStyle(card.querySelector(selector)).color),bg:rgb(getComputedStyle(card).backgroundColor)};
  }));
  const selectedPairs=await page.evaluate(()=>[...document.querySelectorAll('.ds-segmented button[aria-checked=true],.stage-button.selected .stage-action-label,.stage-button.selected small')].map(el=>{
   const rgb=value=>value.match(/[\d.]+/g).map(Number);const color=rgb(getComputedStyle(el).color);let bg=[0,0,0],layers=[];
   for(let node=el;node;node=node.parentElement){const c=rgb(getComputedStyle(node).backgroundColor);layers.unshift(c)}
   for(const c of layers){const a=c.length>3?c[3]:1;bg=bg.map((v,i)=>c[i]*a+v*(1-a))}
   const hex=c=>'#'+c.slice(0,3).map(n=>Math.round(n).toString(16).padStart(2,'0')).join('');return {selector:el.textContent,fg:hex(color),bg:hex(bg)};
  }));
  pairs.push(...selectedPairs);
  for(const {selector,fg,bg} of pairs){const r=ratio(fg,bg);assert(r>=4.5,`${theme} completed ${selector}: ${r.toFixed(2)}`);console.log(`${theme} completed ${selector}: ${r.toFixed(2)}:1`)}
 }
}finally{await browser.close()}
