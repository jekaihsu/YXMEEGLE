async page=>{
 const origin=await page.evaluate(()=>location.origin);await page.unrouteAll({behavior:'wait'});
 const w=await(await page.request.get(origin+'/api/workspace')).json(),p=w.projects.find(p=>p.id==='p1'),n=p.nodes.find(n=>n.key==='settlement');
 w.environment='production';const item={id:'review-terminal-fixture',project_id:p.id,node_id:n.id,status:'rejected',reason:'獨立複審終態資料',native_receipt:{approved:true,binding_verified:true,simulated:false},native_binding:{status:'prepared'}};w.financial_requests=[item];
 await page.route('**/api/session',r=>r.fulfill({json:{user:w.users.find(u=>u.id===p.pm_id),users:w.users,mode:'lark',environment:'production',workspace_id:w.workspace_id,auth_configured:true}}));await page.route('**/api/workspace',r=>r.fulfill({json:w}));
 const checks={};
 for(const [status,label] of Object.entries({rejected:'Lark 已拒絕此申請，不能套用。',withdrawn:'Lark 申請已撤回，不能套用。',invalidated:'核准內容或範圍已失效，需重新核對。',canceled:'Lark 申請已取消，不能套用。'})){
  item.status=status;await page.goto(origin+`/#view=project&project=p1&node=${n.id}&tab=approvals`);await page.reload();await page.getByRole('heading',{name:'重大財務確認',exact:true}).waitFor();
  checks[status+'Label']=await page.locator('.native-approval-controls').getByText(label,{exact:true}).isVisible();
  checks[status+'NoFinalize']=await page.getByRole('button',{name:'核實條件並完成財務節點'}).count()===0;
  checks[status+'NoSubmit']=await page.getByRole('button',{name:'送出至 Lark',exact:true}).count()===0;
 }
 await page.unrouteAll({behavior:'wait'});await page.reload();return {fixtureOnly:true,checks,failed:Object.entries(checks).filter(([,v])=>!v)};
}
