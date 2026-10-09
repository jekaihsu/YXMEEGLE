// WCAG AA (4.5:1) for text tokens in light, explicit dark and automatic dark themes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const css=fs.readFileSync(new URL('./src/design/tokens.css',import.meta.url),'utf8');
const block=start=>{const i=css.indexOf(start);assert(i>=0,`Missing token block: ${start}`);return css.slice(i,css.indexOf('}',i))};
const vars=b=>Object.fromEntries([...b.matchAll(/--([a-z0-9-]+):(#[0-9a-f]{6}|#[0-9a-f]{3})\b/gi)].map(m=>[m[1],m[2].length===4?'#'+[...m[2].slice(1)].map(c=>c+c).join(''):m[2]]));
const light=vars(block(':root{'));
const themes=[['light',light],['dark',{...light,...vars(block(':root[data-theme=dark]{'))}],['auto-dark',{...light,...vars(block(':root:not([data-theme=light]):not([data-theme=dark]){'))}]];
const lum=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2]};
const ratio=(a,b)=>{const[x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return(x+.05)/(y+.05)};
const pairs=[['on-accent','accent'],['accent','bg'],['accent','surface'],['label','bg'],['label-2','bg'],['label-2','surface'],['on-critical','critical'],...['positive','warning','critical'].flatMap(fg=>['surface','surface-2','bg'].map(bg=>[fg,bg]))];
const failures=[];
for(const[name,t]of themes)for(const[fg,bg]of pairs){
 assert(t[fg]&&t[bg],`${name}: missing ${fg} or ${bg}`);
 const r=ratio(t[fg],t[bg]);if(r<4.5)failures.push(`${name} ${fg} on ${bg}: ${r.toFixed(2)}:1`);
}
assert.equal(failures.length,0,failures.join('\n'));
console.log('contrast ok: light, dark, auto-dark text pairs >= 4.5:1');
