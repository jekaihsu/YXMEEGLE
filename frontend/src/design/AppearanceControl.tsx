import {Segmented} from './index';
import {useAppearance,type TextSize,type ThemeMode} from './appearance';

const THEMES:[ThemeMode,string][]=[['system','自動'],['light','淺色'],['dark','深色']];
const SIZES:[TextSize,string][]=[['s','S'],['m','M'],['l','L'],['xl','XL']];

export function AppearanceControl(){
 const a=useAppearance();
 return <section className="appearance-control" aria-label="外觀"><div className="appearance-field"><span aria-hidden="true">外觀模式</span><Segmented label="外觀模式" options={THEMES} value={a.theme} onChange={theme=>a.set({theme})}/></div><div className="appearance-field"><span aria-hidden="true">文字大小</span><Segmented label="文字大小" options={SIZES} value={a.text} onChange={text=>a.set({text})}/></div></section>;
}
