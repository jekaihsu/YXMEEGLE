async (page) => {
 const cloud=page.context().pages().find(p=>p.url().startsWith('https://yongxiang-projects-20260925.zeabur.app/'));
 return await cloud.evaluate(()=>({
 path:location.hash,
 headings:[...document.querySelectorAll('h1')].map(x=>x.textContent),
 table_count:document.querySelectorAll('main table').length,
 selects:[...document.querySelectorAll('select')].map(x=>({label:x.getAttribute('aria-label'),options:x.options.length})),
 loading:document.body.textContent.includes('讀取來源狀態'), requests:performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/')).map(x=>({path:new URL(x.name).pathname,duration:Math.round(x.duration),bytes:x.transferSize,body:x.decodedBodySize})),
 main_loading:document.body.textContent.includes('準備你的工作台'),
 error_labels:[...document.querySelectorAll('[role=alert], .error-banner')].map(x=>x.textContent.slice(0,300)),
 source_buttons:[...document.querySelectorAll('main button')].map(x=>x.textContent).filter(x=>/同步|重試|載入/.test(x)),
 scripts:[...document.scripts].map(x=>x.src).filter(x=>x.includes('/assets/')),
 known_flags:['部分資料','已讀取','目前尚未同步','尚未設定','篩選來源類型','來源資料待確認'].filter(s=>document.body.textContent.includes(s))
 }));
}