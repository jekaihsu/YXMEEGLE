async page=>{
 const origin='http://127.0.0.1:8794';await page.unrouteAll({behavior:'wait'});await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>document.documentElement.style.fontSize='');const checks={};const w=await(await page.request.get(origin+'/api/workspace')).json();const user=w.users.find(u=>u.role==='manager');let mode='lark';w.environment='production';
 w.attendance_schedule_status={status:'pending_schedule',last_success_at:null,last_attempt_at:'2026-09-28T10:00:00+08:00',ready_count:1,manual_override_count:0,issues:[{user_id:user.id,reason:'employee_identity_unverified'}]};
 w.work_schedules=[{id:'fixture-night',user_id:user.id,day:'2026-09-28',end_time:'02:00',normal_off_at:'2026-09-29T02:00:00+08:00',off_day_offset:1,basis:'attendance_schedule',status:'ready',active:true}];
 await page.route('**/api/session',r=>r.fulfill({json:{user,users:w.users,mode,environment:w.environment,workspace_id:w.workspace_id,auth_configured:true}}));await page.route('**/api/workspace',r=>r.fulfill({json:w}));let posted;await page.route('**/api/attendance/sync',r=>{posted=r.request().postDataJSON();return r.fulfill({json:{status:'pending_schedule'}})});
 await page.goto(origin+'/#view=admin&tab=settings');await page.reload();await page.getByRole('heading',{name:'正常下班班表',exact:true}).waitFor();
 checks.pendingIdentityExplained=await page.getByText(/尚未核實 Attendance 員工識別/).isVisible();checks.noFalseSuccessfulSync=await page.getByText('最近成功：尚無 · 最近嘗試：2026-09-28T10:00:00+08:00').isVisible();checks.crossMidnightDate=await page.getByText('2026-09-29 02:00:00+08:00',{exact:false}).isVisible();checks.crossDayLabel=await page.getByText('跨日 +1 天').isVisible();checks.attendanceNotManual=await page.getByText('Attendance 正常班表 · 已啟用').isVisible();
 await page.getByRole('button',{name:'同步正常班表',exact:true}).click();await page.getByText('已查回同步結果，仍有條件待核對。').waitFor();checks.explicitReadSyncDates=!!posted?.date_from&&!!posted?.date_to;
 await page.getByRole('heading',{name:'正常下班班表',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:'output/playwright/independent-attendance-status-20260928.png'});
 mode='demo';w.environment='demo';await page.reload();await page.getByRole('heading',{name:'正常下班班表',exact:true}).waitFor();checks.noFormalSyncInDemo=await page.getByRole('button',{name:'同步正常班表',exact:true}).count()===0;
 await page.unrouteAll({behavior:'wait'});await page.reload();const failed=Object.entries(checks).filter(([,v])=>!v);if(failed.length)throw Error(JSON.stringify({checks,failed}));return {fixtureOnly:true,checks};
}

