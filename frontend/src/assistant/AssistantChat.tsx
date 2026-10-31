// Ported from assistant-ui thread.aui and message-pair (MIT). See elements/LICENSE.assistant-ui.
import {createContext,useContext,useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {AssistantRuntimeProvider,useLocalRuntime,ThreadPrimitive,ComposerPrimitive,MessagePrimitive,ActionBarPrimitive,ErrorPrimitive,useAuiState} from '@assistant-ui/react';
import {MarkdownTextPrimitive} from '@assistant-ui/react-markdown';
import remarkGfm from 'remark-gfm';
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
const Markdown=()=> <MarkdownTextPrimitive smooth={false} remarkPlugins={[remarkGfm]} components={{
 img:({alt})=><>{alt}</>,
 a:({href,children})=>href&&/^https?:\/\//i.test(href)?<a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>:<>{children}</>,
 table:({children})=><div className="assistant-table" tabIndex={0} role="region" aria-label="回答表格"><table>{children}</table></div>,
}}/>;

function AnswerError(){
 return <MessagePrimitive.Error><ErrorPrimitive.Root data-slot="error-state" role="alert" className="assistant-error"><ErrorPrimitive.Message/></ErrorPrimitive.Root></MessagePrimitive.Error>;
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
 const completed=useAuiState(s=>{const message=s.thread.messages.at(-1);return message?.role==='assistant'&&message.status?.type==='complete'?message.id:null});
 return <ThreadPrimitive.Viewport data-slot="aui_thread-viewport" className="assistant-viewport" autoScroll role="log" aria-live="polite" aria-relevant="additions" aria-busy={running}>
  <div aria-live="off">{children}<ThreadPrimitive.Messages components={{UserMessage,AssistantMessage}}/></div>
  <div className="assistant-completion" role="status">{!running&&completed&&<span key={completed}>回答完成</span>}</div>
  <ThreadPrimitive.ScrollToBottom asChild><Button data-slot="scroll-anchor" className="assistant-bottom">回到最新回答</Button></ThreadPrimitive.ScrollToBottom>
 </ThreadPrimitive.Viewport>;
}

function Conversation({catalog,newConversation,projectId,projectLabel,compact}:AssistantChatProps&{catalog:ModelCatalog;newConversation:()=>void}){
 const [forbidden,setForbidden]=useState(false);
 const conversation=useRef(crypto.randomUUID());
 const adapter=useMemo(()=>createChatAdapter(()=>conversation.current,()=>setForbidden(true),projectId),[]);
 const runtimeRef=useRef<ReturnType<typeof useLocalRuntime>>();
 const feedback=useMemo(()=>createFeedbackController(()=>runtimeRef.current!),[]);
 const runtime=useLocalRuntime(adapter,{adapters:{feedback:feedback.adapter}});
 runtimeRef.current=runtime;
 useEffect(()=>{feedback.activate();return()=>{feedback.dispose();runtime.thread.cancelRun()}},[runtime,feedback]);
 const available=!forbidden&&catalog.models.some(m=>m.available);
 const input=useRef<HTMLTextAreaElement>(null);
 return <AssistantRuntimeProvider runtime={runtime}><FeedbackContext.Provider value={feedback}><ForbiddenContext.Provider value={forbidden}>
  <div className={`assistant-chat${compact?' assistant-chat-compact':''}`}><header className="assistant-heading">{!compact&&<h1>AI 助理</h1>}<Button variant="plain" onClick={()=>{runtime.thread.cancelRun();newConversation()}}>新對話</Button></header>
   <ThreadPrimitive.Root data-slot="aui_thread-root" className="assistant-thread">
    <MessageLog>
     <ThreadPrimitive.Empty>
      <div data-slot="empty-state" className="assistant-empty">
       <h2 data-slot="empty-state-greeting">{projectId?(projectLabel||'想了解這個案件的什麼？'):'想先確認哪件事？'}</h2>
       <div data-slot="empty-state-suggestions" className="assistant-suggestions">{(projectId?projectSuggestions:suggestions).map((text,index)=><ThreadPrimitive.Suggestion key={text} prompt={projectId||index<2?text:index===2?'請查詢案件進度：':'請查詢案件負責人：'} send={!!projectId||index<2} asChild><Button data-slot="empty-state-suggestion" disabled={!available} onClick={()=>input.current?.focus()}>{text}</Button></ThreadPrimitive.Suggestion>)}</div>
      </div>
     </ThreadPrimitive.Empty>
    </MessageLog>
    <ComposerPrimitive.Root data-slot="aui_composer-shell" className="assistant-composer">
     <ComposerPrimitive.Input ref={input} aria-label="詢問 AI 助理" placeholder="輸入問題" maxLength={4000} disabled={!available} rows={2}/>
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
 const [catalog,setCatalog]=useState<ModelCatalog|undefined>(props.catalog);
 const [error,setError]=useState<'load'|'forbidden'|null>(null),[attempt,setAttempt]=useState(0),[conversation,setConversation]=useState(0);
 useEffect(()=>{
  if(props.catalog){setCatalog(props.catalog);return}
  const controller=new AbortController();setError(null);
  api<ModelCatalog>('/api/ai/models',{signal:controller.signal}).then(data=>{
   if(controller.signal.aborted)return;
   setCatalog(data);
  }).catch(error=>{if(!controller.signal.aborted)setError(error instanceof ApiError&&(error.status===403&&error.code==='ai_forbidden')?'forbidden':'load')});
  return()=>controller.abort();
 },[attempt,props.catalog]);
 if(!catalog)return <div className="assistant-chat">{!props.compact&&<h1>AI 助理</h1>}{error
  ?error==='forbidden'?<p role="alert">{errorText('ai_forbidden')}</p>:<p role="alert">無法載入 AI 助理。<Button onClick={()=>setAttempt(n=>n+1)}>重試</Button></p>
  :<p role="status">正在載入 AI 助理…</p>}
 </div>;
 return <Conversation key={`${props.projectId||'global'}:${conversation}`} {...props} catalog={catalog} newConversation={()=>setConversation(n=>n+1)}/>;
}
