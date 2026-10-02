async (page) => {
 const methods=[];
 const listen=request=>{if(!['GET','HEAD','OPTIONS'].includes(request.method())) methods.push(request.method());};
 page.on('request',listen);
 try {
  const w=await page.evaluate(async()=>{const r=await fetch('/api/workspace');if(!r.ok)throw new Error(`Workspace read failed: ${r.status}`);return r.json();});
  const ids=w.projects.map(p=>p.id);
  if(new Set(ids).size!==ids.length)throw new Error('Duplicate internal project IDs');
  const formal=w.projects.filter(p=>p.case_type!=='intake');
  const intake=w.projects.filter(p=>p.case_type==='intake');
  const businessKeys=formal.filter(p=>p.case_type==='formal').map(p=>`${p.company_id||p.tenant_id||''}:${p.code}`);
  if(new Set(businessKeys).size!==businessKeys.length)throw new Error('Duplicate formal case identity');
  const quoteIds=w.projects.flatMap(p=>(p.quotes||[]).map(q=>q.id));
  if(new Set(quoteIds).size!==quoteIds.length)throw new Error('Quote source appears in multiple cases');
  await page.getByRole('button',{name:'案件總覽',exact:true}).first().click();
  await page.getByRole('heading',{name:'案件總覽',exact:true}).waitFor();
  await page.getByRole('button',{name:/^全部紀錄/}).click();
  if(await page.locator('.projects-table tbody tr').count()!==ids.length)throw new Error('Project UI differs from workspace');
  await page.getByRole('button',{name:/^正式案件/}).click();
  if(await page.locator('.projects-table tbody tr').count()!==formal.length)throw new Error('Formal count mismatch');
  await page.getByRole('button',{name:/^待確認接案/}).click();
  if(await page.locator('.projects-table tbody tr').count()!==intake.length)throw new Error('Intake count mismatch');
  const example=w.projects.find(p=>(p.quotes||[]).length>1);
  if(example){
   await page.evaluate(id=>{location.hash=new URLSearchParams({view:'project',project:id,tab:'quotes'}).toString();},example.id);
   await page.getByRole('heading',{name:'本案報價',exact:true}).waitFor();
   if(await page.locator('.operations table tbody tr').count()!==example.quotes.length)throw new Error('Quote count mismatch');
  }
  await page.getByRole('button',{name:'教育訓練與能力',exact:true}).click();
  await page.getByRole('heading',{name:'教育訓練與能力',exact:true}).waitFor();
  await page.getByRole('button',{name:'能力地圖',exact:true}).click();
  await page.getByRole('heading',{name:'來源能力目錄',exact:true}).waitFor();
  if(methods.length)throw new Error('Readonly acceptance issued mutations');
  return {projects:ids.length,formal_cases:formal.length,intake_records:intake.length,quote_sources:quoteIds.length,multiple_quote_case_checked:example?.id||null,capability_catalog:(w.capability_catalog||[]).length,non_read_requests:0};
 } finally {page.off('request',listen);}
}
