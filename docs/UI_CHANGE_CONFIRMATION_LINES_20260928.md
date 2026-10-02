# 設計變更三線前端

與 native 後端代理確認 `POST /api/change-approvals/{request_id}/confirm-line` 契約後，新增 `ChangeConfirmationLines.tsx`，由正式設計變更詳情使用；demo 模擬操作保留原樣。

- 公司主管本人確認：仅節點指定主管、否則案件主管可操作，不因管理員角色而代投。
- 業主確認佐證：案件 PM 或指定主管登錄外部佐證，必填說明、至少一筆本案 accepted 證據；已撤下、尚未覆核、文件未核實保存 Drive 者不列入。不是代外部業主投 Lark 票。
- Lark 內部審批：單獨顯示；核准不等同其他兩線完成。使用者後續已核定 PM＋該組主管兩位不同人共同核准，介面已更新固定標示，不再列待決定。

送出使用 `{version, party, reason, evidence_ids}`；沒有送出正式變更（native binding 尚未 attempted）或申請終態時不能登錄。409 會更新工作區，由後端重新核實範圍、身分及證據。

舊 `owner_confirmed`／`client_confirmed` 布林不顯示為正式已確認。存在新 proof 時顯示「已登錄，套用時重新核實」，因為前端不能單靠 proof 與 binding scope 比較判斷目前案件範圍／人員／附件仍有效；完整有效性由後端決定。

`frontend/qa/ui_change_lines_20260928.js`：11 項隔離 fixture 檢查通過，包括舊布林不冒充證明、內審通過不提供提前套用、不能代主管、佐證篩選、必選佐證、正確 API payload、draft 不可確認。第一次 Playwright `isDisabled()` 對 option 判斷不符原生屬性，改直接讀 HTML option.disabled 後確認本身確實已停用。

TypeScript／Vite 建置通過。此代理沒有部署或提交真實審批；真實三線核准與套用仍須整合驗收。
