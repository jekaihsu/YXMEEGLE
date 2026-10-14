const chain = [['sales', '業務'], ['pm', 'PM'], ['confirmation', '確認單'], ['field', '外業'], ['control', '控制'], ['mapping', '圖資'], ['report', '報告'], ['pricing', '計價'], ['settlement', '結算']];
export function assignmentFixture() {
  const owners = [{open_id: 'ou_anna', name: '林安娜'}, {open_id: 'ou_wei', name: '陳威廷'}];
  const nodes = chain.map(([key, label], i) => ({key, label, status: i < 4 ? 'completed' : i === 4 ? 'in_progress' : 'not_started', derived_status: i < 4 ? 'completed' : i === 4 ? 'in_progress' : 'not_started',
    tasks: {done: i < 4 ? 3 : i === 4 ? 2 : 0, total: i < 5 ? i === 4 ? 5 : 3 : 0}, progress: i < 4 ? 100 : i === 4 ? 40 : 0,
    owners: i < 5 ? owners : [], assigned_by: owners[0], approver: null, approved_at: null, reject_reason: null, deadline: i === 4 ? '2026-10-20' : null, warnings: []}));
  const list = {code: 'ok', summary: {done: 4, total: 9, current_node: 'control'}, nodes: [...nodes].reverse(), stale: false,
    can: Object.fromEntries(chain.map(([key]) => [key, {claim: true, assign: true, complete: true, approve: true, reject: true, create_task: true}]))};
  const detail = {node: nodes[4], tasks: [{id: 'task_1', title: '控制點成果核對', detail: '核對現場紀錄與座標。', assignee: owners[1], assigned_by: owners[0], department: '測量部', deadline: '2026-10-20', status: 'in_progress', completed_at: null}],
    assignable_people: owners.map(p => ({...p, departments: ['測量部', '專案部']}))};
  return {list, detail};
}
export function projectFixture() {
  const user = {id: 'ou_anna', name: '林安娜', role: 'manager', department: '專案部', avatar: '', capabilities: []};
  const nodes = chain.map(([key, name], i) => ({id: `node_${key}`, key, name, status: i < 4 ? 'completed' : i === 4 ? 'in_progress' : 'pending', owner_id: user.id, collaborator_ids: [], tasks: [], start_date: null, due_date: null, original_due_date: null, started_at: null, completed_at: null}));
  const project = {id: 'p1', code: 'YX-2026-042', name: '南港基地測量與成果交付', client: '永祥工程顧問', pm_id: user.id, supervisor_id: user.id, status: 'in_progress', priority: 'normal', due_date: '2026-10-30', original_due_date: '2026-10-30', created_at: '2026-10-01', started_at: '2026-10-01', description: '節點指派 UI 示範', contract_amount: 300000, estimated_points: null, source_url: '', source_kind: 'demo', revision: 1, nodes, files: [], comments: [], daily_reports: [], evidence: [], sop_version: 1};
  return {project, user, workspace: {version: 1, as_of: '2026-10-14', workspace_id: 'node-assignment-review', environment: 'test', users: [user], projects: [project], approvals: [], events: [], calendar: {holidays: [], workdays: []}, source_status: {status: 'fresh', last_sync: '2026-10-14', message: ''}}};
}
