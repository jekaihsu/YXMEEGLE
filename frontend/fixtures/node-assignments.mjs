const chain = [['sales', '業務'], ['pm', 'PM'], ['confirmation', '確認單'], ['field', '外業'], ['control', '控制'], ['mapping', '圖資'], ['report', '報告'], ['pricing', '計價'], ['settlement', '結算']];
export function assignmentFixture() {
  const owners = [{open_id: 'ou_anna', name: '林安娜'}, {open_id: 'ou_wei', name: '陳威廷'}];
  const nodes = chain.map(([key, label], i) => ({key, label, departments: ['控制'], record_id: i < 5 ? `recNode${i}` : null, revision: i < 5 ? '3f2a9c0d1b7e4a55' : null, assignment_method: i < 5 ? '主管指派' : null, started_at: '2026-10-14T09:00:00+08:00', finished_at: null, status: i < 4 ? '已完成' : i === 4 ? '進行中' : '未開始', derived_status: i < 4 ? '已完成' : i === 4 ? '進行中' : '未開始',
    tasks: {done: i < 4 ? 3 : i === 4 ? 2 : 0, total: i < 5 ? i === 4 ? 5 : 3 : 0}, progress: i < 4 ? 1 : i === 4 ? 0.4 : 0,
    owners: i < 5 ? owners : [], assigned_by: owners[0], approver: null, approved_at: null, reject_reason: null, deadline: i === 4 ? '2026-10-20' : null, warnings: []}));
  const list = {code: 'A115001-01', summary: {done: 4, total: 9, current_node: 'control'}, nodes, stale: false, writes_enabled: true, writes_disabled_reason: null, roster: {available: true, stale: false}, warnings: [],
    can: Object.fromEntries(chain.map(([key]) => [key, {claim: true, assign: true, complete: true, approve: true, reject: true, create_task: true}]))};
  const detail = {...list, can: list.can.control, node: nodes[4], tasks: [{id: 'recTask1', revision: '9b0c1d2e3f405162', title: '控制點成果核對', detail: '核對現場紀錄與座標。', assignee: owners[1], assigned_by: owners[0], department: '測量部', deadline: '2026-10-20', status: '進行中', done_at: null, created_at: '2026-10-14T09:10:00+08:00', can: {edit_status: true, cancel: true, assign: true, claim: false, edit_details: true}}],
    assignable_people: owners.map(p => ({...p, departments: ['測量部', '專案部']}))};
  return {list, detail};
}
export function projectFixture() {
  const user = {id: 'ou_anna', name: '林安娜', role: 'manager', department: '專案部', avatar: '', capabilities: []};
  const nodes = chain.map(([key, name], i) => ({id: `node_${key}`, key, name, status: i < 4 ? 'completed' : i === 4 ? 'in_progress' : 'pending', owner_id: user.id, collaborator_ids: [], tasks: [], start_date: null, due_date: null, original_due_date: null, started_at: null, completed_at: null}));
  const project = {id: 'p1', code: 'YX-2026-042', name: '南港基地測量與成果交付', client: '永祥工程顧問', pm_id: user.id, supervisor_id: user.id, status: 'in_progress', priority: 'normal', due_date: '2026-10-30', original_due_date: '2026-10-30', created_at: '2026-10-01', started_at: '2026-10-01', description: '節點指派 UI 示範', contract_amount: 300000, estimated_points: null, source_url: '', source_kind: 'demo', revision: 1, nodes, files: [], comments: [], daily_reports: [], evidence: [], sop_version: 1};
  return {project, user, workspace: {version: 1, as_of: '2026-10-14', workspace_id: 'node-assignment-review', environment: 'test', users: [user], projects: [project], approvals: [], events: [], calendar: {holidays: [], workdays: []}, source_status: {status: 'fresh', last_sync: '2026-10-14', message: ''}}};
}

export function documentedAssignmentFixture() {
  const list = {
  "project_id": "p1",
  "code": "A115001-01",
  "summary": {
    "done": 1,
    "total": 8,
    "current_node": "confirmation"
  },
  "nodes": [
    {
      "key": "field",
      "label": "外業",
      "departments": [
        "外業",
        "水深A"
      ],
      "record_id": "rec...",
      "revision": "3f2a9c0d1b7e4a55",
      "status": "進行中",
      "derived_status": "進行中",
      "tasks": {
        "done": 1,
        "total": 3
      },
      "progress": 0.3333,
      "owners": [
        {
          "open_id": "ou_...",
          "name": "王外業"
        }
      ],
      "assignment_method": "主管指派",
      "assigned_by": {
        "open_id": "ou_...",
        "name": "林經理"
      },
      "approver": null,
      "approved_at": null,
      "reject_reason": null,
      "started_at": "2026-10-14T09:00:00+08:00",
      "finished_at": null,
      "deadline": "2026-10-20",
      "warnings": []
    }
  ],
  "can": {
    "field": {
      "claim": false,
      "assign": true,
      "complete": true,
      "approve": false,
      "reject": false,
      "create_task": true
    }
  },
  "warnings": [],
  "stale": false,
  "stale_reason": null,
  "fetched_at": "2026-10-14T09:00:05+08:00",
  "roster": {
    "available": true,
    "stale": false
  },
  "writes_enabled": true,
  "writes_disabled_reason": null
};
  const detail = {...list, node: list.nodes[0], can: list.can.field, ...{
  "tasks": [
    {
      "id": "rec...",
      "revision": "9b0c1d2e3f405162",
      "title": "控制點佈設",
      "detail": "北側 12 點",
      "assignee": {
        "open_id": "ou_...",
        "name": "陳水深"
      },
      "assigned_by": {
        "open_id": "ou_...",
        "name": "林經理"
      },
      "department": "水深B",
      "deadline": "2026-10-20",
      "status": "進行中",
      "done_at": null,
      "created_at": "2026-10-14T09:10:00+08:00",
      "can": {
        "edit_status": true,
        "cancel": false,
        "assign": false,
        "claim": false,
        "edit_details": false
      }
    }
  ],
  "assignable_people": [
    {
      "open_id": "ou_...",
      "name": "陳水深",
      "departments": [
        "水深B"
      ]
    }
  ]
}};
  return {list, detail};
}

export function embeddedAssignmentFixture() {
  const fixture = assignmentFixture();
  fixture.list.node_details = Object.fromEntries(fixture.list.nodes.map(n => [n.key, {tasks: n.key === 'control' ? fixture.detail.tasks : [], assignable_people: fixture.detail.assignable_people}]));
  return fixture;
}
export function visualAssignmentFixture() {
  const fixture = embeddedAssignmentFixture();
  for (const n of fixture.list.nodes) {
    const i = chain.findIndex(([key]) => key === n.key);
    n.status = n.derived_status = i < 3 ? '已完成' : i === 3 ? '進行中' : i === 4 ? '待審核' : '未開始';
    n.tasks = {done: i < 3 ? 3 : i === 3 ? 3 : i === 4 ? 5 : 0, total: i < 3 ? 3 : i < 5 ? 5 : 0};
    n.progress = n.tasks.total ? n.tasks.done / n.tasks.total : 0;
    n.deadline = i === 3 ? '2026-10-10' : i === 4 ? '2026-10-20' : null;
    n.warnings = i === 3 ? ['交付期限已過，請確認排程。'] : [];
  }
  fixture.list.summary = {done: 3, total: 9, current_node: 'field'};
  return fixture;
}
