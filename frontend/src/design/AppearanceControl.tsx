import {useAppearance,type TextSize,type ThemeMode} from './appearance';

const THEMES:[ThemeMode,string][]=[['system','跟隨系統'],['light','淺色'],['dark','深色']];
const SIZES:[TextSize,string][]=[['s','小'],['m','中'],['l','大'],['xl','特大']];

function Choice<T extends string>({legend,options,value,onChange}:{legend:string;options:[T,string][];value:T;onChange:(v:T)=>void}){
 return <fieldset className="appearance-choice"><legend>{legend}</legend>{options.map(([k,label])=><label key={k}><input type="radio" name={legend} checked={value===k} onChange={()=>onChange(k)}/>{label}</label>)}</fieldset>;
}

export function AppearanceControl(){
 const a=useAppearance();
 return <section className="appearance-control" aria-label="外觀"><Choice legend="外觀模式" options={THEMES} value={a.theme} onChange={theme=>a.set({theme})}/><Choice legend="文字大小" options={SIZES} value={a.text} onChange={text=>a.set({text})}/></section>;
}
