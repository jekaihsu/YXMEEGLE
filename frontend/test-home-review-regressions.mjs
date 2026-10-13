// Render actual full/shell API payloads for the independent Home review findings.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import Module from 'node:module';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';

const py=String.raw`
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from pytest import MonkeyPatch
from backend.test_home_executable_tasks import home_client, shape, task, VIEWER, OTHER
from backend import workflow
mp=MonkeyPatch()
mp.setattr(workflow, 'now', lambda:'2026-10-13T09:00:00+08:00')
def mutate(s):
    shape(s)
    paused,live=s['projects'][:2]
    paused['nodes'][0]['tasks'] += [task('extra-paused-'+str(i), VIEWER, '2026-09-30') for i in range(3)]
    paused['nodes'][0]['tasks'][0]['original_due_date']=None
    sales=live['nodes'][0]
    next(t for t in sales['tasks'] if t['id']=='lv-other').update(input_task_ids=['missing-proxy-upstream'],source_batch_id='SOURCE-BATCH-42')
    sales['tasks'].append(dict(task('lv-prereq', VIEWER, '2026-10-20'), input_task_ids=['lv-other']))
    sales['tasks'].append(task('lv-correction', VIEWER, '2026-10-20', 'rework'))
    s['events'].append(dict(id='return-event',action='task_return',project_id=live['id'],node_id=sales['id'],task_id='lv-correction',created_at='2026-10-06T09:00:00+08:00',message='須補測量成果'))
    field=next(n for n in live['nodes'] if n['key']=='field')
    field['tasks']=[dict(task('contact-before-permit', VIEWER, '2026-10-01'), sop_rule_id='dispatch_date_contact')]
    d=dict(project_id=live['id'],principal_id=OTHER,delegate_id=VIEWER,seat='owner',scope='tasks',task_ids=['lv-other'],status='active',qualified=True,qualification_evidence='synthetic',source='supervisor')
    s['delegations']=[dict(d,id='expired',start_date='2026-08-01',end_date='2026-08-31',qualification_note='EXPIRED BASIS'),dict(d,id='current',start_date='2026-10-01',end_date='2026-10-31',qualification_note='CURRENT BASIS')]
with TemporaryDirectory() as tmp:
    with home_client(Path(tmp), mp, mutate) as client:
        print(json.dumps({'full':client.get('/api/workspace').json(),'shell':client.get('/api/workspace?scope=shell').json(),'viewer':VIEWER},ensure_ascii=False))
`;
const python=process.env.HOME_REVIEW_PYTHON||'/Users/vc/Local/run/yxs3-demo/venv/bin/python';
const generated=spawnSync(python,['-c',py],{cwd:'..',encoding:'utf8',maxBuffer:16*1024*1024});
assert.equal(generated.status,0,generated.stderr||generated.error?.message);
const {full,shell,viewer}=JSON.parse(generated.stdout);
assert.equal(full.as_of,shell.as_of,'API payloads measure the same data date');
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dashboard'});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const output=await build({stdin:{contents:"export {Dashboard,ShellDashboard} from './src/DailyHome';export {homeOverdueCount} from './src/executableTasks';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundled=new Module(process.cwd()+'/.home-review-bundle.cjs');bundled.filename=process.cwd()+'/.home-review-bundle.cjs';bundled.paths=Module._nodeModulePaths(process.cwd());bundled._compile(output.outputFiles[0].text,bundled.filename);
const {Dashboard,ShellDashboard,homeOverdueCount}=bundled.exports;
const user=full.users.find(u=>u.id===viewer);const routes=[];
const context=w=>({w,s:{user,users:w.users,mode:'demo'},route:{view:'dashboard'},go:route=>routes.push(route),run:async()=>undefined,reloadVersion:0,busy:false});
let root;
const render=async(Component,w)=>{if(root)await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(Component,{c:context(w)})))};
const waitingSection=kind=>[...document.querySelectorAll('.dh-waiting')].find(section=>section.textContent.includes(kind));
const rowByTitle=title=>[...document.querySelectorAll('.dh-waiting .ds-row')].find(row=>row.querySelector('.ds-row-main > span')?.textContent===title);
const pausedRow=()=>[...waitingSection('暫停中的指派').querySelectorAll('.ds-row')].find(row=>row.textContent.includes('pz-late1'));
const attention=()=>document.querySelector('.work-inbox');
const fullContact=full.projects.flatMap(p=>p.nodes.flatMap(n=>n.tasks)).find(t=>t.id==='contact-before-permit');
assert.equal(fullContact.home_detail.actionable,true,'API says permit-exempt field contact is actionable');
assert.deepEqual(fullContact.execution_blockers,[],'contact has no canonical execution blockers');
await render(Dashboard,full);
const fullCount=attention().querySelector('.heading-count').textContent;
assert.ok(attention().textContent.includes('contact-before-permit'),'R1 full Home shows actionable field contact');
assert.ok(!waitingSection('等待前置條件')?.textContent.includes('contact-before-permit'),'R1 contact is not misclassified as permit-blocked');
assert.equal(homeOverdueCount(full,viewer),shell.counts.my_overdue_tasks,'R1 full badge matches shell canonical count');
assert.equal(fullCount,String(shell.counts.my_overdue_tasks+shell.counts.due_today_tasks+shell.counts.approvals_pending),'R1 full attention matches shell count');
const fullProxy=rowByTitle('lv-other');
assert.ok(fullProxy?.textContent.includes('2026-10-01 至 2026-10-31')&&fullProxy.textContent.includes('主管核定代理'),'R2 full Home uses the verified current proxy');
assert.ok(!fullProxy.textContent.includes('EXPIRED BASIS')&&!fullProxy.textContent.includes('2026-08-01'),'R2 expired raw delegation is never rendered');
assert.ok(fullProxy.textContent.includes('作業條件')&&fullProxy.textContent.includes('指定前置成果尚未交付'),'R5 proxy blocker remains visible despite proxy grouping');
const fullPaused=waitingSection('暫停中的指派');assert.equal(fullPaused.querySelector('.heading-count').textContent,'6');
assert.equal([...fullPaused.querySelectorAll('.ds-row')].filter(row=>row.textContent.includes('pz-')||row.textContent.includes('extra-paused')).length,5,'R3 preview is capped at five');
assert.ok(fullPaused.textContent.includes('查看全部指派工作'),'R3 sixth paused assignment has a reachable overflow link');
assert.ok(pausedRow().textContent.includes('現行期限 2026/10/01'),'R4 paused due-only task retains current deadline');
assert.ok(pausedRow().textContent.includes('逾期')&&pausedRow().textContent.includes('工作日'),'R4 paused row explains overdue workday risk');
assert.ok(pausedRow().textContent.includes('預估期限未提供')&&pausedRow().textContent.includes('暫停計時規則待核定'),'R4 unknown forecast and pause clock remain explicit');
await act(async()=>[...fullPaused.querySelectorAll('button')].find(button=>button.textContent.includes('查看全部指派工作')).click());
assert.equal(routes.at(-1).view,'work','R3 overflow opens all assigned work');
const prereq=rowByTitle('lv-prereq');
assert.ok(prereq?.textContent.includes('lv-other')&&prereq.textContent.includes('員工021')&&prereq.textContent.includes('來源批次 SOURCE-BATCH-42'),'R5 prerequisite shows exact upstream task, owner and source batch');
assert.ok(prereq.textContent.includes('本任務可核對的交付批次關聯未提供'),'R5 missing delivery batch link is explicit');
const correction=rowByTitle('lv-correction');
assert.ok(correction?.textContent.includes('須補測量成果')&&correction.textContent.includes('修正範圍待核對'),'R5 correction uses recorded reason and labels unknown scope');
await render(ShellDashboard,shell);
assert.equal(attention().querySelector('.heading-count').textContent,fullCount,'R1 full and shell attention counts match');
assert.ok(attention().textContent.includes('contact-before-permit'),'R1 shell attention contains the same field contact');
const shellProxy=rowByTitle('lv-other');
assert.ok(shellProxy?.textContent.includes('2026-10-01 至 2026-10-31')&&!shellProxy.textContent.includes('EXPIRED BASIS'),'R2 shell uses the current proxy basis');
assert.ok(shellProxy.textContent.includes('作業條件')&&shellProxy.textContent.includes('指定前置成果尚未交付'),'R5 shell proxy blocker remains visible');
assert.ok(waitingSection('暫停中的指派').textContent.includes('查看全部指派工作'),'R3 shell overflow link matches full');
assert.ok(pausedRow().textContent.includes('現行期限 2026/10/01'),'R4 shell paused risk matches full');
assert.ok(document.querySelector('.dh-personal-queue').textContent.includes('載入待我確認／我交辦事項'),'R5 shell personal queues are explicitly on demand');
// The verified queue contract is rendered read-only, with exact navigation targets and unavailable evidence visible.
const queued={...full,home_queues:{awaiting_confirmation:[{id:'review-1',title:'待核實覆核',reason:'目前覆核席位輪到你',project_id:'p002',node_id:'n2',kind:'node_review',tab:'flow'}],delegated_by_me:[{id:'handover-1',title:'已發出的交接',reason:'對方尚未確認',project_id:'p002',kind:'handover_outgoing',tab:'flow'}],unavailable:[{id:'missing-audit',title:'交辦紀錄待核對',reason:'缺少 assignment_history.actor_id',project_id:null,kind:'assignment_audit_unavailable',tab:null}]}};
await render(Dashboard,queued);
for(const title of ['待我確認','我交辦的事項','資料待核對'])assert.ok([...document.querySelectorAll('.dh-personal-queue h2')].some(h=>h.textContent.includes(title)),`R5 ${title} queue renders`);
assert.ok(document.querySelector('.dh-personal-queue').textContent.includes('待核實覆核'),'R5 verified confirmation is visible');
assert.ok(document.querySelectorAll('.dh-personal-queue button').length>=2,'R5 verified records navigate without action buttons');
assert.ok([...document.querySelectorAll('.dh-personal-queue')].some(section=>section.textContent.includes('assignment_history.actor_id')),'R5 unavailable source evidence is explicit');
await render(ShellDashboard,shell);
assert.ok(!document.querySelector('.dh-personal-queue').textContent.includes('目前沒有已核實的事項'),'R5 shell does not claim an empty queue before loading');
globalThis.fetch=async url=>{assert.equal(url,'/api/workspace');return new Response(JSON.stringify(queued),{status:200,headers:{'Content-Type':'application/json'}})};
await act(async()=>document.querySelector('.dh-personal-queue button').click());
await act(async()=>new Promise(resolve=>setTimeout(resolve,20)));
assert.ok([...document.querySelectorAll('.dh-personal-queue')].some(section=>section.textContent.includes('待核實覆核')),'R5 shell loads verified queues on request');
await act(async()=>root.unmount());dom.window.close();
console.log('Home review regressions R1-R5 rendered API checks passed');
