# Drive 成果保存入口補齊

主案件資料頁原先只有檔案下載、Drive 狀態，沒有保存入口；本輪新增 `DriveFileStorage.tsx`，主檔案頁與流程中的舊文件清單共用。

- 首次本地文件提供「保存至公司 Drive」，經正常 `/api/files/{id}/store-lark` 並帶工作區版本送出。
- 正式工作區若 drive_root 尚空或 external_enabled 未開，停用保存並明示檔案僅暫存工作台。不會自行啟用設定。
- 排隊／執行中提供更新狀態；已核實不提供重送。失敗／受阻／結果未知導向背景工作及回執核對，避免重複保存。
- 展示 queued 與 verified 不混淆，送出成功只稱「已送交保存工作」，不稱檔案已存入 Drive。

`frontend/qa/ui_drive_storage_20260928.js` 的 10 項隔離 fixture 檢查全部通過，未對遠端上傳檔案。TypeScript／Vite build 通過，bundle `index-BeVrXu_y.js`、`index-bMhteLtr.css`。尚未部署。

已向主代理回報後端待檢查：舊 store-lark 路由對既有 job 呼叫 queue 後仍直接將檔案標 queued，可能覆蓋 failed／outcome_unknown 外觀；前端不再提供這些重送入口，但直接 API 仍需後端防護。

同輪更新設計變更固定內審標示為 PM＋該組主管共同核准，依使用者新決策，不修改後端或真實審批設定。
