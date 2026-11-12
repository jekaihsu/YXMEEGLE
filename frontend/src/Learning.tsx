import {Section} from './design';
import './owned-screens.css';
// Disabled by the explicit business decision on 2026-09-27.
// Keep a non-operational component for stale imports; the app exposes no route.
export function Learning(){
 return <section className="owned-view owned-state"><Section><h1>功能已停用</h1><p>訓練、能力認定與考評目前不開放，請使用管理設定。</p></Section></section>;
}
