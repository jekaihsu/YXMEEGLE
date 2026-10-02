# 專用 Lark 審批表 UI 設定與映射（2026-09-28）

官方管理入口：[審批管理後台](https://www.larksuite.com/approval/admin/approvalList?devMode=on)。來源為已保存官方 `.runtime/approval-official-definition_create.md`。使用 UI 建表；不使用有不可刪停限制的 API create definition。

## 共通表單設定

目前程式最小可驗證契約為兩個「多行文字」控件，型別在 GET 應回傳 `textarea`：

| 顯示名稱 | logical key | 值由誰填入 |
| --- | --- | --- |
| 工作台綁定資料 | binding | 後端填入案件、申請、版本、scope 綁定資料 |
| 申請內容 | content | 後端填入本次申請內容快照 |

兩個欄位必填；請勿添加金額、附件、日期、人員控件後就直接啟用映射，因現行 verifier 要求表單全部欄位与 mapping 完全一致，僅支持 input/textarea。若 UI 能設定不可被核准人修改，設為唯讀；修改內容會使查回驗證失敗，不能讓核准後變更原送審內容。

這是服務的最小技術契約，不是最終審批閱讀體驗：目前 content 是 JSON 序列化字串，後續應改善可讀摘要，不能把機器 JSON 當成已完成的專業表單呈現。

## 四張表與流程

| UI 表單名稱 | kind | 審批節點與 seats | 狀態 |
| --- | --- | --- | --- |
| 詠翔專案工作台－節點跳過 | node_skip | 一個「PM 與該組主管確認」多人 AND 節點；seats `["pm","supervisor"]` | 符合已核定規則，可建立，映射前核對真實 ID |
| 詠翔專案工作台－財務交付確認 | financial | 一個「PM 與行政確認」多人 AND 節點；seats `["pm","admin"]` | 確認交付證據，不修改帳務，也不代表款項結清 |
| 詠翔專案工作台－期限展延 | extension | 一個「主管確認」AND 節點；seats `["supervisor"]` | 依既有 PRD／契約主管確認；跨組主管及節點關聯必須可核實，缺人阻擋 |
| 詠翔專案工作台－設計變更 | change | PM 與該組主管 AND；exact seats `["pm","supervisor"]` | **2026-09-28 使用者已核定**；另外兩線主管本人確認、業主佐證仍獨立保留 |

設計變更可按已核定 PM 與該組主管共同核准建立表單，不要求業主 Lark 帳號，也不把同事改稱業主。兩席必須為不同的實際人員，不接受多加、替換、缺少或重複席次。

每個核准節點須採「由發起人自選／Free」，讓服務以 `node_approver_open_id_list` 指定案件實際人員。GET 回傳必須同時满足：

- `node_type="AND"`。
- `need_approver=true`。
- 同節點兩席時 `approver_chosen_multi=true`。
- 審批開始／結束之外只包含映射中的核准節點，不要額外條件、抄送或其他節點後忽略。
- 不自動通過發起人、不同節點同人、不去重；每席都需要本人實際 PASS。
- 不使用或依賴轉交、加減簽、自動通過、退回後另行跳轉；這些軌跡會使本服務拒絕將該單當成原定人員全數核准。

建立與啟用後，GET `/approval/v4/approvals/{approval_code}?user_id_type=open_id`，確認 `status="ACTIVE"`、表單 id/name/type、node_list 真實 node_id。不要從 UI 名稱拼出 ID。

## 服務映射模板

下例所有尖括號都是**尚未核實的佔位符，禁止直接放入正式環境**。每一 kind 均需獨立真實 approval_code 與欄位／節點 ID。

```json
{
  "node_skip": {
    "kind": "node_skip",
    "approval_code": "<GET 核實的跳過定義 code>",
    "fields": {
      "binding": {"id": "<綁定欄位 id>", "name": "工作台綁定資料", "type": "textarea"},
      "content": {"id": "<內容欄位 id>", "name": "申請內容", "type": "textarea"}
    },
    "nodes": [{"id": "<核准 node_id>", "seats": ["pm", "supervisor"]}]
  }
}
```

驗證真實 definition 與 mapping：呼叫 `backend.native_approval.verify_definition(definition, mapping)`，純本地核對不會提單。通過後才併入伺服器 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON`。

不得設定只有 title/code 的舊式 `LARK_CHANGE_APPROVAL_CODE` 等變數就宣稱已接好；目前服務實際讀取上述 JSON mapping。

## 送出前還需要

專用 app instance scope 發布有效、正確正式工作區、已核實在職申請人及不同席次人員、案件責任人完整、內容版本未變；財務文件已讀回驗證。所有真實提單須留下 UUID 持久化 checkpoint，核准必須由實際人員完成，本代理不代人核准。

最小定義可讀測試與 UI 建表本身，均不能當作「已完成真實兩人審批」。

設計變更第三線核准角色已由使用者決定為「PM＋該組主管共同核准」。主管本人確認與業主佐證是另外兩線，不因同一主管完成 Lark 內審而自動代為完成。2026-09-28 針對最新規則的 native／三線測試 **67 項通過**。

## 真實定義查回核實（2026-09-28 23:07 台北）

主代理透過管理 UI 建立並發布四張表，本代理用專用 app application token 唯讀 GET 後跑 `verify_definition`，四張全數 ACTIVE／通過。**沒有發起實例、傳訊或代人核准。**

| kind | 真實 approval_code | 核准 seats |
| --- | --- | --- |
| node_skip | 22DB5586-DE90-4481-9975-F413BB5E05C8 | pm + supervisor |
| financial | 96D0C600-ADB9-4ABB-B603-553E5273527F | pm + admin |
| extension | C09D9A15-DD76-43D9-A1DC-B91513D600F0 | supervisor |
| change | 9CE5E901-E128-478C-A505-33613592A08C | pm + supervisor |

私有完整設定：`.runtime/native-approval-mappings-20260928.json`，可供 root 設為 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON`；驗證 receipt：`.runtime/native-definitions-verified-20260928.json`。真實 form.id/node_id 已從 GET 取得，沒有將 Custom ID 當成實際 ID。

UI 定義回傳的起點／終點沒有 START/END custom ID，而是 hash node_id。mapping 現加 `boundary_nodes.start/end={id,name}`，綁定已核對管理 UI 的 Submit／End 真實 ID；verifier 同時要求 name、AND、need_approver=false、empty_assignee_list=[]、require_signature=false、無 custom ID。不能自動忽略任意 need_approver=false，也不能靠 custom_id=START 跳過流程檢查。注入隱藏固定審批／偽 START 或變更 boundary ID／型別的測試均拒絕；最新 native／三線 **68 項通過**。

定義查回成功只證明表單與流程契約。部署配置、有效登入與真實指定人員提單／核准仍須各自驗收。
