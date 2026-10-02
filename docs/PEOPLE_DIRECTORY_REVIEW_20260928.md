# 人員名冊實際核對（2026-09-28）

以 Lark Base 唯讀查詢「人員名單及資料」核定四欄：姓名、人員、在職、內外勤。69 筆完整讀取、`has_more=false`；未讀薪資、銀行或能力欄位，未修改來源。此補查使用 CLI user，只核對帳號欄有無值與在職 checkbox，不拿另一應用的 ID 來比對工作台身分。

| 原生人員帳號 | 在職 | 離職 | 合計 |
| --- | ---: | ---: | ---: |
| 有帳號 | 61 | 2 | 63 |
| 缺帳號 | 1 | 5 | 6 |
| 合計 | 62 | 7 | 69 |

工作台的 `valid_people=63` 是63筆有唯一可識別帳號，不代表63人在職；`explicit_left=2` 僅是這63筆中的離職人員。全部名冊共有7筆在職checkbox為false，其中5筆沒有帳號。不能把6筆 `missing_account` 全部描述為在職資料錯誤。

需公司核對的實際事項：1筆在職人員缺少原生「人員」欄帳號，需由公司確認並填入正確帳號後再同步；5筆已離職缺帳號保留歷史即可，不能按姓名猜配或自動建立可登入身分。是否補歷史帳號屬資料整理，不是授予登入權限。

程式核對：`merge_directory` 只以原生 ID 匹配，名字只更新顯示。明確離職且有帳號時停權；既有停權不因重新在職自動恢復；同名不同 ID 保留不同人。缺漏原帳號會標 `directory_missing`，一般名冊准入檢查拒絕它；明示 bootstrap 管理員另依既有核定例外，不能將其等同一般名冊准入。

修正診斷缺口：原 `fetch_directory` 在缺帳號時提前跳出，因此沒有保留該筆在職狀態。現在先嚴格解析 boolean checkbox，於 missing_account／multiple_accounts／missing_name issue 附上 `employment_status`；不變更匹配、停權或核准規則，也不以字串 `false`／數字 0 假裝有效離職值。

回歸：`python -B -m pytest backend/test_people_directory.py backend/test_production_access.py -q` → **43 passed in 7.35s**。新增涵蓋在職／離職／未知且缺帳號、同名不可配對、既有人員保留並標缺漏、不可藉缺帳號猜測停用別人。

聚合回執：`.runtime/roster-missing-accounts-summary-20260928.json`。原始四欄資料僅在私密 `.runtime` 保存，本文不列名字或帳號。正式同步仍可維持 `review_required`，不應為了顯示綠燈清掉歷史資料或忽略那1筆在職缺帳號。
