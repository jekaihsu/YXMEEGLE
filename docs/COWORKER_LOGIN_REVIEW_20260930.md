# 同事登入與名冊准入核對

## 結論

普通同事不需逐人建立工作台帳號，也不需先升級為管理員。前提是專用 Lark app 對本人可用、公司名冊「人員」欄連結其正確帳號、「在職」明確為 true，且應用身分同步成功未超過 900 秒。登入只能由本人完成，不能用管理員登入結果代替。

名冊新成員預設 `member`、空 capabilities、正式工作區；業務操作另看案件 PM／大節點負責人／子任務負責人／審核者與功能授權。能登入不等於具有全部業務權限。內外勤分類不會自動推導組別主管，缺少組別／責任人仍需公司授權者設定。

## 身分與來源流程

1. 應用唯讀取得薪水 Base 的已核定人員表四欄：姓名、人員、在職、內外勤。要求 `user_id_type=open_id`，不讀取薪資欄、不回寫來源。
2. 以同一 app 的 open ID 合併；不依姓名合併。同名、缺帳號、多帳號及重複帳號不會猜測關聯。
3. OAuth 校驗一次性 state／cookie、租戶白名單，再用 Lark user_info 的 open ID 精確查公司 PersonRow。未在名冊且沒有獨立公司管理帳號授权者不得自行註冊。
4. 正常登入後每次 API 都重新查正式名冊與權限；離職、停用、缺失、跨 app、過期立即拒絕。重同步不恢復人工停權或重新賦予管理權。
5. 公司名冊背景同步每 300 秒，須 `people_directory_connection.enabled=true`。同步採已授權公司唯讀連線，不依賴某同事持續登入；名冊健康面板 600 秒預警，900 秒後阻擋。

## 本次實際修正

OAuth callback 原本只查是否曾獲名冊准入，未查 900 秒新鮮度，導致過期同事先拿 cookie／redirect，下一個 API 才被拒絕，看似登入無反應。兩個 callback 分支現改用 `require_access(... allow_recovery=True ...)`：普通同事過期／未來／無效時間不建立 session，bootstrap 管理員仍保留既有維修入口，沒有降低准入門檻。

## 正式環境必要條件

- `APP_ENV=production`，持久 DATABASE_URL／SESSION_SECRET；`DEMO_MODE=false`、`ALLOW_CLOUD_DEMO=false`。
- 正確 `LARK_APP_ID`／`LARK_APP_SECRET`／`LARK_REDIRECT_URI`／`LARK_ALLOWED_TENANTS`；Lark 後台 callback 白名單與 HTTPS 正式網址一致。
- `LARK_WORKER_IDENTITY=application`、`LARK_WORKER_ORGANIZATION` 在允許租戶中；worker 確實運作且唯讀名冊連線已启用。
- app 已發布、可用範圍包含欲使用同事；app 對人員表有唯讀資源權限與 API scope。
- `PUBLIC_ORIGIN` 指正式網址；反向代理與 Secure cookie 使用 HTTPS。
- 普通同事不需加入 `LARK_ROLE_MAP_JSON`。公司管理帳號的精確 grant 是另外的例外，不能當作同事自動獲權機制。

## 驗證範圍

本次本機 82 passed：staff OAuth HTTP、legacy OAuth、公司管理帳號准入、people directory、production access。新增過期／未來／格式錯／缺時間在 callback 即拒絕且沒有 session row／cookie 的反例。HTTP OAuth 為合成 provider，不能稱真人驗收。

既有真實唯讀回執 `.runtime/people-directory-verification-20260927.json`：2026-09-27 13:30:56 UTC，來源 69 列、可解析人員 63；remote_writes=false、production_database_access=false。這是過往來源解析證據，不表示今天 63 人全部在職可登入、全部已寫入正式 PersonRow 或目前名冊仍新鮮。

最新正式 deployment `6abd215dc997a72fa1748eba` 已於 9/30 14:50 UTC 完成，包含 callback 新鮮度與登入固定正式區修正；六個關鍵檔案 SHA 與候選包相同。jekai 已重新 OAuth，session 與 workspace HTTP200、formal_namespace=true。這不替代普通同事本人验收。

## 尚待本人及線上驗收

### 最新名冊問題核實（2026-09-30 台灣 22:51）

正式 workspace 在台灣 22:50 的讀回為 64 人（63 個來源可解析帳號，加獨立 jekai），名冊同步成功但 `review_required`。隨後以同一工作台 app 唯讀四欄名冊，仍為 69 列／63 可解析，6 個問題全為 `missing_account`，没有重複帳號或多帳號問題：其中 5 列來源明確離職；**鄭光瑞**來源顯示在職但沒有可解析的「人員」帳號關聯。使用者已核定「他不用，只要有 LARK 帳號的人才可以使用」，因此這 6 列均不需補開通，鄭光瑞不列為上線缺口。現有逐人帳號准入規則維持，未寫回薪資 Base，也未按姓名自行配人。

另已解析名冊中的 **王煜誠、林芷樓** 明確離職，正式 profile `active=false`，登入應被擋。其餘可解析且在職者仍須個別 active、freshness 與角色檢核；來源可解析不等同全部真人已成功登入。私有診斷 `.runtime/coworker-roster-diagnosis.json` 僅列姓名、匹配原因、在職狀態及四欄名稱，不含薪資。

補充實際 Lark 可用範圍核實（2026-09-30 14:38:21 UTC）：專用 app `cli_aa3cab98b2789e17` 的最新版本 0.4.3，版本 ID `7690834540366056986`，已發布、審核通過，可用範圍明確為「所有员工」，且頁面顯示目前修改均已發布。這不是通訊錄讀取範圍的推論。安全回執 `.runtime/company-app-availability-verified.json`；檢查僅開新命名分頁讀取，沒有變更設定。較舊 0.4.1／0.4.2 的「部分成员」紀錄已被此新版證據取代。仍不代表普通同事本人完成 OAuth。

- 至少一位普通在職同事以自己的 Lark 帳號完成正式 OAuth，確認 production／member／正確姓名，不具管理介面權限。
- 核對此人被指派案件與任務確實可見、能提交本人交付、不能代其他角色核准；不以 jekai 權限代驗。
- 管理員核對正式當前名冊最近成功時間、同步啟用與錯誤清單；不要求無公司 Lark 帳號者補關聯。如具帳號員工有實際匹配問題，才核對其明確身分。
- 新部署版本／cookie／真實班表等整合行為尚需驗收；app 可用範圍已由上方真實 0.4.3 版本頁核實為所有員工。
