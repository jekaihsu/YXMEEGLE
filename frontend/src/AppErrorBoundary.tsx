import {Section,Button} from './design';
import './owned-screens.css';
import {Component,type ErrorInfo,type ReactNode} from 'react';

export class AppErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true}}
 componentDidCatch(_error:Error,_info:ErrorInfo){/* Do not expose case content or error payloads. */}
 render(){return this.state.failed?<main className="owned-view owned-state"><Section><h1>畫面暫時無法顯示</h1><p>資料或畫面發生錯誤，請重新載入。若仍無法開啟，請將目前頁面網址提供給管理員核對。</p><Button variant="primary" onClick={()=>location.reload()}>重新載入</Button><a className="text-button" href="/">返回工作總覽</a></Section></main>:this.props.children}
}
