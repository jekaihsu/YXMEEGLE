import type {ModelId} from './runtime';
export type ModelCatalog={default:ModelId;models:{id:ModelId;label:string;available:boolean}[]};
export function rememberedModel(catalog:ModelCatalog):ModelId {
 let saved:string|null=null;
 try{saved=localStorage.getItem('yx:ai-model')}catch{}
 return catalog.models.find(m=>m.id===saved&&m.available)?.id||catalog.models.find(m=>m.id===catalog.default&&m.available)?.id||catalog.models.find(m=>m.available)?.id||catalog.default;
}
export function ModelPicker({catalog,value,onChange,disabled}:{catalog:ModelCatalog;value:ModelId;onChange:(id:ModelId)=>void;disabled:boolean}){
 const unavailable=(['claude','gpt'] as const).filter(id=>!catalog.models.some(m=>m.id===id&&m.available));
 return <div className="assistant-model"><div className="ds-segmented" role="group" aria-label="選擇 AI 助理">{(['claude','gpt'] as const).map(id=><button key={id} type="button" aria-pressed={value===id} className={value===id?'active':undefined} disabled={disabled||unavailable.includes(id)} aria-describedby={unavailable.includes(id)?'assistant-model-unavailable':undefined} onClick={()=>{try{localStorage.setItem('yx:ai-model',id)}catch{}onChange(id)}}>{id==='claude'?'Claude':'GPT'}</button>)}</div>{unavailable.length>0&&<small id="assistant-model-unavailable">{unavailable.map(id=>id==='claude'?'Claude':'GPT').join('、')} 尚未設定</small>}</div>;
}
