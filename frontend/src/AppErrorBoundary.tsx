import {Button} from './design';
import {CircleAlert,Copy,RotateCw,ArrowLeft,Check} from 'lucide-react';
import './AppErrorBoundary.css';
import {Component,type ErrorInfo,type ReactNode} from 'react';

type State={failed:boolean;detail:string;copyStatus:'idle'|'copied'|'failed'};

// Reports stay collapsed and are copied only at the user's request.
export class AppErrorBoundary extends Component<{children:ReactNode},State>{
 state:State={failed:false,detail:'',copyStatus:'idle'};
 static getDerivedStateFromError(){return {failed:true}}
 componentDidCatch(error:Error,info:ErrorInfo){this.setState({detail:[`時間：${new Date().toISOString()}`,`網址：${location.href}`,`訊息：${error.message}`,`堆疊：\n${error.stack||'（無）'}`,`元件堆疊：${info.componentStack||'（無）'}`].join('\n')})}
 copy=async()=>{try{await navigator.clipboard.writeText(this.state.detail);this.setState({copyStatus:'copied'})}catch{this.setState({copyStatus:'failed'})}};
 render(){
  if(!this.state.failed)return this.props.children;
  return <main className="error-page"><section className="error-panel glass" aria-labelledby="error-title">
   <div className="error-symbol" aria-hidden="true"><CircleAlert size={28} strokeWidth={1.6}/></div>
   <p className="error-eyebrow">暫時發生問題</p>
   <h1 id="error-title">這個畫面暫時無法開啟</h1>
   <p className="error-description">請重新載入頁面再試一次，或先返回工作總覽。</p>
   <div className="error-actions"><Button variant="primary" onClick={()=>location.reload()}><RotateCw size={16}/>重新載入頁面</Button><a className="ds-button" href="/#view=dashboard"><ArrowLeft size={16}/>返回工作總覽</a></div>
   <p className="error-help">若問題持續，請展開下方資訊，複製給管理員協助查詢。</p>
   <details className="error-report"><summary>錯誤詳情</summary><div className="error-report-body"><p>包含目前頁面網址、發生時間與錯誤訊息。</p><pre tabIndex={0} aria-label="錯誤資訊">{this.state.detail}</pre><Button onClick={()=>void this.copy()}>{this.state.copyStatus==='copied'?<Check size={16}/>:<Copy size={16}/>}複製錯誤資訊</Button><p className="error-copy-status" role="status">{this.state.copyStatus==='copied'?'已複製，可以貼給管理員。':this.state.copyStatus==='failed'?'無法自動複製，請選取上方資訊手動複製。':''}</p></div></details>
  </section></main>;
 }
}
