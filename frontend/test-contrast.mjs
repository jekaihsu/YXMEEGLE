// AA (4.5:1) check for accent/label pairs, read from src/design/tokens.css (light = first :root, dark = [data-theme=dark]).
import assert from 'node:assert/strict';
import fs from 'node:fs';
const css=fs.readFileSync(new URL('./src/design/tokens.css',import.meta.url),'utf8');
const block=(start)=>{const i=css.indexOf(start);return css.slice(i,css.indexOf('}',i))};
const vars=(b)=>Object.fromEntries([...b.matchAll(/--([a-z0-9-]+):(#[0-9a-f]{6}|#[0-9a-f]{3})\b/gi)].map(m=>[m[1],m[2].length===4?'#'+[...m[2].slice(1)].map(c=>c+c).join(''):m[2]]));
const light=vars(block(':root{')),dark={...light,...vars(block(':root[data-theme=dark]{'))};
const lum=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(x=>x<=.03928?x/12.92:((x+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2]};
const ratio=(a,b)=>{const[x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return(x+.05)/(y+.05)};
for(const[name,t]of[['light',light],['dark',dark]])for(const[fg,bg]of[['on-accent','accent'],['accent','bg'],['accent','surface'],['label','bg'],['label-2','bg'],['label-2','surface']]){
 if(!t[fg]||!t[bg])continue;const r=ratio(t[fg],t[bg]);assert(r>=4.5,`${name} ${fg} on ${bg}: ${r.toFixed(2)}`)}
console.log('contrast ok');

// Resolve the actual primitive declarations, including token-derived sRGB mixes.
const primitives=fs.readFileSync(new URL('./src/design/primitives.css',import.meta.url),'utf8');
const channels=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
const hex=c=>'#'+c.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');
const resolve=(value,t)=>{
 const variable=value.match(/^var\(--([a-z0-9-]+)\)$/);if(variable)return t[variable[1]];
 const mix=value.match(/^color-mix\(in srgb,var\(--([a-z0-9-]+)\) (\d+)%[,]var\(--([a-z0-9-]+)\)\)$/);
 assert.ok(mix,`unsupported color: ${value}`);const [,a,p,b]=mix,f=Number(p)/100;
 return hex(channels(t[a]).map((v,i)=>v*f+channels(t[b])[i]*(1-f)));
};
const declaration=(selector,property)=>{
 const start=primitives.lastIndexOf(selector+'{');assert.ok(start>=0,selector);
 const body=primitives.slice(start,primitives.indexOf('}',start));
 const value=body.match(new RegExp(`(?:[;{])${property}:([^;}]*)`))?.[1];assert.ok(value,`${selector} ${property}`);return value;
};
for(const[name,t]of[['light',light],['dark',dark]]){
 const avatarBg=resolve(declaration('.workspace .project-detail .project-discussion .avatar','--accent-fill'),t);
 assert.ok(ratio(t.accent,avatarBg)>=4.5,`${name} discussion initials: ${ratio(t.accent,avatarBg).toFixed(2)}`);
 const border=resolve(declaration('.ds-button','border').split('solid ')[1],t);
 const bg=resolve(declaration('.ds-button','background'),t),fg=resolve(declaration('.ds-button','color'),t);
 assert.ok(ratio(border,t.surface)>=3,`${name} secondary border: ${ratio(border,t.surface).toFixed(2)}`);
 assert.ok(ratio(fg,bg)>=4.5,`${name} secondary text: ${ratio(fg,bg).toFixed(2)}`);
 const destructive='.ds-button[data-variant=destructive]';
 const criticalBorder=resolve(declaration(destructive,'border-color'),t);
 const criticalText=resolve(declaration(destructive,'color'),t);
 assert.notEqual(criticalBorder,t.accent,`${name} destructive border must use the critical tone`);
 for(const surface of ['surface','surface-2','bg']){
  assert.ok(ratio(criticalBorder,t[surface])>=3,`${name} destructive border on ${surface}: ${ratio(criticalBorder,t[surface]).toFixed(2)}`);
  assert.ok(ratio(criticalText,t[surface])>=4.5,`${name} destructive text on ${surface}: ${ratio(criticalText,t[surface]).toFixed(2)}`);
 }
 console.log(`${name} destructive boundary ${ratio(criticalBorder,t.surface).toFixed(2)}:1; text ${ratio(criticalText,bg).toFixed(2)}:1`);
 for(const tone of ['positive','warning','critical','accent']){
  const color=resolve(declaration(`.ds-badge[data-tone=${tone}]`,'color'),t);
  const r=ratio(color,t['surface-2']);assert.ok(r>=4.5,`${name} ${tone} badge: ${r.toFixed(2)}`);
  console.log(`${name} ${tone} badge ${r.toFixed(2)}:1`);
 }
 console.log(`${name} secondary boundary ${ratio(border,t.surface).toFixed(2)}:1; text ${ratio(fg,bg).toFixed(2)}:1`);
}
assert.ok(Number(declaration('.ds-button:disabled','opacity'))>=.55);
assert.equal(declaration('.ds-button:disabled','cursor'),'not-allowed');

const assistant=fs.readFileSync(new URL('./src/Assistant.css',import.meta.url),'utf8');
const ring=assistant.match(/\.assistant-chat\[data-input=keyboard\] \.assistant-composer:focus-within\{box-shadow:0 0 0 2px var\(--([a-z-]+)\)\}/);
assert.ok(ring,'keyboard-only composer ring uses an opaque token');
for(const [name,t] of [['light',light],['dark',dark]]){
 const contrast=ratio(t[ring[1]],t.surface);
 assert.ok(contrast>=3,`${name} composer ring: ${contrast.toFixed(2)}:1`);
 console.log(`${name} composer ring ${contrast.toFixed(2)}:1`);
}

export {ratio};

// Browser regression: bundle the real application cascade, including legacy page
// styles. Token-pair arithmetic alone cannot detect a white surface override.
const {build}=await import('esbuild');
const {chromium}=await import('playwright-core');
const bundled=await build({entryPoints:['src/main.tsx'],bundle:true,write:false,outdir:'.contrast-build',loader:{'.png':'file','.svg':'file','.jpg':'file','.webp':'file'}});
const appCss=bundled.outputFiles.filter(f=>f.path.endsWith('.css')).map(f=>f.text).join('\n')
 // Lazy case styles may arrive after the shared case rules. Exercise that order too.
 +fs.readFileSync(new URL('./src/ProjectOverview.css',import.meta.url),'utf8')
 +fs.readFileSync(new URL('./src/ProjectCalm.css',import.meta.url),'utf8');
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage();
 await page.setContent(`<html data-theme="dark"><style>${appCss}</style><body><div class="app-shell"><main class="workspace">
 <div class="project-detail project-detail-calm"><div class="project-overview"><div class="pf-diagram i3-stepper pf-diagram-compact"><h2>案件流程</h2><button class="pf-node" aria-pressed="true" aria-current="step"><span class="pf-node-title"><strong>控制</strong></span><span class="pf-state">進行中</span></button><button class="pf-node"><span class="pf-node-title">下一階段</span></button><details class="i3-legend"><summary>狀態圖例</summary></details></div><section class="pf-panel glass--card"><h3>本階段任務</h3><span class="st-count">已完成 0 / 3 項</span></section></div><div class="pf-stage-workspace"><section class="pf-panel"><span class="st-count">已完成 0 / 3 項</span><span class="pf-evidence-state">待核對</span><div class="pf-plan-facts"><dl><dt>來源計畫總量</dt></dl><p class="pf-plan-note">不同單位不加總</p></div><div class="pf-items-heading"><a>完整表格</a></div><ul class="pf-gap-list"><li><strong>實際完成量未知</strong><p>補齊方式</p></li></ul></section></div></div>
 <div class="project-detail project-detail-calm"><div class="detail-page-content"><form class="mention-composer"><span class="disabled-action"><span class="disabled-action-reason">目前無法操作</span></span></form></div></div>

 </main></div></body></html>`);
 const checks=async label=>{
  const samples=await page.evaluate(()=>{
   const rgb=s=>{const c=document.createElement('canvas').getContext('2d');c.fillStyle=s;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data]};
   return [...document.querySelectorAll('main,h2,h3,.pf-gap-list p,.pf-node,.pf-node-title,.pf-state,summary,.st-count,.pf-evidence-state,dt,.pf-plan-note,.pf-items-heading a,.pf-gap-list strong,.administration-page button,.disabled-action-reason')].map(e=>{
    const s=getComputedStyle(e),chain=[];for(let a=e;a;a=a.parentElement)chain.unshift(a);
    let bg=[255,255,255,255];for(const a of chain){const c=rgb(getComputedStyle(a).backgroundColor),alpha=c[3]/255;bg=[...c.slice(0,3).map((v,i)=>Math.round(v*alpha+bg[i]*(1-alpha))),255]}
    // Primary controls use a gradient; inspect its lightest and darkest stops.
    const stops=[...s.backgroundImage.matchAll(/(?:rgba?|color)\([^)]*\)/g)].map(m=>rgb(m[0]));
    return {text:e.textContent,fg:rgb(s.color),backgrounds:stops.length?stops:[bg],border:rgb(s.borderColor),borderWidth:parseFloat(s.borderWidth),selected:e.matches('[aria-pressed=true]')};
   });
  });
  const toHex=c=>'#'+c.slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('');
  let minimum=Infinity,boundary=null;
  for(const s of samples){
   for(const bg of s.backgrounds){const r=ratio(toHex(s.fg),toHex(bg));minimum=Math.min(minimum,r);assert.ok(r>=4.5,`${label} ${s.text}: ${r.toFixed(2)}:1 (text requires 4.5:1)`)}
   if(s.selected){assert.ok(s.borderWidth>=1,`${label} selected stage has a visible boundary`);const r=ratio(toHex(s.border),toHex(s.backgrounds[0]));boundary=r;assert.ok(r>=3,`${label} selected stage boundary: ${r.toFixed(2)}:1 (requires 3:1)`)}
  }
  console.log(`${label}: ${samples.length} computed samples; minimum text ${minimum.toFixed(2)}:1${boundary===null?'':`; selected boundary ${boundary.toFixed(2)}:1`}`);
 };
 await checks('dark overview');
 await page.locator('.project-overview').evaluate(e=>e.classList.replace('project-overview','pf-stage-workspace'));
 await checks('dark flow');
 await page.setContent(`<html data-theme=dark><style>${appCss}</style><body><div class=app-shell><main class=workspace> <div class="operations administration-page"><details class="ops-form" open><summary>設定</summary><form><button class="ds-button" data-variant="primary">儲存類別</button><button class="ds-button" data-variant="primary">儲存</button><button class="ds-button">新增類別</button></form></details></div></main></div></body></html>`);
 await checks('dark admin');
 for(const button of await page.locator('.administration-page button[data-variant=primary]').all()){
  await button.hover();await checks(`dark admin hover ${await button.textContent()}`);
 }

}finally{await browser.close()}
