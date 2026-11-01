// Ported from assistant-ui thread.aui and message-pair (MIT). See elements/LICENSE.assistant-ui.
import {createContext,useContext,useCallback,useEffect,useMemo,useRef,useState,type ReactNode,type MutableRefObject} from 'react';
import {AssistantRuntimeProvider,useLocalRuntime,ThreadPrimitive,ComposerPrimitive,MessagePrimitive,ActionBarPrimitive,ErrorPrimitive,useAuiState} from '@assistant-ui/react';
import {MarkdownTextPrimitive} from '@assistant-ui/react-markdown';
import {ConversationHistory} from './ConversationHistory';
import {historyMessages,type ConversationDetail} from './history';
import {assistantRemarkPlugins} from './markdown';
import {Button} from '../design';
import {api,ApiError} from '../api';
import {createChatAdapter,errorText} from './runtime';
import {ModelSelector,type ModelCatalog} from './ModelSelector';
import {createFeedbackController,FeedbackActions,FeedbackContext} from './feedback';
import {toolUIs,ToolResult} from './ToolResult';
import {ThinkingIndicator} from './elements/ThinkingIndicator';
import '../Assistant.css';
import './elements/elements.css';

const suggestions=['今天誰遲到？','今天誰還沒打卡？','某案件進度（請輸入案名或編號）','某案件負責人是誰？'];
const Markdown=()=> <MarkdownTextPrimitive smooth={false} remarkPlugins={assistantRemarkPlugins} components={{
 img:({alt})=><>{alt}</>,
 a:({href,children})=>href&&/^https?:\/\//i.test(href)?<a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>:<>{children}</>,
 table:({children})=><div className="assistant-table" tabIndex={0} role="region" aria-label="回答表格"><table>{children}</table></div>,
}}/>;

function AnswerError(){
 const detail=useAuiState(s=>s.message.metadata.custom?.error_detail);
 return <MessagePrimitive.Error><ErrorPrimitive.Root data-slot="error-state" role="alert" className="assistant-error"><ErrorPrimitive.Message/>{typeof detail==='string'&&detail&&<small className="assistant-error-detail">{detail}</small>}</ErrorPrimitive.Root></MessagePrimitive.Error>;
}

function UserMessage(){
 return <MessagePrimitive.Root data-slot="aui_user-message-root" data-role="user" className="assistant-message assistant-user">
  <div data-slot="aui_user-message-content"><MessagePrimitive.Parts/></div>
 </MessagePrimitive.Root>;
}

const ForbiddenContext=createContext(false);
function AssistantMessage(){
 const forbidden=useContext(ForbiddenContext);
 const thinking=useAuiState(s=>s.message.status?.type==='running'&&!s.message.content.some(p=>p.type==='text'&&p.text.length>0));
 return <MessagePrimitive.Root data-slot="aui_assistant-message-root" data-role="assistant" className="assistant-message">
  {thinking&&<ThinkingIndicator/>}
  <MessagePrimitive.Parts components={{Text:Markdown,tools:{by_name:toolUIs,Fallback:ToolResult}}}/>
  <AnswerError/>
  <ActionBarPrimitive.Root hideWhenRunning data-slot="message-actions" className="assistant-actions">
   <ActionBarPrimitive.Copy asChild><Button variant="plain">
    <MessagePrimitive.If copied={false}>複製回答</MessagePrimitive.If><MessagePrimitive.If copied>已複製</MessagePrimitive.If>
   </Button></ActionBarPrimitive.Copy>
   {!forbidden&&<ActionBarPrimitive.Reload asChild><Button variant="plain">重試</Button></ActionBarPrimitive.Reload>}
   <FeedbackActions/>
  </ActionBarPrimitive.Root>
 </MessagePrimitive.Root>;
}

function MessageLog({children}:{children:ReactNode}){
 const running=useAuiState(s=>s.thread.isRunning);
 const outcome=useAuiState(s=>{
  const message=s.thread.messages.at(-1);
  if(message?.role!=='assistant')return '';
  const status=message.status;
  if(status?.type==='complete')return `${message.id}|回答完成`;
  if(status?.type==='incomplete')return `${message.id}|${status.reason==='cancelled'?'已停止':`回答失敗${typeof status.error==='string'&&status.error?`：${status.error}`:''}`}`;
  return '';
 });
 const [outcomeId,outcomeText]=outcome.split('|');
 const viewport=useRef<HTMLDivElement>(null),messages=useRef<HTMLDivElement>(null);
 const [away,setAway]=useState(false);
 useEffect(()=>{
  const element=viewport.current!;
  const update=()=>setAway(element.scrollHeight-element.clientHeight-element.scrollTop>80);
  element.addEventListener('scroll',update,{passive:true});
  const observer=new ResizeObserver(update);
  observer.observe(element);observer.observe(messages.current!);update();
  return()=>{element.removeEventListener('scroll',update);observer.disconnect()};
 },[]);
 return <>
  <div className="assistant-scroll-region">
  <ThreadPrimitive.Viewport ref={viewport} data-slot="aui_thread-viewport" className="assistant-viewport" tabIndex={-1} autoScroll role="log" aria-live="off" aria-busy={running}>
   <div ref={messages}>{children}<ThreadPrimitive.Messages components={{UserMessage,AssistantMessage}}/></div>
  </ThreadPrimitive.Viewport>
  <Button hidden={!away} data-slot="scroll-anchor" className="assistant-bottom" onClick={()=>{const element=viewport.current!;element.focus({preventScroll:true});element.scrollTo({top:element.scrollHeight,behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}}>回到最新回答</Button>
  </div>
  <div className="assistant-completion" role="status">{!running&&outcomeText&&<span key={outcomeId}>{outcomeText}</span>}</div>
 </>;
}

function Conversation({catalog,newConversation,projectId,projectLabel,compact,selected,onComplete,cancelResponse}:AssistantChatProps&{catalog:ModelCatalog;newConversation:()=>void;selected:{id:string;detail?:ConversationDetail};onComplete:()=>void;cancelResponse:MutableRefObject<()=>Promise<void>>}){
 const [forbidden,setForbidden]=useState(false);
 const conversation=useRef(selected.id);
 const settled=useRef<Promise<void>>(Promise.resolve());
 const adapter=useMemo(()=>{
  const base=createChatAdapter(()=>conversation.current,()=>setForbidden(true),projectId,onComplete);
  return {async *run(...args:Parameters<typeof base.run>){
   let finish!:()=>void;
   settled.current=new Promise<void>(resolve=>{finish=resolve});
   try{const result=base.run(...args);if(Symbol.asyncIterator in result)yield* result;else yield await result}finally{finish()}
  }};
 },[]);
 const runtimeRef=useRef<ReturnType<typeof useLocalRuntime>>();
 const feedback=useMemo(()=>createFeedbackController(()=>runtimeRef.current!),[]);
 const runtime=useLocalRuntime(adapter,{initialMessages:selected.detail?historyMessages(selected.detail):[],adapters:{feedback:feedback.adapter}});
 runtimeRef.current=runtime;
 useEffect(()=>{
  const cancel=async()=>{runtime.thread.cancelRun();await settled.current};
  cancelResponse.current=cancel;
  return()=>{if(cancelResponse.current===cancel)cancelResponse.current=async()=>{}};
 },[runtime,cancelResponse]);
 useEffect(()=>{feedback.activate();return()=>{feedback.dispose();runtime.thread.cancelRun()}},[runtime,feedback]);
 const available=!forbidden&&catalog.models.some(m=>m.available);
 const input=useRef<HTMLTextAreaElement>(null);
 return <AssistantRuntimeProvider runtime={runtime}><FeedbackContext.Provider value={feedback}><ForbiddenContext.Provider value={forbidden}>
  <div className={`assistant-chat${compact?' assistant-chat-compact':''}`}>
   <ThreadPrimitive.Root data-slot="aui_thread-root" className="assistant-thread">
    <Button variant="plain" className="assistant-new" onClick={()=>{runtime.thread.cancelRun();newConversation()}}>新對話</Button>
    <MessageLog>
     <ThreadPrimitive.Empty>
      <div data-slot="empty-state" className="assistant-empty">
       <h2 data-slot="empty-state-greeting">{projectId?(projectLabel||'想了解這個案件的什麼？'):'想先確認哪件事？'}</h2>
       <div data-slot="empty-state-suggestions" className="assistant-suggestions">{(projectId?projectSuggestions:suggestions).map((text,index)=><ThreadPrimitive.Suggestion key={text} prompt={projectId||index<2?text:index===2?'請查詢案件進度：':'請查詢案件負責人：'} send={!!projectId||index<2} asChild><Button data-slot="empty-state-suggestion" disabled={!available} onClick={()=>input.current?.focus()}>{text}</Button></ThreadPrimitive.Suggestion>)}</div>
      </div>
     </ThreadPrimitive.Empty>
    </MessageLog>
    <ComposerPrimitive.Root data-slot="aui_composer-shell" className="assistant-composer">
     <ComposerPrimitive.Input ref={input} aria-label="詢問 AI 助理" placeholder="輸入問題" maxLength={4000} disabled={!available} rows={1}/>
     <div className="assistant-composer-bar">
      <ModelSelector catalog={catalog}/>
      <ThreadPrimitive.If running={false}><ComposerPrimitive.Send asChild disabled={!available}><Button variant="primary">送出</Button></ComposerPrimitive.Send></ThreadPrimitive.If>
      <ThreadPrimitive.If running><ComposerPrimitive.Cancel asChild><Button>停止回應</Button></ComposerPrimitive.Cancel></ThreadPrimitive.If>
     </div>
    </ComposerPrimitive.Root>
   </ThreadPrimitive.Root>
  </div>
 </ForbiddenContext.Provider></FeedbackContext.Provider></AssistantRuntimeProvider>;
}

export type AssistantChatProps={projectId?:string;projectLabel?:string;compact?:boolean;catalog?:ModelCatalog};
const projectSuggestions=['進度如何？','卡在哪裡？','誰負責？','下一步是什麼？','最近有什麼變更？'];
export function AssistantChat(props:AssistantChatProps){
 return <AssistantChatWorkspace key={props.projectId||'global'} {...props}/>;
}
function AssistantChatWorkspace(props:AssistantChatProps){
 const [selected,setSelected]=useState<{id:string;detail?:ConversationDetail}>(()=>({id:crypto.randomUUID()}));
 const cancelResponse=useRef<()=>Promise<void>>(async()=>{});
 const [revision,setRevision]=useState(0),[generation,setGeneration]=useState(0);
 const completed=useCallback(()=>setRevision(n=>n+1),[]);
 const [catalog,setCatalog]=useState<ModelCatalog|undefined>(props.catalog);
 const [error,setError]=useState<'load'|'forbidden'|null>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  if(props.catalog){setCatalog(props.catalog);return}
  const controller=new AbortController();setError(null);
  api<ModelCatalog>('/api/ai/models',{signal:controller.signal}).then(data=>{
   if(controller.signal.aborted)return;
   setCatalog(data);
  }).catch(error=>{if(!controller.signal.aborted)setError(error instanceof ApiError&&(error.status===403&&error.code==='ai_forbidden')?'forbidden':'load')});
  return()=>controller.abort();
 },[attempt,props.catalog]);
 if(!catalog)return <div className="assistant-chat">{error
  ?error==='forbidden'?<p role="alert">{errorText('ai_forbidden')}</p>:<p role="alert">無法載入 AI 助理。<Button onClick={()=>setAttempt(n=>n+1)}>重試</Button></p>
  :<p role="status">正在載入 AI 助理…</p>}
 </div>;
 const fresh=()=>{setGeneration(n=>n+1);setSelected({id:crypto.randomUUID()})};
 return <ConversationHistory projectId={props.projectId} compact={props.compact} revision={revision} activeId={selected.id} beforeDelete={()=>cancelResponse.current()} onNew={fresh} onOpen={detail=>{setGeneration(n=>n+1);setSelected({id:detail.id,detail})}}>
  <Conversation key={`${selected.id}:${generation}`} {...props} catalog={catalog} cancelResponse={cancelResponse} selected={selected} onComplete={completed} newConversation={fresh}/>
 </ConversationHistory>;
}
