async (page) => {
  page=page.context().pages().find(p=>p.url().startsWith('https://yongxiang-projects-20260925.zeabur.app/'));
  if(!page)throw new Error('Cloud app page unavailable');
  return await page.evaluate(async()=>{
    const safeRead=async path=>{try{const response=await fetch(path,{signal:AbortSignal.timeout(8000)});return {status:response.status,data:await response.json()}}catch{return {status:'timeout',data:{}}}};
    const [session,ws,source]=await Promise.all([safeRead('/api/session'),safeRead('/api/workspace'),safeRead('/api/sources')]);const s=session.data;const x=source.data;
    const allowed=['公司駕駛艙','案件總覽','我的工作','排程與人力','變更與展延','資料來源'];
    return {session_status:session.status,mode:s.mode,role:s.user?.role,workspace_status:ws.status,source_status:source.status,source_tables:x.tables?.length,source_records:x.records?.length,document_title:document.title,view:new URLSearchParams(location.hash.slice(1)).get('view'),headings:[...document.querySelectorAll('h1,h2')].map(e=>allowed.includes(e.textContent||'')?e.textContent:'[omitted]'),body_children:document.body.children.length,has_loading:document.body.innerText.includes('準備你的工作台'),has_login:document.body.innerText.includes('請先登入'),has_error_banner:!!document.querySelector('.error-banner'),react_root_child_count:document.getElementById('root')?.children.length};
  });
}
