// Pure wording/draft contract for the synthetic vertical flow: no live-sync claim, mapping labelled unconfirmed, editing resets operation identity.
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const code=(await build({entryPoints:['src/opsFlowView.ts'],bundle:true,write:false,format:'esm',platform:'node'})).outputFiles[0].text;
const V=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const text=[V.MAPPING_BADGE,V.MOCK_DECISION_NOTE,V.DEADLINE_LABEL,V.SEAT_LABEL.case,V.SEAT_LABEL.node,...Object.values(V.PROPOSAL_STATE),...Object.values(V.ELIGIBILITY)].join('\n');
assert.doesNotMatch(text,/已同步|同步成功|儲存成功|已寫入 Lark/);
assert.match(V.MAPPING_BADGE,/未確認/);assert.match(V.MOCK_DECISION_NOTE,/mock/);assert.match(V.MOCK_DECISION_NOTE,/不會產生真實 Lark 核准/);
assert.match(V.SEAT_LABEL.case,/不由案件 PM／案件負責人標籤推得/);assert.match(V.SEAT_LABEL.node,/未確認/);assert.match(V.DEADLINE_LABEL,/非合約結束日/);
assert.notEqual(V.PROPOSAL_STATE.waiting_approval,V.PROPOSAL_STATE.confirmed);
// operation identity: stable across retries of the same draft, fresh after any edit
let n=0;const uuid=()=>'id'+(++n),now=()=>'t'+n;
const d1=V.withIdentity(V.emptyDraft(),uuid,now);assert.equal(d1.cid,'id1');
assert.equal(V.withIdentity(d1,uuid,now).cid,'id1');
const d2=V.edited(d1,{date:'2026-10-20'});assert.equal(d2.cid,null);assert.equal(V.withIdentity(d2,uuid,now).cid,'id2');
assert.equal(V.deliverySentence(undefined,{}),'尚未產生派送');
console.log('ops-flow view: ok');
