# 獨立公司管理帳號核定與實作

使用者明確核定：「將 jekai 設為獨立公司管理帳號，綁定目前已驗證的 Lark 帳號並完整記錄授權。」此決策只授予已核實的單一帳號，不將所有 manager 或 bootstrap 管理員自動升為一般業務准入。不得修改薪資 Base 或以姓名猜測綁定。

伺服器設定 `LARK_COMPANY_ADMIN_GRANTS_JSON` 為授權陣列；每筆必須有 grant_id、精確 open_id、app_id、tenant、role=manager、enabled=true、authorized_at、authorized_by、reason、decision_ref，可選 expires_at。值僅置於私密部署設定，不寫入前端或本文件。重複身分、缺必要欄位、錯應用／公司、未生效／到期、停用授權均不採用。

一般同事仍依在職名冊及 15 分鐘新鮮度准入。独立管理員還必須符合 active=true、角色 manager、沒有 manager_revoked，並具正常 OAuth callback 保存的同 app／tenant／open_id user_info 證據。新部署後重新走正常登入取得證據；不得直接 patch PersonRow 為 normal。

`company_admin_grant` 每次依當前伺服器設定核對，不信任儲存的授權副本。移除或停用設定立即取消獨立准入；未另符合名冊者回到 recovery 或 denied。測試工作區不能覆蓋正式的停權／manager_revoked。OAuth 與正常身分讀取偵測授權套用或撤回，記錄 append-only action_audit，包含核定理由、來源與決策引用。

app 業務 API、交易內再次准入、worker actor gate 都採當前設定。Native approver／applicant／receipt checks 採載入當下由伺服器重算的精確管理員名單；既有 unknown 審批查回及取消清理不因登入者權限移除而停止觀測，但失效身分不能套用業務結果。此來源不建立人事／薪資列，也不自動認定班表或能力。

私密準備檔案：`.runtime/company-admin-approved-subject.json`、`.runtime/company-admin-env-fragment.json`。設定須由 root 以最新完整環境快照合併，不單獨以 delta 覆蓋整組 Zeabur 變數。授權時間記於私密 grant；截至本地驗證尚未宣稱正式 normal 登入完成。

本地測試覆蓋：正常 OAuth→normal→配置撤回→recovery、稽核新增/撤回、沒有名冊時授權不偽造名冊、錯人/錯app/錯tenant/缺OAuth證據/停權/撤權/重複/到期/未生效/缺理由等全部拒絕。相關 35 項測試通過；完整整合結果由部署紀錄另行列示。

完整 backend suite：858 passed（202.04 秒），紀錄 `.runtime/company-admin-full-suite.log`。另補 native poller 回歸：獨立管理授權撤回後仍以 GET 查回原審批，但回執不可套用業務結果；該組與授權測試共 23 passed。此新增回歸在上述完整套件收集後加入，結果分開記錄。

Worker hooks 收尾後，worker／Input／mention／native／admin 五組共 92 passed。再新增 production worker 的兩個端到端分支：有效獨立授權可外送、撤回授權後同一身分不可外送；獨立管理測試總計 18 passed。`LARK_NATIVE_APPROVAL_SUBMIT_ENABLED` 未因本授權功能自動開啟。

## 真實部署驗收

2026-09-29，完整 30 項 Zeabur 設定已套用並逐值讀回一致。最終部署 `6abb7a9cb57ea4921d62c57b` 為 RUNNING（08:46:08 UTC），後端整合測試 894 項通過，必要 SOP 資料檔已加入部署包並直接載入驗證。

已使用已驗證 jekai 帳號走正常 Lark OAuth，透過工作台正常 API 切回公司工作區：`/api/session` 200、access_mode=normal、role=manager；`/api/workspace` 200。正常 `/api/audit` 查到一筆本人獨立管理授權，含核定理由、決策來源、授權者及時間，salary_base_modified=false。Session 不暴露 oauth_identity 或 company_admin_authorization。未直接修改資料庫來繞過准入。

其他同事的應用可用範圍為「所有員工」，仍依個人在職名冊及角色判定；不代表每位同事都已完成實際登入驗收。人員／薪資 Base 未因本次管理帳號授權寫入。

第二眼再修兩點（供後續部署）：所有非 simulated 的真實外送都驗准入，不以 APP_ENV 跳過；company_admin_* 稽核沿用管理稽核隱私，普通同事不能讀別人的授權 metadata。development/production worker 授權撤回、一般員工 900/901 秒邊界、離職、偽造 profile 授權／test overlay、正常 member OAuth 後 audit 過濾均有回歸。相關 50 項與新增後獨立管理 22 項測試通過。

## 正常雲端登入最小驗收

1. 核對部署版本及完整 env 中私密精確 grant 已合併，維持 native submit 關閉；以原可見瀏覽器走正常 Lark OAuth，不手填 Cookie 或修改 PersonRow。
2. GET /api/session 應回 mode=lark、access_mode=normal、role=manager；不得回傳 oauth_identity 或 company_admin_authorization 私密欄位。GET /api/workspace 應 200。
3. 若初始在 test，以正常介面切到公司正式工作區。只讀 GET /api/audit?limit=100，核對本人的 company_admin_authorization 記錄有同一 actor、grant_id、app/tenant、核定者／理由／時間／決策引用，salary_base_modified=false。只回報布林與數量，不列姓名或 ID。
4. `.runtime/company-admin-live-acceptance.js` 是供瀏覽器 evaluate 的只讀彙總函式；不自行切工作區、不發審批、不寫資料。若 grant 記錄超過第一頁，讀取下一頁核對，不把第一頁缺少當成未記錄。
5. 實際撤回及停權不在 demo 中臨時切正式 env；本地回歸已驗正常→撤回→recovery/denied 與 worker 外送阻擋。要做正式撤回演練須另安排維運窗口，保存原設定並使用正常復原流程。
