# V4 未配對診斷

查證日期：2026-09-25。第一階段離線分析來源快取、metadata 與程式映射；後續加入瀏覽器原表核對與經授權的暫填案號唯讀配對。未修改 Lark Base。本文只列欄位、識別碼與統計，不列人員、案件名稱或金額。

## 已能確認的結論

日報未配對與填報工項未配對是兩個問題：

- 535 筆日報：API 已返回正確的原始 link 欄位，但其中案件與工項連結沒有 record_ids，text_arr 也全空。不是把有值的 record_ids 漏解包，也不是只投影公式而漏掉正式原始關聯。尚不能據此斷定 Base 內真正空白或 App 資料權限造成裁切。
- 218 筆填報工項：其案件值對上 15 個報價編號，每個報價編號有兩個不同報價 record。不是同一專案被重複加入 lookup；目前程式在選案前已按 project ID 去重。沒有合法依據任選其中一個。
- 另有 102 筆填報工項沒有可用案件值；其餘 280 筆已帶入來源工項。報價建立的 280 個來源案件不代表 280 個去重後的業務工程案號。

## 證據範圍

- `.runtime/live-source-debug.json`：新 App 使用者 token 的八表成功快取，共 2,446 筆。這是私密診斷快取，不作公開附件。
- `backend/evidence/v4-workflow-field-metadata.json`：當日已授權 CLI 查得的相關欄位設定，包含欄位 ID、型別及關聯目標。
- `deployment/source-tables.json`：實際投影字段。
- `backend/sources.py`：實際匹配規則。

metadata 檔保留的是關鍵欄位子集，外業原表共 131 欄、內業共 53 欄。本輪能確認投影包含正式 raw link，不能僅依子集排除所有其他舊備援欄位。第二身分 CLI 的 record 交叉讀取未完成，没有可比較的第二份 records；瀏覽器原表核對另行進行。

## 日報欄位是否選錯

以下均位於 V4 Base `H7W6b0PFWaVF1BsgqXJj3pQ9pXb`。

| 日報表／欄位 | field ID | 實際型別與來源 | 此次 API 結果 |
| --- | --- | --- | --- |
| 外業 tbl5zPLS0ExWNEty／所屬案件 | fldfpNpQiE | 雙向 link → 工程確認單 tblmSQrcCs9vPQZx；反向欄 flddfFq9zI | 187 筆全部無 record_ids、text_arr 空 |
| 外業／合約工項 | flduIbW1xZ | 雙向 link → 合約填報工項 tblwQPYk3c9RvCU7；反向欄 fldWSg0f8f | 187 筆全部無 record_ids、text_arr 空 |
| 外業／所屬成本單 | fldRekgGob | 雙向 link → 外業成本單 tbl8wRYCUCvbSoJG；反向欄 fldPqgElTB | 186 筆有 record_ids，1 筆空 |
| 外業／案件編號 | fld7FB7oaW | formula：IFERROR(FIRST([所屬案件].[所屬案件]),"") | 187 筆沒有返回欄位值 |
| 外業／明細所屬案件編號 | fld2zDDAYc | formula：IFERROR(FIRST([合約工項].[所屬案件]),"") | 未投影；仍依賴上述空合約工項，不能視為獨立原始連結 |
| 內業 tblrCo8KeZiuJUNh／所屬案件 | fld9yB8pCo | 單向 link → 工程確認單 tblmSQrcCs9vPQZx；描述為「取代舊案件表關聯」 | 348 筆全部無 record_ids、text_arr 空 |
| 內業／內業工項 | fldJwsE5yG | 單向 link → 合約填報工項 tblwQPYk3c9RvCU7；描述為正式新來源 | 348 筆全部無 record_ids、text_arr 空 |
| 內業／所屬成本單 | fldcnIsIhT | 雙向 link → 內業成本單 tblKwSDRg6WaGHYr；反向欄 fldhRlBkuF | 348 筆有 record_ids |
| 內業／案件編號 | fldMx2QEOd | formula：IFERROR(FIRST([所屬案件].[所屬案件]),"") | 348 筆沒有返回欄位值 |

正式案件、工項及成本單 link 都已在 field_names 投影中；關聯目標也都在八表設定內。案件／工項空關聯的結構為 `{table_id, type, text_arr: []}`。成本單有值的結構多出 `record_ids` 與 `text`；既有解析器可解析這種結構。

因此目前不是少設一張「工程總表」導致讀不到 link 目標。成本單可以供日期與組別判斷，但不能單獨證明該筆工作屬於哪個案件。舊備援關聯若有值，必須先確認遷移規則及與新確認單的穩定對應，不能直接跨 V3／V4 猜配。

## 218 筆工項的案號多義

逐筆按現有 import_sources 的規則重算，結果如下：

| 檢查 | 結果 |
| --- | --- |
| 受影響填報工項 | 218 筆 |
| 涉及不同報價編號 | 15 個 |
| 每個報價編號的不同 quote record 數 | 全部恰為 2 個 |
| 匹配來源 | 全部來自報價編號欄，沒有工程編號／報價編號跨欄碰撞 |
| 確認單 alias 轉換造成歧義 | 0；這 218 筆轉換前後值相同 |
| 同組工程名稱相同 | 15／15 組 |
| 同組工程編號相同 | 13／15 組；2 組不同 |
| 同組行號單位相同 | 14／15 組；1 組不同 |

這些相同欄位不足以判定哪筆作廢、哪筆為新版或是否可合併。此次最小投影沒有報價版本／有效狀態與可唯一綁定上游 record 的欄位，不能將相同名稱當主鍵。全報價表還存在 21 個重複工程編號及 41 個重複報價編號；本次 218 筆工項僅涉及其中 15 個報價編號。

工程確認單有 106 個非空 SourceID，但它們不等於現有快取中的 quote record ID 或工程／報價編號；尚未查證該欄來源契約，不據字串格式猜用途。

## 瀏覽器精確核對位置

1. 外業：table `tbl5zPLS0ExWNEty`，record `rec27XJ6JoxP6j`。比較「所屬案件」`fldfpNpQiE`、「合約工項」`flduIbW1xZ` 是否有可點開的連結；以有正常 API record_ids 的「所屬成本單」`fldRekgGob` 作對照。確認是否有其他舊案件／工項欄位仍有值。
2. 內業：table `tblrCo8KeZiuJUNh`，record `rec27XTgtoqFZG`。比較「所屬案件」`fld9yB8pCo`、「內業工項」`fldJwsE5yG` 及「所屬成本單」`fldcnIsIhT`；特別核對舊案件關聯是否尚未遷移。
3. 工項多義：table `tblwQPYk3c9RvCU7`，record `recvsrC9IguTm3`。其報價編號匹配報價表 `tblENZvYAya93Twa` 的 `recvs99lJ624pD` 與 `recvtieNVfGZWN`；報價 Base 是 `JoOqbggsVar0ATsVgbcjh6IIp1g`。核對兩筆是否為不同版本／分案、哪個欄位指定有效來源，以及確認單 SourceID 能否唯一指向其中一筆。

瀏覽器如果看到同一欄位確實有 link 而 App API 返回空值，下一步才針對該身分的欄位／資料可見範圍檢查；若原表也為空，則確認新舊關聯遷移或測試資料用途。兩種結論都須以實際核對結果支持。本輪不補造關聯、不變更來源、不修改 backend。

## 後續原表核對與有限配對

同日瀏覽器查看內業工作單 IW.377：正式「案件編號」「所屬案件」「內業工項」確實空白，但原始欄位「可能的確認單工編(若暫無確認單才需填寫)」有完整工編。至少此樣本可確認是原表正式關聯尚未建立，不能歸因於新 App 把有值的正式 link 隱藏。這一筆證據不推廣為全部 535 筆均同樣原因。

同日另抽查外業工作單 NO.391：「所屬案件」「合約工項」在原表也顯示新增記錄、無關聯，而成本單有值。兩個已核對樣本的正式链均在原表缺少連結；未找到已確認的外業暫填案號欄，因此不新增外業 fallback，也不將兩個樣本推廣為全部 535 筆。

經確認需求後，內業最小投影加入此原始暫填欄位。只有正式案號及 link 都空白時，才去除 Unicode 空白與不可見格式字元後，依完整案號做唯一匹配；保留案號後綴，不模糊比對名稱，不任選重複報價 record，也不覆蓋未知或衝突的正式關聯。已配對者保留 `source_case_code` 原值、`match_basis=provisional_case_code`，顯示「來源待核對」，僅提供日期＋組別＋案號的作業證據。這不代表 V4 正式 link 已修復，不自動完成任務，不寫回 Base。

上述變更部署後已完成真實同步：HTTP 200、ready、gzip，耗時 33.869 秒；八表仍共 2,446 筆，建立 280 案件及 280 個來源工項。日報統計為 daily_imported=1、daily_provisional=1、daily_unmatched=534、daily_missing_date=0、daily_missing_department=0。這 1 筆由完整暫填案號唯一配對提供作業證據，正式 link 並未修復；現在不能再說 535 筆全部未配對。外業暫填欄仍未確認，沒有套用。

日期與組別缺漏統計只涵蓋已匯入日報，不證明 534 筆未配對紀錄也通過檢核。快取中 414 筆成本單的工作日期範圍為 2026-07-01 至 2026-08-11；僅記錄可見資料的日期事實，不據此判定 V4 是否正式啟用。
