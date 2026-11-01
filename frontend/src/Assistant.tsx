import {useEffect,useMemo,useRef,useState} from 'react';
import {AssistantRuntimeProvider,useLocalRuntime,ThreadPrimitive,ComposerPrimitive,MessagePrimitive,ActionBarPrimitive,useAuiState} from '@assistant-ui/react';
import {MarkdownTextPrimitive} from '@assistant-ui/react-markdown';
import remarkGfm from 'remark-gfm';
import {Button,Page} from './design';
import {api,ApiError} from './api';
import {createChatAdapter,errorText,type ModelId} from './assistant/runtime';
import {ModelPicker,rememberedModel,type ModelCatalog} from './assistant/ModelPicker';
import {createFeedbackController,FeedbackActions,FeedbackContext} from './assistant/feedback';
import {toolUIs,ToolResult} from './assistant/ToolResult';
import {ThinkingIndicator} from './assistant/elements/ThinkingIndicator';
import './Assistant.css';
import './assistant/elements/elements.css';

const suggestions=['今天誰遲到？','今天誰還沒打卡？','某案件進度（請輸入案名或編號）','某案件負責人是誰？'];
const Markdown=()=> <MarkdownTextPrimitive smooth={false} remarkPlugins={[remarkGfm]} components={{
 img:({alt})=><>{alt}</>,
 a:({href,children})=>href&&/^https?:\/\//i.test(href)?<a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>:<>{children}</>,
 table:({children})=><div className="assistant-table" tabIndex={0} role="region" aria-label="回答表格"><table>{children}</table></div>,
}}/>;

function AnswerError(){
 const error=useAuiState(s=>s.message.status?.type==='incomplete'?s.message.status.error:undefined);
 return error?<p role="alert" className="assistant-error">{typeof error==='string'?error:'回答未完成，請重試。'}</p>:null;
}

function UserMessage(){
 return <MessagePrimitive.Root className="assistant-message assistant-user">
  <span className="assistant-speaker">你</span><MessagePrimitive.Parts/>
 </MessagePrimitive.Root>;
}

function AssistantMessage({forbidden=false}:{forbidden?:boolean}){
 return <MessagePrimitive.Root className="assistant-message">
  <span className="assistant-speaker">AI 助理</span>
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

function Conversation({catalog,model,onModel,newConversation}:{catalog:ModelCatalog;model:ModelId;onModel:(id:ModelId)=>void;newConversation:()=>void}){
 const [forbidden,setForbidden]=useState(false);
 const conversation=useRef(crypto.randomUUID()),selected=useRef(model);
 selected.current=model;
 const adapter=useMemo(()=>createChatAdapter(()=>selected.current,()=>conversation.current,()=>setForbidden(true)),[]);
 const runtimeRef=useRef<ReturnType<typeof useLocalRuntime>>();
 const feedback=useMemo(()=>createFeedbackController(()=>runtimeRef.current!),[]);
 const runtime=useLocalRuntime(adapter,{adapters:{feedback:feedback.adapter}});
 runtimeRef.current=runtime;
 useEffect(()=>{feedback.activate();return()=>{feedback.dispose();runtime.thread.cancelRun()}},[runtime,feedback]);
 const available=!forbidden&&catalog.models.some(m=>m.id===model&&m.available);
 const input=useRef<HTMLTextAreaElement>(null);
 const ForbiddenAssistantMessage=useMemo(()=>()=> <AssistantMessage forbidden={forbidden}/>,[forbidden]);
 return <AssistantRuntimeProvider runtime={runtime}><FeedbackContext.Provider value={feedback}>
  <Page title="AI 助理" subtitle="查詢出勤與案件，掌握今天的工作。" actions={<Button onClick={()=>{runtime.thread.cancelRun();newConversation()}}>新對話</Button>}>
   <ThreadPrimitive.Root className="assistant-thread">
    <ThreadPrimitive.Viewport className="assistant-viewport" autoScroll>
     <ThreadPrimitive.Empty>
      <div className="assistant-empty">
       <span className="assistant-kicker">工作查詢</span><h2>想先確認哪件事？</h2>
       <p>可以詢問今天出勤、案件進度與負責人。</p>
       <div className="assistant-suggestions">{suggestions.map((text,index)=><Button key={text} disabled={!available} onClick={()=>{
        if(index<2)runtime.thread.append(text);
        else{runtime.thread.composer.setText(index===2?'請查詢案件進度：':'請查詢案件負責人：');input.current?.focus()}
       }}>{text}</Button>)}</div>
      </div>
     </ThreadPrimitive.Empty>
     <ThreadPrimitive.Messages components={{UserMessage,AssistantMessage:ForbiddenAssistantMessage}}/>
     <ThreadPrimitive.If running><ThinkingIndicator/></ThreadPrimitive.If>
     <ThreadPrimitive.ScrollToBottom asChild><Button className="assistant-bottom">回到最新回答</Button></ThreadPrimitive.ScrollToBottom>
    </ThreadPrimitive.Viewport>
    <ComposerPrimitive.Root className="assistant-composer">
     <ComposerPrimitive.Input ref={input} aria-label="詢問 AI 助理" placeholder="輸入出勤或案件問題…" maxLength={4000} disabled={!available} rows={2}/>
     <div className="assistant-composer-bar">
      <ThreadPrimitive.If running={false}><ModelPicker catalog={catalog} value={model} onChange={onModel} disabled={false}/></ThreadPrimitive.If>
      <ThreadPrimitive.If running><ModelPicker catalog={catalog} value={model} onChange={onModel} disabled/></ThreadPrimitive.If>
      <ThreadPrimitive.If running={false}><ComposerPrimitive.Send asChild disabled={!available}><Button variant="primary">送出</Button></ComposerPrimitive.Send></ThreadPrimitive.If>
      <ThreadPrimitive.If running><ComposerPrimitive.Cancel asChild><Button>停止回應</Button></ComposerPrimitive.Cancel></ThreadPrimitive.If>
     </div>
    </ComposerPrimitive.Root>
    <p className="assistant-note">回答依你可查看的資料整理。重要資訊請再核對原始紀錄。</p>
   </ThreadPrimitive.Root>
  </Page>
 </FeedbackContext.Provider></AssistantRuntimeProvider>;
}

export default function Assistant(){
 const [catalog,setCatalog]=useState<ModelCatalog>(),[model,setModel]=useState<ModelId>('claude');
 const [error,setError]=useState<'load'|'forbidden'|null>(null),[attempt,setAttempt]=useState(0),[conversation,setConversation]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();setError(null);
  api<ModelCatalog>('/api/ai/models',{signal:controller.signal}).then(data=>{
   if(controller.signal.aborted)return;
   setModel(rememberedModel(data));setCatalog(data);
  }).catch(error=>{if(!controller.signal.aborted)setError(error instanceof ApiError&&(error.status===403||error.code==='ai_forbidden')?'forbidden':'load')});
  return()=>controller.abort();
 },[attempt]);
 if(!catalog)return <Page title="AI 助理">{error
  ?error==='forbidden'?<p role="alert">{errorText('ai_forbidden')}</p>:<p role="alert">無法載入 AI 助理。<Button onClick={()=>setAttempt(n=>n+1)}>重試</Button></p>
  :<p role="status">正在載入 AI 助理…</p>}
 </Page>;
 return <Conversation key={conversation} catalog={catalog} model={model} onModel={setModel} newConversation={()=>setConversation(n=>n+1)}/>;
}
