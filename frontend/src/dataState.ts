// Mirrors backend/data_state.py. Every read state renders separately; only
// partial and stale may coexist, unknown never renders as zero, and forbidden
// never exposes a name or count.
export const DATA_STATES=['loading','complete_empty','filtered_empty','unlocated','forbidden','read_failed','partial','stale','unknown'] as const;
export type DataStateName=typeof DATA_STATES[number];
// Forbidden is its own shape: count and name are `never`, so a forbidden value
// carrying either is a compile error rather than a leak waiting to render.
export type ForbiddenDataState={states:['forbidden'];count?:never;name?:never};
export type ReadableStateName=Exclude<DataStateName,'forbidden'>;
export type ReadableDataState={states:ReadableStateName[];count:number|null;name?:string};
export type DataState=ForbiddenDataState|ReadableDataState;

const COMBINABLE:ReadonlySet<DataStateName>=new Set(['partial','stale']);
const EMPTY:ReadonlySet<DataStateName>=new Set(['complete_empty','filtered_empty']);
const UNCOUNTED:ReadonlySet<DataStateName>=new Set(['loading','unlocated','read_failed','unknown']);
const unknown=():DataState=>({states:['unknown'],count:null});

export const DATA_STATE_LABELS:Record<DataStateName,string>={
 loading:'讀取中',
 complete_empty:'尚無資料',
 filtered_empty:'沒有符合篩選條件的資料',
 unlocated:'找不到資料來源',
 forbidden:'沒有權限',
 read_failed:'讀取失敗',
 partial:'部分資料',
 stale:'資料待更新',
 unknown:'狀態未知',
};

const isState=(value:unknown):value is DataStateName=>typeof value==='string'&&(DATA_STATES as readonly string[]).includes(value);
const isCount=(value:unknown):value is number=>typeof value==='number'&&Number.isInteger(value)&&value>=0;

// Anything malformed or contradictory reads as unknown rather than as a count.
export function parseDataState(value:unknown):DataState{
 if(!value||typeof value!=='object')return unknown();
 const {states,count,name}=value as {states?:unknown;count?:unknown;name?:unknown};
 if(!Array.isArray(states)||!states.length||!states.every(isState)||new Set(states).size!==states.length)return unknown();
 // Forbidden wins over anything sent alongside it, which is dropped unrendered.
 if(states.includes('forbidden'))return {states:['forbidden']};
 if(states.length>1&&!states.every(state=>COMBINABLE.has(state)))return unknown();
 const ordered=DATA_STATES.filter((state):state is ReadableStateName=>state!=='forbidden'&&states.includes(state));
 if(count!==null&&count!==undefined&&!isCount(count))return unknown();
 const known=isCount(count)?count:null;
 if(EMPTY.has(ordered[0])&&known!==null&&known!==0)return unknown();
 if(UNCOUNTED.has(ordered[0])&&known!==null)return unknown();
 const result={states:ordered,count:EMPTY.has(ordered[0])?0:known};
 return typeof name==='string'&&name?{...result,name}:result;
}

// Direct values can bypass the parser (casts, malformed input), so the helpers
// re-check: unreadable states read as unknown, forbidden suppresses everything.
const statesOf=(state:DataState):readonly DataStateName[]=>{
 const states=(state as {states?:unknown}|null|undefined)?.states;
 if(!Array.isArray(states)||!states.length||!states.every(isState))return ['unknown'];
 return states.includes('forbidden')?['forbidden']:states;
};
export const hasDataState=(state:DataState,name:DataStateName)=>statesOf(state).includes(name);

// null means "show no number": callers must not substitute 0.
export function dataStateCount(state:DataState):number|null{
 const states=statesOf(state);
 const count=(state as {count?:unknown}|null|undefined)?.count;
 if(states.includes('forbidden')||states.some(name=>UNCOUNTED.has(name)))return null;
 return isCount(count)?count:null;
}

export function describeDataState(state:DataState):string{
 const states=statesOf(state);
 const label=states.map(name=>DATA_STATE_LABELS[name]).join('・');
 const count=dataStateCount(state);
 return count===null||EMPTY.has(states[0])?label:`${label}（${count} 筆）`;
}
