async page=>{
 const origin='http://127.0.0.1:8793';
 await page.unrouteAll({behavior:'wait'});
 await page.setViewportSize({width:1440,height:1000});await page.emulateMedia({reducedMotion:'reduce'});
 await page.goto(origin+'/#view=projects');await page.reload();await page.locator('.portfolio-page').waitFor();
 const response=await page.request.get(origin+'/api/workspace');const w=await response.json();const p=w.projects.find(p=>p.case_type!=='intake'),n=p.nodes.find(n=>n.key==='control')||p.nodes[0];
 const checks={};const expected=['案件概覽','流程與交付','日報紀錄','案件資料','操作紀錄'];
 await page.goto(origin+`/#view=project&project=${p.id}&node=${n.id}&tab=operations`);
 await page.locator('.flow-operations').waitFor();
 const tabs=page.getByRole('navigation',{name:'案件頁面'});
 checks.fivePages=JSON.stringify(await tabs.getByRole('button').allTextContents())===JSON.stringify(expected);
 checks.legacyOperations=await page.locator('.flow-operation-picker [aria-selected=true]').getAttribute('data-section')==='review';
 checks.operationsOutsideTaskBorder=await page.locator('.flow-operations').evaluate(el=>!el.closest('.node-section'));
 checks.noNestedEightTabs=await page.locator('.flow-operations .ops-tabs').count()===0;
 checks.desktopTabNoVerticalScroll=await tabs.evaluate(el=>el.scrollHeight<=el.clientHeight+1);
 await page.locator('.flow-operations').scrollIntoViewIfNeeded();
 await page.screenshot({path:'output/playwright/company-flow-review-viewport-20260928.png',animations:'disabled'});await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'output/playwright/company-flow-desktop-20260928.png',fullPage:true,animations:'disabled'});
 await page.getByRole('button',{name:'案件概覽',exact:true}).click();
 checks.singleQuoteEntry=await page.getByRole('button',{name:/^報價（\d+）$/}).count()===1;
 await page.getByRole('button',{name:/^報價（\d+）$/}).click();checks.quoteRoute=await tabs.getByRole('button',{name:'案件資料'}).getAttribute('aria-current')==='page';
 for(const key of ['files','family','basic','participants']){await page.goto(origin+`/#view=project&project=${p.id}&node=${n.id}&tab=${key}`);checks['legacy_'+key]=await tabs.getByRole('button',{name:'案件資料'}).getAttribute('aria-current')==='page'}
 await page.goto(origin+`/#view=project&project=${p.id}&node=${n.id}&tab=flow`);await page.locator('.flow-operations').waitFor();
 await page.locator('.flow-operation-picker [data-section=finance]').click();
 checks.noDirectAccounting=await page.getByText('財務資料僅供核對，不在工作台直接記帳、登錄收付款或核准帳務。重大財務確認依核定 Lark 流程辦理。').isVisible()&&await page.getByRole('button',{name:'核准款項'}).count()===0;
 await page.locator('.flow-operation-picker [data-section=review]').click();
 for(const width of [900,390]){
  await page.setViewportSize({width,height:900});await page.evaluate(()=>window.scrollTo(0,0));
  checks['noPageOverflow_'+width]=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
  checks['noTabVerticalScroll_'+width]=await tabs.evaluate(el=>el.scrollHeight<=el.clientHeight+1);
  await page.screenshot({path:`output/playwright/company-flow-${width}-20260928.png`,fullPage:true,animations:'disabled'});
 }
 await page.evaluate(()=>document.documentElement.style.fontSize='200%');
 await page.waitForTimeout(150);
 checks.zoom200NoOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
 checks.zoom200TabsNoScroll=await tabs.evaluate(el=>el.scrollHeight<=el.clientHeight+1);
 checks.zoom200TaskTitleReadable=await page.locator('.node-section .task-title>div').first().evaluate(el=>el.getBoundingClientRect().width>150);
 checks.zoom200TaskFitsCard=await page.locator('.node-section .task-table').evaluate(el=>el.getBoundingClientRect().width<innerWidth);
 await page.locator('.node-section .task-table').scrollIntoViewIfNeeded();await page.screenshot({path:'output/playwright/company-task-200percent-viewport-20260928.png',animations:'disabled'});await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'output/playwright/company-flow-200percent-20260928.png',fullPage:true,animations:'disabled'});
 await page.evaluate(()=>document.documentElement.style.fontSize='');await page.setViewportSize({width:1440,height:1000});
 await page.goto(origin+`/#view=project&project=${p.id}&node=${n.id}&tab=files`);await page.getByRole('button',{name:'上傳檔案',exact:true}).click();
 checks.fileCategories=await page.getByRole('combobox',{name:'檔案類別',exact:true}).locator('option').count()>=7;
 checks.filePurpose=await page.getByRole('combobox',{name:'用途',exact:true}).last().locator('option').allTextContents().then(x=>x.includes('交付佐證'));
 await page.keyboard.press('Escape');checks.fileDialogEsc=await page.getByRole('dialog').count()===0;
 await page.screenshot({path:'output/playwright/company-file-index-20260928.png',fullPage:true,animations:'disabled'});
 const failed=Object.entries(checks).filter(([,value])=>!value);if(failed.length)throw new Error(JSON.stringify({checks,failed}));return checks;
}
