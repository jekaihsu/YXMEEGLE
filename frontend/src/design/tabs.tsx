/** Keep section navigation discoverable without moving the surrounding page. */
function watchTabs(){
 const selector='.workspace .tabbar,.workspace .ops-tabs';
 const active=new WeakMap<Element,Element|null>();
 const hints=new WeakMap<Element,HTMLElement>();
 const cue=(rail:HTMLElement)=>{
  let hint=hints.get(rail);
  if(!hint){hint=document.createElement('p');hint.className='tab-scroll-hint';hint.textContent='左右捲動查看更多頁籤 ↔';rail.after(hint);hints.set(rail,hint)}
  hint.hidden=rail.scrollWidth<=rail.clientWidth+4;
  rail.dataset.scrollBefore=String(rail.scrollLeft>4);
  rail.dataset.scrollAfter=String(rail.scrollLeft+rail.clientWidth<rail.scrollWidth-4);
 };
 const update=()=>document.querySelectorAll<HTMLElement>(selector).forEach(rail=>{
  const selected=rail.querySelector<HTMLElement>('.active');
  if(selected&&active.get(rail)!==selected){
   active.set(rail,selected);
   const r=rail.getBoundingClientRect(),s=selected.getBoundingClientRect();
   rail.scrollLeft+=s.left-r.left-(rail.clientWidth-s.width)/2;
  }
  cue(rail);
 });
 const scroll=(e:Event)=>{if(e.target instanceof HTMLElement&&e.target.matches(selector))cue(e.target)};
 const resize=()=>{document.querySelectorAll(selector).forEach(rail=>active.delete(rail));update()};
 const observer=new window.MutationObserver(update);
 observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
 document.addEventListener('scroll',scroll,true);window.addEventListener('resize',resize);update();
 return()=>{observer.disconnect();document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',resize)};
}

// This observer belongs to the document lifetime; module caching prevents duplicate setup.
watchTabs();
export {};
