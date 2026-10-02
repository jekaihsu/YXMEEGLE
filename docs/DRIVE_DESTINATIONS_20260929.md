# 獨立 Drive 目的地與權限驗收

本輪依核定計畫，以專用 app `cli_aa3cab98b2789e17` 的隔離 CLI profile 新增兩個根目錄；沒有改動既有檔案、來源 Base 或正式附件根目錄。

| 用途 | 根目錄 token | 建立／讀回 | 尚待事項 |
|---|---|---|---|
| 隔離測試附件 | RgONfc9uylFv2MdiS1ujQNkopSb | 正常上傳、自動排程、遠端下載雜湊核實通過 | 其他檔案類型／失敗情境仍依各自驗收 |
| 加密備份（維運專用） | S6lqfyItLlr42OdCidWjgkLEpic | create 成功，permission setting 可讀 | 私密 ACL 完整核實、公司保管金鑰、持久 volume、排程及加密回存驗收 |

建立時回執 `permission_grant.status=skipped`。使用者後續明確核定 jekai 為獨立公司管理帳號後，已將該精確已驗證身分加入兩個新 Drive 根目錄及兩個 Input Base，full_access 回讀相同；未轉移 owner，未開放給全公司。

備份根目錄自身設定讀回：`link_share_entity=closed`；`external_access_entity=open`、`share_entity=anyone` 等為分享政策，不能單憑此推斷已有外部協作者或完全私密。`drive +member-list --type folder` 真實回 code 99992402 / field validation failed，為目前環境之資料夾成員 API 支援限制，未以其他資源類型冒充 folder。

目前尚未设置 `BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED=true`，未啟用異地排程，未上傳業務備份到新目錄。需要可支援的權限介面核對目前協作者與受控分享範圍後才可啟用。

後續在專用備份資料夾 UI 已關閉「允許將資料夾分享到組織外」，重新讀取核取狀態確認未勾選；連結仍為未開啟／僅協作者可存取。上述 API 初始設定並非修改後快照；完整協作者與其他分享政策仍未驗收，不據此啟用備份。

## 隔離附件真實驗收

2026-09-29，正常 jekai manager／test session 使用 `/api/files` 上傳 64 bytes 標示隔離測試的文字檔。系統自動產生 `file:fe1bea22e20b41358e5f0752ccc00b6b` 工作，正常 worker 執行為 succeeded。附件 remote_status=verified，remote_receipt simulated=false、remote_mode=isolated_live、destination_root 等於專用测试根目錄。原始內容 SHA256 `1cb8b4e035a16ae2728b026d61523370d712f045ad14f03cadcc02753e6aba14` 與 adapter 上傳後下載核實及本地下載 SHA256 相同，下載 HTTP 200。正式附件根目錄、來源及薪資 Base 未寫入。

私密原始回執與防重建 checkpoint：`.runtime/lark-input-cli/{test,backup}-drive-*`。建立結果未知時不可盲重建；本次二目錄皆已取得唯一 token，可直接沿用。
