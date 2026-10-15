# Reports API contract（後端與前端共同遵守）

所有端點 `GET`、唯讀、需登入、`Cache-Control: no-store`。成功回應皆含 `meta`。週以 Asia/Taipei 週一為起點，`week` 為該週週一 `YYYY-MM-DD`，預設為最近一個已結束的完整週。錯誤沿用 repo 慣例 `{detail: string}`。

## 首次讀取與失敗回應

啟動時，僅在 `REPORTS_ENABLED=true`、reader 為 `LarkReader` 且有 `LARK_APP_ID` 與 `LARK_APP_SECRET` 時背景建立首份快照。啟動不等待來源讀取，失敗不阻止 app 啟動。FixtureReader 不預熱。

無快照時，每個請求最多等待 `REPORTS_COLD_WAIT_SECONDS`，預設 20 秒，上限 60 秒。逾時且背景仍在讀取時回 HTTP 503，標頭含 `Retry-After: 5` 與 `Cache-Control: no-store`。

```json
{"detail":"報表資料正在首次讀取，請稍候","warming":true,"retry_after":5}
```

來源讀取失敗且無快照時回 HTTP 503，仍含 `Cache-Control: no-store`。

```json
{"detail":"報表來源暫時無法讀取","warming":false}
```

前端只對 `503 warming=true` 自動重試。等待時顯示骨架及「正在首次讀取 Lark 資料，約需 15 到 30 秒」。每次回應後依 `retry_after` 秒數排下一次請求，同一 hook 最多 12 次請求，含首次請求。卸載、參數變更或 session epoch 變更後不再送舊請求。達上限或非預熱失敗時顯示錯誤及「重試」。手動刷新每 60 秒一次的限制不變。

```ts
type Meta = {
  fetched_at: string;            // ISO，快照讀取時間
  stale: boolean;                // 已過 TTL 或最近刷新失敗
  refresh_error: boolean;        // 最近一次刷新失敗，顯示「更新失敗，顯示舊資料」
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
 by_person: ({person: string; person_key: string; group: string} & Kpi)[];
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
 kpi: {planned_points: number|null; actual_points: number; planned_days: number; actual_days: number; matched_days: number; unplanned_days: number; achievement: number|null; open_cases: number; remaining_points: number|null};
 by_group: {group: string; group_label: string; planned_days: number; matched_days: number; unplanned_days: number; planned: number; actual: number; achievement: number|null}[];
 items: {case_code: string; case_name: string; planned: number; actual: number; planned_days: number; actual_days: number; matched_days: number; unplanned_days: number; achievement: number|null; diff: number;
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
- 天數模式的明細與 KPI 顯示預排 `planned_days`、對應 `matched_days`、未預排 `unplanned_days`；`actual_days` 保留全部出工天數，差異為實際天數減預排天數。點數欄仍保留原值。

## 2026-10-15 獨立審查修正的加法欄位與計算規則

所有 GET 端點僅接受各自 Query 清單中的欄位。`sources` 不接受查詢欄位。未知欄位回 422 `{detail: string}`。文字 trim，最長 240 字元，數值與日期由邊界正規化後組成快取 key。結果快取最多 512 筆，使用 LRU，併發同鍵 miss 只計算一次。靜態資料缺口在快照建立時按端點、部門計算一次。日期區間覆蓋率與負剩餘筆數由當次篩選結果計算。

- 組別共用 `normalize_group`。先 trim，再去除尾端「組」，已知別名「控制組」對應「控制」。`group` filter 接受原始名稱與正規化名稱。工作單保留 `group_label`，進度組別回 `group_label` 作顯示標籤。無對應組別列入資料缺口。
- 預排的開始與結束日期皆含當日，依台北日曆展開後裁切報告週。結束早於開始時只算開始當日並提示筆數。排除休假與 C000000。一列多案件各自取得日期。總計以 `(case, date)` 去重，組別表在各組內去重。
- days 達成率為 `matched_days / planned_days`。`matched_days` 是實際出工與預排 `(case, date)` 的交集。`actual_days` 保留全部出工天數，`unplanned_days` 為實際減交集，在 KPI 與明細回傳；組別表另回各組的 `unplanned_days`。points 達成率也排除未預排日期上的實際點數。
- `diff` 的 days 基準為 `actual_days - planned_days`，points 基準為 `actual - planned`。伺服器排序與畫面均使用 `diff`。
- 個案 `remaining` 保留負值。進行中案件的 KPI 僅加總非負且有值者，沒有可加總值回 null，並提示排除筆數。
- sales 的所有 `contract_total`，包括 `by_status` 與 `by_pm`，全缺值回 null。實際合約為 0 且預期合約為正時使用預期合約，並提示筆數。單案超過正合約總額 50% 或正合約中位數 100 倍時提示筆數與案件編號。`by_pm.progress` 以有進度且正合約的案件加權，沒有可用權重回 null。金額缺值顯示「來源無資料」。
- assets KPI 加 `coverage: number|null` 與 `mileage_excluded: number`。`coverage` 為期間有該類資產反向連結的成本單比例。缺口列車輛與儀器的 `N / M 張成本單有車輛紀錄` 或儀器紀錄。缺值與倒退里程逐組排除並計數，有排除時標「部分里程」。`idle_days` filter 保留從未使用者，null 顯示「期間無使用紀錄」。覆蓋不足 80% 時，無使用 KPI 使用「期間無使用紀錄」；目前所有覆蓋率均採此保守名稱。
- review 人員排行保留 `(person_key, group)` 為識別，顯示 `person · group`。空白 person 顯示「未填」，`person_key=__blank__`，可用 `person=__blank__` 篩選。排行點擊同時套用 person 與 group。
- review、progress、sales、assets 加 `options`。分別為 `{group:string[],person:string[],flag:string[]}`、`{group:string[]}`、`{status:string[],pm:string[]}`、`{status:string[],category:string[],owner:string[]}`。選項獨立於當次 group、人員、PM、類別與文字篩選。review 為整個部門，progress 為當週，assets 為資產類型。
- review status 升冪依「已通過、已退回、待檢核、未填」。所有表格首次點文字欄為升冪，數字欄為降冪，同欄再點切換。搜尋 offset 與 debounced query 同時套用。
- TrendChart 的圖像內沒有可聚焦元素。外層 group 提供名稱，SVG 提供完整文字摘要，原生週次按鈕提供鍵盤選取。錯誤狀態使用 `role=alert`。


## Round 2 補充契約

- Sales items 新增 `id`，保留空白 `code`、`name`、`client`。UI 編號顯示「（未填編號）」及 record id 末六碼，名稱與業主顯示淡色「未填」。空字串與 null 的排序固定在有值列之後，升降冪皆相同，並以 record id 作穩定次序。`sales-code` 缺口回傳「N 件案件未填編號」。
- Progress 組別新增 `planned_days`、`matched_days`，既有欄位不移除。組別達成率旁顯示「對應 matched / 預排 planned 天」，另以淡色顯示「另有 N 天未預排」。KPI 新增對應天數與未預排天數標示。明細顯示預排、對應、未預排天數，後兩欄接受 `sort=matched_days` 與 `sort=unplanned_days`。達成率計算不變。
- 缺組別統一正規化為 `未分組`，可重複正規化。`group=未分組` 與 `group=__blank__` 查詢相同資料。組別圖表顯示「未分組」。工作單缺口計數包含無日期列，但無日期列仍不納入每週達成率。
- Assets 的 owner、category、status 空白選項及 Progress 缺組別選項使用 `__blank__`，下拉標示「未填」。空字串僅代表全部。資產明細保留原始空字串，空白篩選由後端轉換。車輛仍沿用啟用狀態及「車輛」類別回退。
- 每個 tab 定義欄位預設排序，日期與最後使用日期預設降冪。同欄再次點擊反轉方向。清除篩選及工項排行點擊同步更新搜尋條件，不先以舊 q 查詢。

## Round 3 補充契約

- Progress 的 KPI、`by_group`、`items` 新增數值 `matched_points`，為已預排案件日期上的實際點數。points 達成率使用 `matched_points / planned_points`，組別及案件分母使用 `planned`。`actual_points` 與 `actual` 保留全部實際點數。UI 的 points 說明與主要明細欄使用預排點數、對應點數，另保留預排、對應、未預排天數。
- Progress 缺組別的下拉及圖表標示統一為「未分組」，傳輸值仍為 `__blank__`。此規則取代 Round 2 對 Progress 下拉「未填」的敘述。Assets 空白類別圖表標示「未填」，傳輸值為 `__blank__`，空白 category、status、owner 明細顯示「未填」。
- 切換資產種類同步清除 category、status、owner。Progress 切換週次或部門同步清除 group。Select 收到的 options 不含目前值時清除該條件，修正前仍顯示目前值，不顯示「全部」。
