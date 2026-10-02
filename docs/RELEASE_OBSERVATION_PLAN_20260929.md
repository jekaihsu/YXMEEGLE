# 修正版發布與 24 小時唯讀觀測

## 發布後立即驗收

等待 root 確认最新 deployment RUNNING 後，執行 `.runtime/demo_acceptance_20260929.py --deployment <真部署ID>`。本輪不沿用 9/28 回執，也不因 health 200 就承認新版。新版 dist 預期 `ieKSvLZ6`，腳本逐資產比較實際 bytes/SHA256 與本機 frozen dist。

檢查匿名展示 session 的 demo namespace、示範案件、u- 測試名冊、無公司 open_id／私密身分欄位／token、來源 API 不暴露正式 records、正式維護 API 回 403；五分頁所需唯讀 API 正常。只 GET，不送訊息、審批、Input 或 Drive。首次一般匿名 GET session 會由既有應用建立獨立 demo workspace，属于正常展示登入，不是正式資料操作。

舊 `.runtime/demo_acceptance_20260928.py` 仍可做基本檢查，但不足以驗 environment migration、正式管理 API 隔離；本輪使用新脚本。`scripts/deploy_verify.py before` 會寫 demo 留言與附件，不屬本輪只讀觀測，不能混用。

## 24 小時持久證據計畫

- 公開監測每 5 分鐘跑一次 `--public-only --deployment <ID>`，預計 288 次。每次是獨立程序，無長時間 sleep；只 GET health、HTML、assets，不建立 session，不產生數百個 demo workspace。
- 回執以 UTC 時間＋微秒 exclusive 建檔於 `.runtime/release-observation-20260929/`，記部署 ID、bundle hash、狀態、耗時與 true/false，不寫 cookie、憑證、公司內容或原始錯誤全文。
- 需由 root 選擇持續在线的排程主機並正式建立 scheduler／Task Scheduler，設定失敗可通知的管理管道；本文件只準備方案，**尚未建立排程、沒有24h證據，不宣稱已開始觀測**。本機電腦休眠會中斷，因此不能默認此工作區筆電即可承擔正式監測。
- 第 0、12、24 小時另外各跑一次完整匿名 demo 驗收。每天只建立少量隔離 session。
- 正式 manager 的 `/api/admin/runtime-health` 應由已授權監测身份另外取最小狀態（worker最後成功、備份年齡）；匿名脚本遇403是隔離正確，不代表worker或backup健康。不得復用瀏覽器個人token做無人值守常駐任務。
- 5分鐘公开檢查連續2次失敗或asset版本非本次部署即記異常；正式worker全流程成功超過15分鐘／備份快照超過36小時等門檻沿用 server runtime-health，不以HTTP200替代。通知收件人／管道需沿用既有授權，未設定前不能宣稱告警有人接收。

## 24 小時結案標準

保留所有觀測與中斷，不只成功紀錄；計算預期／實際樣本、最大資料缺口、失敗段落及原因，核對最後 bundle、worker與backup新鮮度。任何監测停機或重大功能未真實驗收明列，不能以「已過24h」當作全功能通過。Cloud demo驗收不代表OAuth、名冊、Attendance、原生審批、專用Input或異地復原均完成。
