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
 for(const tone of ['positive','warning','critical','accent']){
  const color=resolve(declaration(`.ds-badge[data-tone=${tone}]`,'color'),t);
  const r=ratio(color,t['surface-2']);assert.ok(r>=4.5,`${name} ${tone} badge: ${r.toFixed(2)}`);
  console.log(`${name} ${tone} badge ${r.toFixed(2)}:1`);
 }
 console.log(`${name} secondary boundary ${ratio(border,t.surface).toFixed(2)}:1; text ${ratio(fg,bg).toFixed(2)}:1`);
}
assert.ok(Number(declaration('.ds-button:disabled','opacity'))>=.55);
assert.equal(declaration('.ds-button:disabled','cursor'),'not-allowed');
