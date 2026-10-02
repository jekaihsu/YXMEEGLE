async (page) => {
 const cloud=page.context().pages().find(p=>p.url().startsWith('https://yongxiang-projects-20260925.zeabur.app/'));
 if (!cloud) throw new Error('Authorized cloud tab unavailable');
 page=cloud;
 const nonReads=[];
 const listener=req=>{if(!['GET','HEAD','OPTIONS'].includes(req.method()))nonReads.push(req.method())};
 page.on('request',listener);
 try {
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('.sidebar .nav-item').filter({hasText:'資料來源'}).waitFor();
  const workspace=await page.evaluate(async()=>await (await fetch('/api/workspace',{credentials:'same-origin'})).json());
  if(workspace.projects.length!==280)throw new Error('Project count mismatch');
  const matched=workspace.projects.filter(p=>p.daily_reports.length);
  if(matched.length!==1||matched[0].daily_reports.length!==1)throw new Error('Expected one matched daily record');
  if(matched[0].daily_reports[0].match_basis!=='provisional_case_code')throw new Error('Missing provisional provenance');
  await page.locator('.sidebar .nav-item').filter({hasText:'資料來源'}).click();
  const filter=page.getByRole('combobox',{name:'篩選來源類型',exact:true});
  await filter.waitFor({timeout:30000});
  if(await page.locator('main table').first().locator('tbody tr').count()!==8)throw new Error('Source table count mismatch');
  await page.getByText('顯示前 100 筆，共 2446 筆符合資料',{exact:true}).waitFor();
  await filter.selectOption('daily');
  await page.getByText('顯示前 100 筆，共 535 筆符合資料',{exact:true}).waitFor();
  const links=await page.locator('a[aria-label^="開啟來源紀錄 "]').evaluateAll(items=>items.map(a=>({href:a.href,target:a.target,rel:a.rel})));
  if(links.length!==100)throw new Error('Expected 100 visible daily source links');
  if(links.some(a=>!/^https:\/\/yong-xiang-survey\.jp\.larksuite\.com\/base\/[^/?]+\?table=[^&]+&record=.+$/.test(a.href)||a.target!=='_blank'||!a.rel.includes('noopener')))throw new Error('Malformed source link');
  await page.evaluate(id=>{location.hash='view=project&project='+encodeURIComponent(id)+'&tab=daily'},matched[0].id);
  await page.getByRole('heading',{name:'日報作業紀錄',exact:true}).waitFor();
  await page.getByText('暫填工編 · 來源待核對',{exact:true}).waitFor();
  const originalHint=page.locator('small[title="以暫填案號精確配對；原表正式關聯尚未修復。"]');
  if(await originalHint.count()!==1)throw new Error('Original provisional code hint missing');
  if(!(await originalHint.textContent()).startsWith('原始案號：'))throw new Error('Original code label missing');
  if(nonReads.length)throw new Error('Unexpected non-read request');
  return {status:'pass',projects:280,source_tables:8,source_records:2446,daily_filter_records:535,visible_source_links:links.length,source_links:'correct base/table/record and safe new tab; none opened',matched_daily:1,provisional_badge:'visible',original_case_hint:'visible; formal relation unrepaired clearly stated',non_read_requests:0};
 }finally{page.off('request',listener)}
}