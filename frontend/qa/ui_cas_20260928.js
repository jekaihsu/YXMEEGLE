async page=>{
 const origin='http://127.0.0.1:8793';await page.unrouteAll({behavior:'wait'});await page.context().clearCookies();await page.request.get(origin+'/api/session');
 const w=await(await page.request.get(origin+'/api/workspace')).json(),a=w.projects[0],b=w.projects[1];const request=(project,body,version=w.version)=>page.request.post(origin+'/api/actions',{data:{action:'comment_add',project_id:project.id,version,project_versions:{[project.id]:project.concurrency_version},request_id:'ui-'+Date.now()+'-'+Math.random(),payload:{body,mentions:[]}}});
 const first=await request(a,'隔離並行檢查：案件一');const unrelated=await request(b,'隔離並行檢查：案件二仍可儲存');const conflict=await request(a,'隔離並行檢查：舊版同案不應寫入');
 const after=await(await page.request.get(origin+'/api/workspace')).json();const checks={projectVersionAvailable:typeof a.concurrency_version==='number',first:first.ok(),otherProjectStaleWorkspaceAllowed:unrelated.ok(),sameProjectStaleRejected:conflict.status()===409,noRejectedComment:!after.projects[0].comments.some(c=>c.body==='隔離並行檢查：舊版同案不應寫入')};
 if(Object.values(checks).some(v=>!v))throw Error(JSON.stringify({checks,first:await first.json(),unrelated:await unrelated.json(),conflict:await conflict.json()}));return checks;
}
