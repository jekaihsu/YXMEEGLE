# 名冊讀取失敗時的寬限入場政策

## 原因

即時讀取（`LARK_LIVE_READ_ENABLED=true`）只在有人使用時於背景刷新名冊。普通同事的名冊證明超過 900 秒就被拒絕，所以只要一次刷新失敗或太慢，全員在最後一次成功後 15 分鐘起都進不了 `/api/projects/{id}` 等頁面。

名冊與班表刷新原本很慢：每個 Lark 請求前的權限檢查會載入整個工作區，套用時再載入並比對整個工作區。staging（2 vCPU、31,934 筆 business_records）實測一次完整載入約 2.0 秒、一次完整儲存比對約 10.9 秒，名冊刷新因此耗時 20 至 85 秒，超過 30 秒預算就失敗。現在檢查只載入人員，套用只寫入有變動的集合。

## 政策

僅在即時讀取開啟且為應用身分時，`access_mode` 以寬限秒數取代 900 秒：

| 項目 | 規則 |
| --- | --- |
| 寬限 | 預設 86400 秒（24 小時）。`LARK_LIVE_READ_ROSTER_GRACE_SECONDS` 可調，下限 900、上限 604800。設為 900 即回到嚴格行為。 |
| 仍須成立 | active、在職（`directory_status=employed`）、未缺漏、同 app、有 record_id、時間戳有效且不在未來。 |
| 不變 | 名冊明確離職或缺漏者立即拒絕；未知人員拒絕；公司管理員授權、bootstrap 恢復模式、tenant-read 規則不變。 |
| 超過寬限 | 一般同事回到 `access_roster_expired`；bootstrap 管理員進入 recovery。 |
| 即時讀取關閉 | 維持 900 秒。 |

離職在名冊下一次成功刷新時才會生效。刷新持續失敗時，最長有 24 小時的離職延遲，這是此政策接受的風險；`/api/admin/runtime-health` 的 directory 狀態在超過 900 秒時仍顯示 stale 作為維運警示。

## 驗證

`backend/test_roster_grace.py` 涵蓋新鮮、900 秒、寬限內、剛好 24 小時、超過寬限、明確離職、缺漏、未知人員、停用、外部 app、時間戳缺漏／無時區／未來、管理員授權與 recovery，以及整條 HTTP 路徑在刷新持續失敗時 member 仍可讀取、離職者被拒。
