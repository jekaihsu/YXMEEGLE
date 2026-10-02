# 真實登入維運模式診斷 — 2026-09-29

使用者後續已確認名冊姓名為 `jekai`。以最新來源 69 列的「姓名」欄作 casefold 後精確比對，匹配 **0 列**；沒有可認定的唯一既有列。查詢仍限定四個核定欄位且 `user_id_type=open_id`。未將相似姓名或其他人員帳號自動綁定，也未重新要求使用者重答同一姓名。

正常 OAuth 登入後唯一有效 session 對應的人員檔案存在，角色 manager、bootstrap_admin=true、active=true、identity_app_id 與專用 app 一致，基本 admitted=true。登入者的 directory_status、directory_last_seen_at 都為空，沒有 directory_source.record_id，所以 access_mode=recovery。不是名冊逾期、錯誤 app 或停權；尚無精確名冊認定。

接著以 application identity 唯讀重新查核核定人員名冊四欄，沒有讀薪資欄位：69 筆來源、63 個有效帳號、6 筆 missing_account，沒有重複帳號或在職狀態不明。當前登入 open_id 在這 63 個來源帳號中的精確匹配數為 **0**。不以姓名比對，不修改正式資料庫或來源 Base。

因此即使 POST /api/people/sync 回傳 200 review_required，這位登入者仍應保留 recovery。同步成功表示完整處理名冊，不表示不在名冊的 bootstrap 管理員取得業務權限。

後續處理：

1. 若登入者本來應列於這份名冊，由本人／名冊管理者核實並修正對應列的 Lark「人員」帳號，再透過正常名冊同步取得 fresh directory 認定。需明確授權才可修改此來源，不因本次診斷自動寫入薪資 Base。
2. 若登入者不屬薪資名冊，須另行核定獨立的公司准入來源與授權規則：精確同 app OAuth 帳號、明確角色及範圍、授權者與理由、撤銷及稽核、可核實的有效狀態。不能只根據 bootstrap、角色字串或姓名相似放行。

私密匿名診斷回執：`.runtime/recovery-diagnosis-*.json`。工具 `.runtime/diagnose_cloud_recovery.py` 僅 SELECT 必要認定欄位與有效 session 的身分引用，未讀取 token，未輸出姓名／身分 ID，未進行任何業務寫入。
