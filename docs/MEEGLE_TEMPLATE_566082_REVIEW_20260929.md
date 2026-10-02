# Meegle 第二模板唯讀盤點

2026-09-29 依 Meegle skill auth guard 查得 CLI 沒有本地登入，完成官方 device flow 後登入成功。CLI inspect 沒有模板本體命令，因此在既有登入瀏覽器新增獨立 Meegle 分頁，從流程清單點選「詠翔SOP精簡版」，保存該頁實際載入的查詢回應。未按 Save、未修改 Meegle、未匯入舊案件。

## 真實來源

- template ID：`566082`；名稱：詠翔SOP精簡版；version：`2`。
- 空間：`69d92a061543d1dedeb3c91d`；工作項類型：`69da47b0b775f6135d0aa7f8`。
- 頁面讀取端點：`/goapi/v1/projects/69d92a061543d1dedeb3c91d/templates/detail`；回應 code `0`。
- 本機原始 JSON：`.runtime/meegle-template566082-detail-20260929.json`。
- SHA256：`dc8ed1088b045f14583d9dd91bb624be97df2181f924e4cf59760acdce4f6f90`。
- 可重現清單：`docs/MEEGLE_TEMPLATE_566082_INVENTORY_20260929.json`；萃取器 `.runtime/extract_template566082_review.py`。
- 頁面讀取 request 含 `exclude_form_conf: true`，故本回執不能宣稱已讀完全部表單／Input 設定；保留此限制。

## 流程與子任務

共 7 節點、0 子任務、6 連線，線性順序來自 connections，不依 API 陣列位置推定：

| 穩定 key | 節點 | 完成模式 | 與工作台的初步對照（非已實作證明） |
|---|---|---|---|
| started | 業務接案 | auto_pass | sales；不可直接複製自動通過，仍受核定成果條件限制 |
| state_0 | 確認單開立 | single_user_confirm | confirmation |
| state_1 | 外業出工 | single_user_confirm | field |
| state_2 | 控制 | single_user_confirm | control |
| state_3 | 圖資 | single_user_confirm | mapping |
| state_4 | 報告 | single_user_confirm | report |
| state_5 | 未命名节点 | single_user_confirm | 未有業務意義，不推定為結案／財務 |

以上節點無模板子任務，未設定有效 owner rule。回傳的 required_node_fields 為 null、form_items 為空；因表單設定被讀取選項排除，不能據此宣稱沒有必填 Input／附件限制。

## 對目前工作台的影響

1. 「第二模板本體未取得」已解決；早期文件保留歷史狀態，以本次來源回執更新現況。
2. 不會從此精簡模板補出使用者期待的所有子任務：其真實 task 清單為空。完整子任務仍應以 334662 v137（62 節點、52 子任務、71 連線）、核定文件與決策對照。
3. 精簡模板是線性流程，不能用來證明目前工作台與完整版的並行／條件拓樸等價；也不能覆蓋 PM＋主管共同核准與財務審批等較新決策。
4. 尚需逐項核對完整版的未映射節點、條件、必填資料、角色及附件 gate。取得本體不等於發布了完整流程引擎。
5. `state_0` 等 key 在不同模板可重複，正式映射必須含 template ID/version，不能只用 node key 跨模板匹配。

既有 334662 v137 本體直接復用；本輪沒有重複抓取或修改其保存來源。匿名展示雲端驗收另见 `docs/CLOUD_DEMO_ACCEPTANCE_20260929.md`。
