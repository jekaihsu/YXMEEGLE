import {createRoot} from 'react-dom/client';
import {useState} from 'react';
import ReportsPage from './ReportsPage';
import '../design/tokens.css';
import '../design/glass.css';
import '../design/controls.css';
function Preview(){const [tab,setTab]=useState(new URLSearchParams(location.search).get('tab')||'review');return <main className="workspace app-shell" style={{padding:'var(--page-padding)',background:'var(--bg-tint)',minHeight:'100vh'}}><ReportsPage tab={tab} onTab={setTab}/></main>}
document.body.style.cssText='margin:0;background:var(--bg);font-family:var(--font)';
createRoot(document.getElementById('root')!).render(<Preview/>);
