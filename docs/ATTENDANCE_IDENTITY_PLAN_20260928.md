# Attendance 身分對應待辦：官方核實與最少維護方案

正式班表同步目前 HTTP 200、`pending_schedule`、62筆 `employee_identity_unverified`、ready=0。這代表流程已可執行，但尚未取得可查詢班表的員工身分；不能表示62人都沒有班表。本次只核對官方公開文件，沒有修改外部權限，也沒有變更部署中的程式。

## 官方核實

- [查詢班表資訊](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/attendance-v1/user_daily_shift/query)：`POST /attendance/v1/user_daily_shifts/query` 的 `employee_type` 只接受 `employee_id` 或 `employee_no`，**不接受 open_id**。此處 employee_id 是 Lark 管理後台的用戶 user ID。現行程式不直接把 `ou_...` 當 employee_id，是正確限制。所需權限為 `attendance:task:readonly`；班次詳情另需 `attendance:rule:readonly`。
- [OAuth 取得使用者資訊](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/authen-v1/user_info/get)：user_info 本身無額外接口權限要求，但回應 `user_id` 欄位需要 `contact:user.employee_id:readonly`。既有登入程式已在回傳 user_id 時保存映射；因此僅重複登入、沒有所需欄位權限，不會自動解決缺值。
- [批次取得使用者資訊](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/contact-v3/user/batch)：`GET /contact/v3/users/batch` 可用 `user_id_type=open_id` 與重複 query 參數 `user_ids` 查詢，每次最多50人，支持 tenant_access_token。回應同時有 open_id 與 user_id，user_id 仍需 `contact:user.employee_id:readonly`。接口基本權限是 `contact:contact.base:readonly`，並需應用資料可見範圍涵蓋對象。異常／無法取得的 ID 可不返回，不得依陣列位置猜配。

本機保存官方原文於 `.runtime/attendance-official-schedule.md`、`attendance-identity-doc-1-batch.md`、`attendance-identity-doc-2-get.md`。官方文件由 Lark llms 索引逐層取得，不依第三方猜測 API。

## 建議方案

以同一專用 application、同一核定 tenant，對已由公司名冊確認在職的 open_id，執行官方批次 GET，**按回應 open_id 精確對應 user_id**。62人最多兩批，沒有必要讓每位員工各自登入以維護考勤映射，也不需讀手機、email、薪資、職級或整個部門樹。

新增權限前應先讀取目前已發布權限；如果已具 `contact:contact.base:readonly` 與 `contact:user.employee_id:readonly`，直接先做一筆唯讀查證；缺少才另核准／設定並發布。這輪沒有開通任何新權限，也未宣稱目前已有這兩項。

後續程式實作範圍（**尚未實作／部署**）：

1. 新增小型只讀身分解析器，僅允許 GET `/contact/v3/users/batch`；每批50，缺／重複／不在請求範圍的 open_id、空 user_id、同 user_id 對多人的回應都保留待核對，不能按名字或順序配對。
2. 查詢前後重驗 application、tenant、操作者資格及在職名冊版本。僅將 `{open_id, employee_id, employee_type:'employee_id', app_id, tenant, verified_at, source:'contact_user_batch'}` 投影持久保存；忽略其他回應欄位。
3. 現在 `AttendanceScheduleReader` 只允許 `source='oauth_user_info'`，需精確擴充至這個受控服務產生的 `contact_user_batch` 來源；不可改為接受任意客戶端傳入的 employee_id。
4. 可在合法班表同步前補缺少映射，並於名冊新增／身分變更時重新核對；映射應緩存，不需每五分鐘重讀62人全部通訊錄。離職停權仍由在職名冊及現有准入檢查控制，既有缺映射不得被自動當成離職。
5. 同批核實後再查正常班表；每人每天缺班表、彈性班別或時間矛盾仍保留 pending，不用打卡時間或固定17:00填補。

必要測試：51人分兩批、回應亂序、部分回應缺失、重複 employee_id、異租戶／換app、同步中停權、scope不足、回應無user_id，以及重新同步不重複映射或班表歷史。真實驗收須記錄核實映射數、ready/pending分類及班次時間回讀，不輸出人員ID或名字。

較少程式變更的備選是開通 user_id 欄位權限後每人完成 OAuth，但人員初次登入／重新授權的維護成本較高，且不能一次解決其他員工班表，故優先批次只讀映射。
