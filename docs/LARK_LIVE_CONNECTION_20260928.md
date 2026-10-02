# 2026-09-28 真實連線驗收

工作台：https://yongxiang-projects-20260925.zeabur.app

## 已實測

- Zeabur 部署 `6aba548ecf055b5b045624e1` 已恢復 RUNNING。完整18項環境讀回相符，健康檢查 PostgreSQL 正常；新版資產與 demo 10 項驗收通過。
- 使用者完成 Lark 瀏覽器登入後，工作台 OAuth 真實登入成功，session mode=lark、role=manager。未直接修改資料庫資格。以正常 workspace/switch API 切換正式區。
- 正式 `/api/people/sync` HTTP 200，最近成功時間台灣 2026-09-28 21:22:37；status=review_required，並非全部名冊已對齊。遠端只讀核定的四欄，無薪資回寫。
- 正式 `/api/sources/sync` HTTP 200、status=ready，台灣 2026-09-28 21:24:49。專用 application 身分讀取 V4＋Lark 報價總表共9張表、2569列。
- 同步回報：535筆日報均需核對、182列確認單無編號、1筆日報缺日期。未配對日報不建立案件，未写入 Lark。

## 尚未完成

真實讀取成功不代表日報關聯／人員資料全部合格。待核對名冊原因、舊日報關聯、新日報新增測試、Drive資料夾及上傳讀回、四類專用審批、Attendance權限發布與正常班表讀回、通知送達仍需逐項完成。

設定事故及永久防護見 `ENVIRONMENT_REPLACEMENT_INCIDENT_20260928.md`；其他整合缺項見 `LARK_INTEGRATION_GAPS_20260928.md`。

## 同日追加核實與決策

- 設計變更內審由使用者核定 PM＋該組主管兩位不同人共同核准；業主佐證、公司主管確認仍獨立保留。
- 四張專用審批表單已建立發布；專用 application 真實 GET 定義均 ACTIVE，欄位與 AND 審批節點驗證通過。尚未建立真實審批實例或代同事核准。
- 四張對應已加入完整 Zeabur 設定，19 個唯一鍵全部讀回相符；待新版部署啟用。平台傳回重複 HOST 鍵，確認值完全相同才去重，未省略既有設定。
- Drive 成果根資料夾已建立並讀回核實；工作台尚未啟用外部保存，上傳流程尚待驗收。
- 名冊 69 筆：61 在職有帳號、1 在職缺帳號、7 離職（其中 5 缺帳號）。只讀四欄，未讀薪資或按姓名猜配。詳見 PEOPLE_DIRECTORY_REVIEW_20260928.md。
- 正式工作區 API 目前 279 個案件、3 個 blocked 背景工作，external_enabled=false；案件數不代表日報已配對。
- 新部署前六表完整備份已下載並通過本機隔離 SQLite 逐列逐檔還原；尚未完成 PostgreSQL 災難還原。

## 新版部署後驗收

- 部署 `6aba8387cf055b5b04562ae2` 已 RUNNING；四類審批對應及三線規則已隨新版發布，demo 10 項檢查通過。詳見 DEMO_DEPLOYMENT_20260928.md。
- 台灣 23:16:06 真實 Attendance 同步 HTTP 200，但 status=pending_schedule、ready_count=0，62 筆 employee_identity_unverified。這只證明正常正式工作區路徑已修復，尚未取得員工班表；不能宣稱截止時間已自動同步。
- 官方班表介面需 employee_id／employee_no，名冊 open_id 不可直接代填；後續須以專用應用核實員工識別，不按名字配對。
- 新版部署後，透過正式管理員正常 `/api/actions` 的 `admin_settings` 設定成果 Drive 根目錄並啟用 external_enabled，HTTP 200、設定回傳相符。事前沒有 queued／running 工作，既有三筆 digest 均 blocked，未重新送出。實際檔案上傳與下載雜湊核對仍未執行。
