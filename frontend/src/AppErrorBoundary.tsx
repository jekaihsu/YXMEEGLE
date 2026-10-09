import {Section,Button} from './design';
import './owned-screens.css';
import {Component,type ErrorInfo,type ReactNode} from 'react';

type State={failed:boolean;detail:string;copied:boolean};

// Collapsed by default: the report is only rendered after the reader opens it, and is copied only on request.
export class AppErrorBoundary extends Component<{children:ReactNode},State>{
 state:State={failed:false,detail:'',copied:false};
 static getDerivedStateFromError(){return {failed:true}}
 componentDidCatch(error:Error,info:ErrorInfo){this.setState({detail:[`時間：${new Date().toISOString()}`,`網址：${location.href}`,`訊息：${error.message}`,`堆疊：\n${error.stack||'（無）'}`,`元件堆疊：${info.componentStack||'（無）'}`].join('\n')})}
 copy=async()=>{try{await navigator.clipboard.writeText(this.state.detail);this.setState({copied:true})}catch{this.setState({copied:false})}};
 render(){return this.state.failed?<main className="owned-view owned-state"><Section><h1>畫面暫時無法顯示</h1><p>資料或畫面發生錯誤，請重新載入。若仍無法開啟，請將目前頁面網址提供給管理員核對。</p><Button variant="primary" onClick={()=>location.reload()}>重新載入</Button><a className="text-button" href="/">返回工作總覽</a><details className="error-details"><summary>錯誤詳情</summary><pre>{this.state.detail}</pre><Button onClick={()=>void this.copy()}>{this.state.copied?'已複製':'複製錯誤詳情'}</Button></details></Section></main>:this.props.children}
}
