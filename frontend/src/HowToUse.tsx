import {useEffect} from 'react';
import {HOWTO_SECTIONS} from './howToContent';
import './HowToUse.css';

export function HowToUse({section}:{section?:string}) {
 useEffect(()=>{
  const target=document.getElementById(section || 'howto-title');
  if(section)target?.scrollIntoView({block:'start'});
  target?.focus({preventScroll:true});
 },[section]);
 return <article className="howto" aria-labelledby="howto-title">
  <header className="page-heading"><div><h1 id="howto-title" tabIndex={-1}>使用說明</h1><p>從開啟案件到處理待辦，依照步驟完成工作。</p></div></header>
  <nav className="howto-toc" aria-label="使用說明目錄"><h2>我要做什麼？</h2><ol>{HOWTO_SECTIONS.map(item=><li key={item.id}><a href={`#view=howto&section=${item.id}`}>{item.title}</a></li>)}</ol></nav>
  <p className="howto-note">圖片使用示範案件與虛構人員。可用的操作以你的權限及目前畫面為準。</p>
  {HOWTO_SECTIONS.map((item,index)=><section className="howto-section" id={item.id} tabIndex={-1} key={item.id} aria-labelledby={`${item.id}-title`}>
   <h2 id={`${item.id}-title`}><span aria-hidden="true">{String(index+1).padStart(2,'0')}</span>{item.title}</h2>
   <figure><a href={`/howto/${item.image}`} target="_blank" rel="noreferrer" aria-label={`放大圖片：${item.title}（另開分頁）`}><img src={`/howto/${item.image}`} alt={item.alt} width="1440" height="900" loading="lazy"/></a><figcaption>{item.caption} · 點圖片可放大</figcaption></figure>
   <ol className="howto-steps">{item.steps.map(step=><li key={step}>{step}</li>)}</ol>
   {item.id==='open-case'&&<details className="howto-mobile-example"><summary>查看手機畫面</summary><figure><img src="/howto/overview-mobile.webp" alt="手機版案件總覽，九節點流程可左右捲動，待辦事項依序排列。" width="390" height="844" loading="lazy"/><figcaption>手機版總覽</figcaption></figure></details>}
   <a className="howto-back" href="#view=howto">回到目錄 ↑</a>
  </section>)}
 </article>;
}
