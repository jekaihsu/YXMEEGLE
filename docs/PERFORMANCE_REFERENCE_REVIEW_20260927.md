# 參考方案對照與本機效能基準

## 結論

參考方案指出的全工作區讀取與回傳問題確實存在。差異化資料列儲存已實作，但每次仍讀取、複製及比對全工作區。先改善身分查詢、封存資料與案件讀寫粒度，比單純拆 App 檔案或改 dispatch map 更直接。

本輪只做隔離量測與必要的 API 隱私修復，未縮減待成案任務、未改正式資料、未呼叫外部服務。下列基準固定在隱私修復前版本，不拿後續改動冒充基準成果。

## 方法與證據

- 程式：`scripts/benchmark_workspace.py`；產物 `.runtime/performance-baseline-5ed5ffba/report.json`。
- 同目錄 `code/` 保存本輪受測檔案複本與 SHA-256。輸入備份／來源快取在測前、測後核對雜湊一致。
- 舊資料來自已完成還原核對的私有備份 `legacy-cloud-backup-20260927T090311Z-c9603e1e/restore.sqlite`，不是正式 DB 連線。來源重播使用已取得的九表私有快取；不重新呼叫 Lark。
- 三個獨立 SQLite 複本，各測 5 種操作、每種 3 次，先暖機。TestClient 走實際 API、中介層、SQLAlchemy、序列化與 gzip；量測不含網際網路、PostgreSQL 或瀏覽器繪製。
- 僅測試複本將選定操作者設為 manager、選定案 PM，建立本機測試登入回執，以滿足操作前提。留言與任務說明只寫複本。
- `archive_detached_experiment` 只在複本移除 migration_archive，屬單一因素探索，不代表正式程式已完成封存遷移。各組順序執行且樣本少，環境亦有其他工作，不能視為嚴格負载試驗或生產 p95。
- 組件計時是包含式，互相重疊，不能相加當總時間。原始三次值、SQL 次數、gzip 前後位元組與 JSON parse 時間均在私有報告。

## 結果

中位數，秒：

| 操作 | 舊備份升級：280案／6,160任務 | 現行來源重播：281案／6,545任務 | 舊備份移除封存實驗 |
|---|---:|---:|---:|
| GET session | 2.44 | 2.00 | 2.13 |
| GET workspace | 7.17 | 4.40 | 3.31 |
| GET projects，30筆 | 2.63 | 2.27 | 1.54 |
| 新增留言 | 8.36 | 8.58 | 5.27 |
| 修改任務說明 | 9.51 | 10.17 | 5.59 |

舊備份是當時的 280 案，不含後來 formal/intake 分類。現行來源重播為 15 正式案、266 待成案、2,529 節點及 535 待配對日報；兩組業務內容不同，不能直接把差值全歸因於效能改進。

舊備份 workspace 回應解壓後 8,530,888 bytes，gzip 約 271,918 bytes。現行來源重播為 6,081,106 bytes／200,080 bytes。移除舊封存的實驗為 4,988,764 bytes／154,763 bytes。gzip 降低傳輸量，沒有免除伺服器讀取、複製和序列化全資料的成本。

一次任務更新的具體成本：

| 組件 | 舊備份 | 現行來源重播 |
|---|---:|---:|
| storage.load，2次合計 | 2.35秒 | 3.13秒 |
| storage.save，全資料列讀取與差異比對 | 2.08秒 | 2.42秒 |
| public_ws | 0.95秒 | 0.71秒 |
| upgrade，3次合計 | 0.23秒 | 0.26秒 |
| review_hash，5,040／5,058次 | 0.10秒 | 0.14秒 |
| 真正 apply_action 業務更新 | 約0.0002秒 | 約0.0002秒 |

修改一項任務只發生 3 UPDATE、2 INSERT，但仍有 14 SELECT 且多數讀全工作區。瓶頸是讀取／複製／回傳的資料範圍，不是「UPDATE 全部資料列」。分頁 projects API 目前只在全量載入後切頁，因此回應很小也仍需兩秒左右。

## 各階段落實程度

| 參考項目 | 現況與證據 | 建議 |
|---|---|---|
| phase0 備份與實測 | 已有真實備份還原核對；本輪加程式快照和本機 API 基準。未做生產負載測試。 | 保留此基準；部署前另核對最新備份時間與還原點。 |
| identity 直接 PersonRow | PersonRow 已存在，但 `app.identity` 先 `load(...)[users]`，session 又載一次。 | 優先改成直接查目前公司 PersonRow；兼容舊資料須受控遷移，不移除停權與身分校驗。 |
| 遷出 migration_archive | 尚未遷出 DB 根 JSON，storage.load/save 仍搬運。 | 本輪先從 public API 剝除，DB 保留；後續以獨立封存列／備份遷移，保留雜湊與回復。 |
| public_ws 使用者投影 | 基準版本沒有；本輪已修請假可見性及封存回傳，詳見後端 readiness 報告。 | 未核定的案件／財務可見政策不自行變更；日後投影政策需明確。 |
| upgrade 僅 migration 跑 | 啟動已有 schema migration，但 load/public_ws/operations/jobs 仍反覆 upgrade。 | 加獨立 schema version 與受控升級後，再從穩態請求移除；不能直接刪掉相容保障。 |
| actions 僅重算案件 | 未做；先 hash 所有節點，legacy action 後再全案核對。 | 依 action 影響範圍重算；跨案日報／合併／人員全域異動須另處理，不可一律套 body.project_id。此項在基準中非最大瓶頸。 |
| project_versions／單案 CAS | 目前是 workspace.version 與整工作區列鎖。 | P1 架構工作；保留跨案交易與 request receipt 去重，不能只把version欄搬走。 |
| 單案 GET／POST 回單案 | 未做。GET projects 是列表摘要，沒有單案完整 API；mutations 回全工作區。 | 先定 projection 與delta契約、前端快取，再導入單案儲存。 |
| jobs 獨立 rows | 已作為 BusinessRow(kind=jobs) 正規化，但 worker 仍重組、儲存整 workspace。 | 欄位化 job 狀態／租約／索引與獨立claim；保留原來 unknown outcome 與權限重查。 |
| 409 只刷新該案 | 未做；`frontend/src/App.tsx` refresh 重新取 session＋workspace。 | 待單案version與API完成才能安全縮小刷新。 |
| 待成案僅接案與確認 | 尚未核定／未做；266 待成案仍有完整 SOP。 | 業務政策，不能以效能名義直接刪任务。確認成案展開時須保留ID、人工歷史與既有任務。 |
| 單一 Base 寫入口 | 寫入均有 LarkAdapter、worker與目的檢查，但 input／training／capability 各自處理。 | 收斂寫入政策與回執契約，不將來源唯讀同步改為寫入。 |
| 535 日報修正 | 來源識別與錯誤分類已做；535 仍待配對。 | 需來源真實關聯或人工雙方核對，不能用效能改版自動造案或猜配。 |
| App拆檔／dispatch | 已有 Operations/Learning 等模組；App及backend action分支仍大。 | P2 可維護性工作，不宣稱單純拆檔即可消除上述秒級耗時。 |
| recurrence 一次工作區迴圈 | schedule先遍歷projects，再遍歷recurring；每筆仍線性find project、查existing recurring。 | 建立project與(project,kind)索引，避免巢狀掃描；須先獨立量測worker，這次API基準沒有覆蓋worker。 |

## 執行優先順序

P0：完成 API 隱私修復及回歸，保持正式資料不變。

P1：直接人員身分查詢、遷出封存熱資料、案件級查讀／CAS／回應；每一步沿本基準比較，並驗證停權、跨案交易、409與工作租約。

P2：穩態不跑upgrade、針對性重算、recurrence索引、App及dispatch整理。待成案縮任務另走業務決策；不列成已核准效能修改。
