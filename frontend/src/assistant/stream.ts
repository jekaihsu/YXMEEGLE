import {isDisplay,type Display} from './elements/types';
export type StreamEvent =
 | {type:'start';conversation_id:string;provider:string;usage_id?:string}
 | {type:'tool';id:string;name:string;label:string;status:'running'|'done'|'error';displays?:Display[]}
 | {type:'text';delta:string}
 | {type:'done'}
 | {type:'error';code:string;message?:string};

export async function* readEvents(body:ReadableStream<Uint8Array>, signal:AbortSignal):AsyncGenerator<StreamEvent> {
 const reader=body.getReader(),decoder=new TextDecoder();
 let buffer='';
 const abort=()=>{void reader.cancel().catch(()=>{})};
 signal.addEventListener('abort',abort,{once:true});
 function parse(block:string):StreamEvent|undefined {
  const data=block.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
  if(!data)return;
  const event=JSON.parse(data);
  if(!event||!['start','tool','text','done','error'].includes(event.type))throw new Error('invalid_event');
  if(event.type==='text'&&typeof event.delta!=='string')throw new Error('invalid_event');
  if(event.type==='tool'&&(!['running','done','error'].includes(event.status)||!['id','name','label'].every(key=>typeof event[key]==='string')))throw new Error('invalid_event');
  if(event.type==='start'&&event.usage_id!==undefined&&typeof event.usage_id!=='string')throw new Error('invalid_event');
  if(event.type==='tool'&&event.displays!==undefined&&(!Array.isArray(event.displays)||!event.displays.every(isDisplay)))throw new Error('invalid_display');
  if(event.type==='error'&&typeof event.code!=='string')throw new Error('invalid_event');
  return event;
 }
 try {
  while(true){
   signal.throwIfAborted();
   const {value,done}=await reader.read();
   signal.throwIfAborted();
   buffer+=decoder.decode(value,{stream:!done});
   let match:RegExpExecArray|null;
   while((match=/\r?\n\r?\n/.exec(buffer))){
    const event=parse(buffer.slice(0,match.index));buffer=buffer.slice(match.index+match[0].length);
    if(event)yield event;
   }
   if(done){if(buffer.trim()){const event=parse(buffer);if(event)yield event}break}
  }
 }finally{signal.removeEventListener('abort',abort);await reader.cancel().catch(()=>{});reader.releaseLock()}
}
