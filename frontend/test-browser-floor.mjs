import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {JSDOM,VirtualConsole} from 'jsdom';
const html=await fs.readFile(new URL('./index.html',import.meta.url),'utf8');
const message='請更新瀏覽器（建議 Chrome 111 或 Safari 16.4 以上）';
function load({mix=true,layer=true,css=true}={}){
 return new JSDOM(html,{url:'http://localhost',runScripts:'dangerously',virtualConsole:new VirtualConsole(),beforeParse(window){
  if(css)window.CSS={supports:(property,value)=>property==='color'&&value.includes('color-mix')&&mix};
  const create=window.document.createElement.bind(window.document);
  window.document.createElement=(tag,...args)=>{const element=create(tag,...args);if(tag==='style')Object.defineProperty(element,'sheet',{get:()=>({cssRules:layer?[{cssText:'@layer browser-floor {}'}]:[]})});return element};
 }});
}
for(const options of [{mix:false},{layer:false},{css:false}]){const dom=load(options);assert.equal(dom.window.document.getElementById('root').textContent,message);assert.equal(dom.window.yxBrowserSupported,false);dom.window.close()}
const supported=load();assert.equal(supported.window.yxBrowserSupported,true);assert.equal(supported.window.document.getElementById('root').textContent,'');supported.window.close();
const entry=await fs.readFile(new URL('./src/main.tsx',import.meta.url),'utf8');
assert.match(entry,/if\(document\.documentElement\.dataset\.browserSupported==='true'\)ReactDOM.createRoot/,'app mounts only after feature checks pass');
console.log('PASS browser floor rejects missing color-mix, layers and CSS API and permits supported browsers');
