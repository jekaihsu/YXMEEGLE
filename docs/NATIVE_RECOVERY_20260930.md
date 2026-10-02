# 原生審批安全恢復（2026-09-30）

修正 #186／#188 與失效範圍原審批追蹤。未建立真實審批、未代替任何人投票。

## 官方錯誤碼依據

已讀 [Lark 建立審批 API](https://open.larksuite.com/document/server-docs/approval-v4/instance/create.md) 與 [撤回 API](https://open.larksuite.com/document/server-docs/approval-v4/instance/cancel.md) 的完整 Markdown，副本留在 `.runtime/native-docs-20260930/`。另核對 CLI `schema approval.instances.create` 的 UUID 去重規則。

只在指定 POST endpoint、HTTP **400**、JSON 整數 code 同時符合時，認定該次寫入明確未執行：

| 操作 | 白名單錯誤碼 |
| --- | --- |
| 建立 | 1390001（參數）、1390015（定義停用）、1390013（不支援的流程） |
| 撤回 | 1390001、1390002、1390003、1390018 |

1395001 服務錯誤、UUID 衝突 60012、任何未列碼、HTTP 5xx、限流、通訊／JSON 不完整，均不能證明沒寫入。**GET 查不到不是未建立證據。** HTTP 狀態與文件不符也不擅自擴大白名單。

## 行為

- 明確拒建：先保存 attempted，再持久化 `creation_outcome=not_created`、code／HTTP／UUID／時間。可在權限與正式送出開關重新核對後，使用同一不可變 payload 與 UUID 重試；不換 UUID 碰運氣。拒絕歷史保留在 `rejection_history`。
- 原申請人可呼叫 `POST /api/native-approvals/{kind}/{id}/abandon`（body `version`），僅在上述拒建證據完整時結束本地申請、有 audit、不 POST 撤回。未知結果禁止此操作。變更任務仍須另走附理由的 `change_resume`，沒有自動解凍。
- 結果未知：再次 submit 只查回原 UUID；不重送。取消結果未知也只 GET，不重複取消。
- 明確拒絕撤回：保留錯誤、清 `cancel_attempted` 與 `cancel_requested`，修正後可重新請求；每次先查原件仍須 PENDING。原件已 APPROVED／REJECTED／CANCELED／DELETED 時只回真實狀態，零取消 POST；按撤回不再使既有有效核准暫時失效。
- scope／核准人／定義已改變或申請失效：poll API 與 background poller 仍可查原 UUID。核對原 payload、申請人、表單及 instance_code 後，記錄終態 `remote_resolution`；**不把這個觀察結果當成新範圍核准**。定義不可用或投票證據失效也不遮蔽原件生命週期，但結果維持不可套用。
- `remote_binding_resolved(item)` 驗證原不可變 binding 與終態證據；單純 `status=invalidated` 或 `remote_resolution_required=false` 不能讓 `change_resume` 通過。

## 驗證與界線

新增 18 項 recovery 測試涵蓋官方碼分類、其他錯誤維持 unknown、同 UUID 再送、禁止 unknown abandon、帶 audit 的明確拒建 abandon、撤回重試、失效範圍終態觀察及 definition drift。整體 `pytest backend -k native` 為 **176 passed、1 failed**；唯一失敗是舊 `test_backend` 自造 Lark 登入 fixture 未符合新准入規則，交由主協調者處理。沒有實際人員投票回執，不能將本機測試描述為 Lark 真實審批驗收完成。
