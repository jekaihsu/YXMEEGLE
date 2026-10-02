# 人員、班表識別與過期名冊保護（2026-09-29）

本輪本機實作完成，尚未部署、未更改 Lark 外部權限。官方依據及最少 scope 見 `ATTENDANCE_IDENTITY_PLAN_20260928.md`。

## 班表原生識別

新增 `backend/attendance_identity.py`：以同一 application、tenant 的原生 open_id 分批 GET `/contact/v3/users/batch`，每批最多50人。只按回應 open_id 配對 user_id；重複、未要求的ID或多人共用 employee_id 整批拒絕，不按名字或陣列位置推測。只保存識別、驗證來源及時間，忽略 email等無關回應欄位。每次 HTTP 前後都重驗授權。

`AttendanceScheduleService.resolve_identities()` 在正式工作區檢查人員快照，交易內再核對後保存 PersonRow 與同步事件。有效映射緩存最多24小時；已完成查詢但沒有返回有效識別時，移除該次查詢對象的舊映射，以免繼續使用過期關係。網路／權限錯誤則中止，不冒充成功。

班表同步在服務設定 `LARK_ATTENDANCE_IDENTITY_RESOLUTION=contact` 才呼叫解析器。必須先核對專用應用已有 `contact:contact.base:readonly`、`contact:user.employee_id:readonly` 及相符可見範圍；本輪未自行開啟設定。已核實的 `contact_user_batch` 與原本 `oauth_user_info` 都可供班表 reader 使用。

## 名冊過期與復原界線

`production_access.access_mode(person, app_id)` 回傳 normal／recovery／denied。一般業務准入需要同app已核實在職、未缺漏、有效含時區 `directory_last_seen_at`，時間不在未來且距今不超過900秒。一般人在超時、缺時間或未知時間時拒絕；有效且未停權的明示 bootstrap manager 只獲 recovery。

`require_access(...,allow_recovery=False)` 是 app 層連接點，由主協調者在每次認證後套用。**只有 helper 不代表全部HTTP路由已受保護**：主協調者須讓 session／登出／指定維運與名冊修復路由可進 recovery，其餘業務拒絕；不能以 `/api/admin` 前綴廣泛放行。舊 `admitted()` 留作身分辨識及修復服務前置檢查，不應再被 app 當作業務 freshness 完整判定。

## 公司背景唯讀授權

新增共用 `readonly_sync_actor()`、`readonly_sync_connection()`。已啟用且公司application/tenant核定的唯讀連線，以無業務capabilities的 `system:company-readonly` 執行，來源授權記錄 app_id／tenant／authorized_by。排程不再依賴最後手動同步者持續在職；人員被停權不會讓全公司名冊永遠停止同步。

已存在的 enabled 連線保留其既有唯讀授權；若其已有 app_id／tenant但與目前不符則拒絕。呼叫方仍必須用 `_policy(wid)` 核對正式namespace；test/demo不能變成正式背景服務。此helper只允許people/source/attendance三種唯讀連線，不適用IM、Drive、Input或審批寫入。

People／Attendance已接上；Source由A代理依相同契約接線。

## 驗證

`python -B -m pytest backend/test_attendance_identity.py backend/test_attendance_service.py backend/test_attendance_schedule.py backend/test_people_directory.py backend/test_production_access.py -q` → **75 passed in 8.07s**。

含51人分批、亂序、未知及重複ID、缺user_id、請求後撤權、交易保存、快取、原手動操作者停權後背景仍刷新、900秒邊界與管理員限復原。仍需主協調者完成app route enforcement並做整合測試，以及真實scope/人員識別/班表讀回驗收。
