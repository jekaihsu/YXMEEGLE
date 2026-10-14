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
