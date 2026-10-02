# Drive 成果根目錄真實準備回執

2026-09-28 使用專用應用 `cli_aa3cab98b2789e17` 的 tenant 身分實測，未使用個人 CLI 身分或共享瀏覽器。

1. GET `/drive/explorer/v2/root_folder/meta` 成功取得該應用可存取根目錄。
2. GET `/drive/v1/files` 成功列出根目錄，沒有任何檔案及同名資料夾。
3. 依已核定成果存放需求，POST `/drive/v1/files/create_folder` 新建唯一「詠翔專案工作台成果」。
4. 以回傳 folder token 再 GET `/drive/v1/files`，成功讀回新資料夾清單。

私密回執 `.runtime/drive-root-preparation-20260928.json`，狀態 `created_readback_verified`，包含真實 folder token、URL、各步驟 API 回應；沒有儲存 access token 或 app secret。主代理應從此回執透過正常工作台設定保存根目錄，不另建立第二個同名資料夾。

沒有移動／刪除既有文件、沒有寫入任何 Base、沒有發送訊息。此結果證明根目錄建立及清單讀取成功，尚未代表成果檔案上傳與內容 hash 讀回已驗收。

官方依據：

- [取得根目錄元資訊](https://open.larksuite.com/document/ukTMukTMukTM/ugTNzUjL4UzM14CO1MTN/get-root-folder-meta)：tenant 與 user access token 均列為支援。
- [新建資料夾](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/file/create_folder)：使用已讀回的父資料夾 token；循序操作。
- [Drive 常見問題](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/faq)：存取個人資料夾需另外分享給含機器人的群組，本次專用應用根目錄實測可用，因此未改個人資料夾分享。
