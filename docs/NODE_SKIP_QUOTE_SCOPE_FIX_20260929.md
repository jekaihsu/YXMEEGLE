# 節點跳過：報價工作範圍修正

獨立全測試發現 v2 skip scope 排除整份 quotes 後，來源「確認範圍」變更不使原跳過核准失效。修正為 approval_scope.quote_work_scope：只投影工作語意白名單（確認範圍、工程內容、工作項目、數量／單位、工項與確認單關聯、工期與交付內容），不投影成本及同步時間。沒有工作語意欄位的成本鏡像不納入。

node_skip v2 納入該投影；不修改 v1 快照算法。來源工作範圍改變，即使本地任務 revision 未變，仍須重新申請。來源列排列不同不影響核准；新增／刪除具有工作內容的列會影響核准。

既有 v2 雜湊不偷偷重算：升級後可能失效，須重新申請；原有核准人、投票及回執不重新簽造。v1 成本變更仍按舊算法影響 scope。

相關 74 項測試通過：test_node_skip_scope、test_node_skip、test_second_review、test_native_scope_semantics。包含原本失敗的 test_quote_scope_change_invalidates_existing_waiver 與新增 9 項成本／語意欄位／來源列增刪／v1 回歸測試。Frontend 與遠端未變。

完整 `python -m pytest backend -q`：828 passed，95.98 秒。
