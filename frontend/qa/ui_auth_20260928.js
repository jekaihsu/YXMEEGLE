async page=>{
 const origin='http://127.0.0.1:8793',checks={};await page.unrouteAll({behavior:'wait'});
 let w=await(await page.request.get(origin+'/api/workspace')).json(),s=await(await page.request.get(origin+'/api/session')).json();let workspaceRequests=0;
 await page.route('**/api/session',r=>r.fulfill({json:{user:null,users:[],mode:'lark',auth_configured:true,environment:'production'}}));
 await page.route('**/api/workspace',r=>{workspaceRequests++;return r.fulfill({json:w})});
 await page.goto(origin+'/?auth_error=unverified_directory#view=project&project=p1&tab=flow');await page.locator('.login-page').waitFor();
 checks.noWorkspaceWithoutLogin=workspaceRequests===0;checks.noPreviousCaseData=await page.locator('.project-title').count()===0;checks.callbackExplainsDirectory=await page.getByText('公司名冊尚未核實此帳號，請聯絡管理員核對。').isVisible();
 const href=await page.getByRole('link',{name:/Lark/}).getAttribute('href');checks.loginPreservesDeepLink=href.includes('next=')&&decodeURIComponent(href).includes('#view=project&project=p1&tab=flow');
 await page.screenshot({path:'output/playwright/company-login-20260928.png',fullPage:true});
 await page.unrouteAll({behavior:'wait'});await page.goto(origin+'/#view=project&project=p1&tab=flow');await page.locator('.project-title').waitFor();
 await page.route('**/api/session',r=>r.fulfill({status:401,json:{detail:'登入已失效'}}));await page.getByRole('button',{name:'重新整理資料',exact:true}).click();await page.locator('.login-page').waitFor();checks.expiryClearsCase=await page.locator('.project-title').count()===0;
 await page.unrouteAll({behavior:'wait'});await page.reload();await page.locator('.project-title').waitFor();
 w=await(await page.request.get(origin+'/api/workspace')).json();const old=JSON.parse(JSON.stringify(w)),latest=JSON.parse(JSON.stringify(w));latest.version=w.version+10;latest.projects[0].name='較新的已核實工作區';old.projects[0].name='過期回應不可覆寫';let reads=0;
 await page.route('**/api/workspace',async r=>{reads++;if(reads===1)return r.fulfill({json:latest});return r.fulfill({json:old})});
 await page.getByRole('button',{name:'重新整理資料',exact:true}).click();await page.getByRole('heading',{name:'較新的已核實工作區'}).waitFor();await page.getByRole('button',{name:'重新整理資料',exact:true}).click();await page.waitForTimeout(400);checks.olderWorkspaceDoesNotReplaceNewer=await page.getByRole('heading',{name:'較新的已核實工作區'}).isVisible();
 await page.unrouteAll({behavior:'wait'});await page.reload();
 const failed=Object.entries(checks).filter(([,v])=>!v);if(failed.length)throw Error(JSON.stringify({checks,failed}));return {fixtureOnly:true,checks};
}
