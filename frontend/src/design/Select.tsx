import {useLayoutEffect,useRef,useState,type SelectHTMLAttributes} from 'react';
import {Picker} from './index';
export function Select({className='',style,...props}:SelectHTMLAttributes<HTMLSelectElement>){
 const native=useRef<HTMLSelectElement>(null);
 const [unavailable,setUnavailable]=useState(!!props.disabled);
 const [options,setOptions]=useState<[string,string][]>([]),[disabledOptions,setDisabledOptions]=useState<string[]>([]),[label,setLabel]=useState('選擇'),[value,setValue]=useState('');
 useLayoutEffect(()=>{
  const select=native.current;if(!select)return;
  setUnavailable(select.matches(':disabled'));
  const next=Array.from(select.options).map<[string,string]>(option=>[option.value,option.text]);
  setOptions(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);
  const blocked=Array.from(select.options).filter(option=>option.disabled||option.parentElement?.tagName==='OPTGROUP'&&option.parentElement.hasAttribute('disabled')).map(option=>option.value);
  setDisabledOptions(old=>JSON.stringify(old)===JSON.stringify(blocked)?old:blocked);
  setValue(select.value);
  const owner=select.labels?.[0]?.cloneNode(true);
  if(owner instanceof window.HTMLElement)owner.querySelectorAll('.ds-select,select,button').forEach(element=>element.remove());
  const explicit=props['aria-label']||(props['aria-labelledby']?document.getElementById(props['aria-labelledby'])?.textContent:'')||owner?.textContent?.trim();
  setLabel(explicit||'選擇');
 });
 if(props.multiple||props.size&&props.size>1)return <select {...props} className={className} style={style}/>;
 return <span className={`ds-select ${className}`} style={style}>
  <select {...props} ref={native} className="ds-select-native" tabIndex={-1} aria-hidden="true" onFocus={()=>native.current?.parentElement?.querySelector('button')?.focus()} onInvalid={event=>{event.preventDefault();native.current?.parentElement?.querySelector('button')?.focus()}}/>
  <Picker label={label} options={options} value={value} disabled={unavailable} disabledOptions={disabledOptions} searchable={options.length>8} onChange={next=>{const select=native.current;if(!select)return;select.value=next;select.dispatchEvent(new Event('change',{bubbles:true}));setValue(select.value)}}/>
 </span>;
}
