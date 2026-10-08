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
