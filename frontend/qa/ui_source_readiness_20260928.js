async page=>{
 const origin='http://127.0.0.1:8793';await page.unrouteAll({behavior:'wait'});const checks={};const w=await(await page.request.get(origin+'/api/workspace')).json();const p=w.projects.find(p=>p.id==='p1'),n=p.nodes.find(n=>n.key==='control');
 p.source_kind='v4';p.source_status='已結案';p.status='active';p.execution_status='in_progress';p.quotes=[];
 w.source_quotes=[{id:'base/table/quote',code:'115001',amount:120000,source_url:'https://example.com/quote',project_ids:[p.id],confirmation_ids:['base/table/c1','base/table/c2'],review_project_ids:[]}];
 w.source_confirmations=[{id:'base/table/c1',project_id:p.id,code:'C115001-01',quote_ids:['base/table/quote'],source_url:'https://example.com/confirmation'}];
 w.contract_items=[{id:'base/table/item',project_id:p.id,title:'跨組共用合約工項',amount_original:5000,amount_reported:5000,task_refs:n.tasks.slice(0,2).map(t=>({project_id:p.id,node_id:n.id,task_id:t.id})),source_url:'https://example.com/item'}];
 const summary=w.policy_summary.find(s=>s.project_id===p.id);summary.closure={status:'blocked',missing:['財務共同核准尚未完成'],financial:{incoming:{status:'unverified'},payables:{status:'unknown'}}};
 await page.route('**/api/workspace',r=>r.fulfill({json:w}));await page.goto(origin+'/#view=project&project=p1&tab=overview');await page.reload();await page.getByRole('button',{name:'報價（1）',exact:true}).waitFor();
 checks.sourceClosedSeparate=await page.locator('.project-source-status').getByText('已結案',{exact:true}).isVisible()&&await page.getByText('尚有結案條件待處理',{exact:true}).isVisible();
 checks.oneSourceQuote=await page.getByRole('button',{name:'報價（1）',exact:true}).count()===1;
 await page.getByRole('button',{name:'報價（1）',exact:true}).click();checks.quoteMultipleConfirmations=await page.getByText('關聯 2 份工程確認單').isVisible();checks.noUnsupportedQuoteReview=await page.getByText('確認此報價',{exact:true}).count()===0;
 await page.getByRole('combobox',{name:'案件資料分類'}).selectOption('contracts');checks.singleContractAmount=await page.getByText('來源金額：5,000 · 申報金額：5,000').count()===1;checks.taskLinks=await page.locator('.source-contract-index li a').count()===2;
 await page.locator('.source-contract-index li a').first().click();await page.getByRole('dialog').waitFor();checks.taskDeepLink=await page.getByRole('dialog').isVisible();await page.keyboard.press('Escape');
 await page.goto(origin+'/#view=project&project=p1&tab=overview');await page.setViewportSize({width:390,height:900});checks.mobileNoOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);await page.screenshot({path:'output/playwright/company-source-readiness-mobile-20260928.png',fullPage:true});
 await page.unrouteAll({behavior:'wait'});await page.setViewportSize({width:1440,height:1000});await page.reload();const failed=Object.entries(checks).filter(([,v])=>!v);if(failed.length)throw Error(JSON.stringify({checks,failed}));return {fixtureOnly:true,checks};
}
