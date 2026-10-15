# Reports API contract（後端與前端共同遵守）

所有端點 `GET`、唯讀、需登入、`Cache-Control: no-store`。回應皆含 `meta`。週以 Asia/Taipei 週一為起點，`week` 為該週週一 `YYYY-MM-DD`，預設為最近一個已結束的完整週。錯誤沿用 repo 慣例 `{detail: string}`。

```ts
type Meta = {
  fetched_at: string;            // ISO，快照讀取時間
  stale: boolean;                // 已過 TTL，背景刷新中
  snapshot: string;              // 快照版本（內容指紋前 12 碼）
  gaps: Gap[];                   // 此報表相關的資料缺口
};
type Gap = {id: string; severity: 'info'|'warn'; message: string}; // 例：內業工作單檢核狀態僅 31/1233 有值

type Kpi = {total: number; passed: number; returned: number; pending: number; unset: number;
            error_rate: number|null;     // returned / (passed + returned)，分母 0 時 null
            pending_rate: number|null;   // pending / total
            coverage: number|null};      // (passed + returned) / total
```

## GET /api/reports/review
Query：`dept=field|office|control`（預設 field）、`week`、`weeks=12`、`group`、`person`。
```ts
{meta: Meta; dept: string; week: string;
 kpi: Kpi; kpi_prev: Kpi;                                   // 本週與前一週
 trend: {week: string; total: number; passed: number; returned: number; error_rate: number|null}[];   // 近 weeks 週，舊到新
 by_group: ({group: string} & Kpi)[];                       // 依 error_rate 降冪，null 在後
 by_person: ({person: string; group: string} & Kpi)[];
 by_item: {item: string; total: number; passed: number; returned: number; error_rate: number|null}[];  // 取前 15
 flags: {flag: string; count: number; share: number}[];     // office：⚠案件不符等；field：違反檢核程序
 control: {checked: number; unchecked: number; violated: number}  // 控制組檢核勾選／未勾／是否有檢核程序=否
}
```
## GET /api/reports/review/rows
Query：同上加 `status=passed|returned|pending|unset`、`flag`、`q`、`sort=date|group|person|case|points|status`、`order=asc|desc`、`offset=0`、`limit=50`（最大 200）。
```ts
{meta: Meta; total: number; offset: number; limit: number;
 items: {id: string; no: string; date: string; group: string; person: string; case_code: string; item: string;
         points: number|null; status: 'passed'|'returned'|'pending'|'unset'; control_checked: boolean|null;
         note: string; flags: string[]; link: string}[]}  // link 為 Lark 紀錄網址
```
## GET /api/reports/sales
Query：`status`、`pm`、`sort`、`order`、`offset`、`limit`。回 `{meta, kpi:{cases,contract_total,billed_total|null,received_total|null,unbilled_billable|null,receivable|null}（請款／入帳公式欄在 v3 全空時回 null 並在 meta.gaps 說明，不可回 0）, by_status:{status,count,contract_total}[], by_pm:{pm,count,contract_total,progress}[], items:{code,name,client,pm,status,contract,progress_revenue,progress_cost,progress_billing,billable_unbilled,receivable,link}[], total, offset, limit}`。`status` 空值以「未填」顯示，不丟棄。`status=未填` 篩選空白狀態。
## GET /api/reports/assets
Query：`kind=vehicle|instrument`、`from`、`to`（預設近 30 天）、`status`、`category`、`owner`（車輛備註分類）、`idle_days`、`q`、`sort`、`order`、`offset`、`limit`。
```ts
{meta: Meta; kind: string; from: string; to: string;
 kpi: {total: number; active: number; in_use: number; idle: number; repair: number; km: number|null; daily_rent_total: number|null};
 by_category: {category: string; total: number; in_use: number; repair: number}[];
 usage_trend: {week: string; uses: number}[];
 items: {id: string; name: string; category: string; status: string; owner: '自有'|'租賃'|'待確認'|''; uses: number; km: number|null;
         last_used: string|null; idle_days: number|null; daily_rent: number|null; note: string; link: string}[];
 total: number; offset: number; limit: number}
```
車輛／儀器的 uses、km、last_used 由「車輛」「儀器費率」的連結欄（第一／二／三台車紀錄、使用此儀器的成本單，內含外業成本單 record_ids）反查外業成本單的工作日期與 出發／結束里程 得出，不是由外業成本單的選項欄。車輛：uses 與 km 來自外業成本單 第一／二／三台車與對應里程；儀器：uses 來自外業成本單 使用儀器；預排次數來自工作預排 車輛／儀器。無法由資料推得者回 null，並在 `meta.gaps` 說明（TAF、自校驗、月租檢查）。
## GET /api/reports/progress
Query：`dept=field|office`、`week`、`group`、`scope=week|open`（預設 week；open 另納入全部執行中案件供剩餘點數統計）、`sort`、`order`、`offset`、`limit`。預排達成率依工程編號。
```ts
{meta: Meta; dept: string; week: string;
 basis: 'days'|'points';   // 工作預排.預估營業額點數 全空時為 'days'：預排出工天數 vs 實際出工天數
 kpi: {planned_points: number|null; actual_points: number; planned_days: number; actual_days: number; achievement: number|null; open_cases: number; remaining_points: number|null};
 by_group: {group: string; planned: number; actual: number; achievement: number|null}[];
 items: {case_code: string; case_name: string; planned: number; actual: number; planned_days: number; actual_days: number; achievement: number|null; diff: number;
         expected_total: number|null; done_total: number|null; remaining: number|null; status: string; link: string}[];
 total: number; offset: number; limit: number}
```
## GET /api/reports/sources
```ts
{meta: Meta; base: {name: string; token: string; url: string};
 tables: {name: string; table_id: string; kind: string; rows: number; used_fields: string[]; status: 'ok'|'error'|'never'; fetched_at: string|null; used_by: string[]}[]}
```
## POST /api/reports/refresh
唯讀來源的手動重新讀取。需與 `/api/live/refresh` 相同的授權，單飛，限制每分鐘一次。回 `{meta}`，進行中時 202。

## 顯示與查詢約定

- `meta.gaps` 依端點與部門限制範圍。控制組使用外業提醒。來源頁保留跨表提醒。畫面以預設收合的「資料品質提醒 N 項」呈現，更新時間與過期標記持續可見。
- 檢核失誤率分母為 `passed + returned`。KPI、排行、趨勢提示顯示已檢核筆數，1 至 19 筆標示「樣本少」。零分母仍為「無法計算」。
- 前端依端點、完整查詢條件與登入工作階段快取成功結果 60 秒。離開或切換條件取消舊請求。
- 天數模式的明細與 KPI 使用 `planned_days`、`actual_days`，差異為實際天數減預排天數。點數欄仍保留原值。
