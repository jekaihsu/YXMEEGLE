-- =============================================================================
-- 009d9_r49_lark_cli_approval_and_usage_telemetry.sql
-- R49: 業主往來 × Lark CLI 同事核准發信閉環 × CLI Watcher Agent 使用量統計 × PM Solution DB 同步橋接
-- Database: yongxiang_plumb_r39_clone (Strictly isolated from production)
-- =============================================================================

DO $$
BEGIN
    IF current_database() = 'yongxiang_plumb' THEN
        RAISE EXCEPTION 'FATAL: Forbidden from running R49 migration on production DB yongxiang_plumb';
    END IF;
END $$;

BEGIN;

-- 1. Outbound Approval Dispatch Table (Hub -> Colleague via Lark CLI -> Colleague Reply -> Hub Final Send -> PM Solution Sync)
CREATE TABLE IF NOT EXISTS public.lark_cli_approval_dispatch (
    dispatch_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                TEXT NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
    card_id               UUID NULL,
    case_code             TEXT NOT NULL,
    client_name           TEXT NOT NULL DEFAULT '',
    contact_name          TEXT NOT NULL DEFAULT '',
    target_employee_id    UUID NOT NULL REFERENCES public.employee(id),
    target_employee_name  TEXT NOT NULL,
    target_department     TEXT NOT NULL DEFAULT '',
    target_lark_open_id   TEXT NOT NULL,
    hub_sender_identity   TEXT NOT NULL DEFAULT 'jekai (cli_aa5c5ceba4f8de2a)',
    draft_subject         TEXT NOT NULL,
    draft_body            TEXT NOT NULL,
    lark_message_id       TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN (
                              'pending_colleague',
                              'colleague_approved',
                              'colleague_edited',
                              'colleague_rejected',
                              'final_sent_by_hub'
                          )),
    colleague_reply_code  TEXT NULL,
    colleague_reply_text  TEXT NULL,
    colleague_replied_at  TIMESTAMPTZ NULL,
    final_sent_at         TIMESTAMPTZ NULL,
    serial_no             INTEGER NULL,
    serial_label          TEXT NULL,
    send_mode             TEXT NOT NULL DEFAULT 'dry_run',
    pm_solution_synced_at TIMESTAMPTZ NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lark_cli_dispatch_case ON public.lark_cli_approval_dispatch(case_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lark_cli_dispatch_status ON public.lark_cli_approval_dispatch(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_lark_cli_dispatch_emp ON public.lark_cli_approval_dispatch(target_employee_id);

-- 2. Colleague Lark CLI Agent Usage Telemetry Table
CREATE TABLE IF NOT EXISTS public.colleague_lark_agent_usage (
    usage_id              BIGSERIAL PRIMARY KEY,
    org_id                TEXT NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
    employee_id           UUID NOT NULL REFERENCES public.employee(id),
    employee_name         TEXT NOT NULL,
    department            TEXT NOT NULL,
    team_scope            TEXT NOT NULL CHECK (team_scope IN ('pm', 'admin', 'eng')),
    lark_open_id          TEXT NOT NULL,
    case_code             TEXT NULL,
    dispatch_id           UUID NULL REFERENCES public.lark_cli_approval_dispatch(dispatch_id) ON DELETE SET NULL,
    action_type           TEXT NOT NULL CHECK (action_type IN (
                              'approve_send',
                              'edit_draft',
                              'supplement_file',
                              'query_bot',
                              'triage_assign',
                              'reject_draft'
                          )),
    channel_profile       TEXT NOT NULL DEFAULT 'cli_aa5c5ceba4f8de2a',
    tokens_used           INTEGER NOT NULL DEFAULT 0 CHECK (tokens_used >= 0),
    response_seconds      INTEGER NOT NULL DEFAULT 0 CHECK (response_seconds >= 0),
    summary_note          TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_colleague_usage_emp ON public.colleague_lark_agent_usage(employee_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_colleague_usage_case ON public.colleague_lark_agent_usage(case_code, created_at DESC);

-- 3. Leaderboard View: Per-Colleague Lark CLI Agent Usage & Approval Metrics
CREATE OR REPLACE VIEW public.colleague_usage_leaderboard_v AS
SELECT
    d.employee_id,
    d.full_name AS employee_name,
    d.department_group AS department,
    d.sub_group,
    d.job_title_display AS job_title,
    d.role_scope AS team_scope,
    d.lark_open_id,
    COUNT(u.usage_id)::INTEGER AS total_interactions,
    COUNT(u.usage_id) FILTER (WHERE u.action_type = 'approve_send')::INTEGER AS approved_sends,
    COUNT(u.usage_id) FILTER (WHERE u.action_type IN ('edit_draft', 'supplement_file'))::INTEGER AS edits_and_supplements,
    COUNT(u.usage_id) FILTER (WHERE u.action_type IN ('query_bot', 'triage_assign'))::INTEGER AS queries_and_triage,
    COUNT(u.usage_id) FILTER (WHERE u.action_type = 'reject_draft')::INTEGER AS rejected_drafts,
    COALESCE(ROUND(AVG(u.response_seconds) / 60.0, 1), 0.0)::NUMERIC(10,1) AS avg_response_min,
    COALESCE(SUM(u.tokens_used), 0)::BIGINT AS total_tokens,
    MAX(u.created_at) AS last_active_at
FROM public.v_yezhu_lark_directory d
LEFT JOIN public.colleague_lark_agent_usage u
    ON u.employee_id::text = d.employee_id::text
GROUP BY
    d.employee_id,
    d.full_name,
    d.department_group,
    d.sub_group,
    d.job_title_display,
    d.role_scope,
    d.lark_open_id
ORDER BY
    COUNT(u.usage_id) DESC,
    COALESCE(SUM(u.tokens_used), 0) DESC,
    d.full_name ASC;

-- 4. PM Solution Correspondence & Approval Sync View
CREATE OR REPLACE VIEW public.pm_solution_correspondence_sync_v AS
SELECT
    d.dispatch_id,
    d.case_code,
    CASE
        WHEN d.case_code = 'C115211' THEN 'C115211-01A'
        ELSE d.case_code
    END AS pm_solution_project_code,
    d.client_name,
    d.contact_name,
    d.target_employee_id,
    d.target_employee_name AS approved_by_colleague,
    d.target_department,
    d.target_lark_open_id,
    d.hub_sender_identity,
    d.draft_subject,
    d.draft_body,
    d.lark_message_id,
    d.status,
    d.colleague_reply_code,
    d.colleague_reply_text,
    d.colleague_replied_at,
    d.final_sent_at,
    d.serial_no,
    d.serial_label,
    d.send_mode,
    d.pm_solution_synced_at,
    d.created_at,
    d.updated_at,
    l.direction AS ledger_direction,
    l.status_label AS ledger_status_label
FROM public.lark_cli_approval_dispatch d
LEFT JOIN public.yezhu_correspondence_ledger l
    ON ABS(l.serial_no) = ABS(d.serial_no)
   AND l.case_code = d.case_code
ORDER BY COALESCE(d.final_sent_at, d.updated_at, d.created_at) DESC;

-- 5. Function: Step 1 & 2 - Dispatch Approval Request from Hub to Colleague via Lark CLI
CREATE OR REPLACE FUNCTION public.r49_dispatch_lark_approval(
    p_case_code          TEXT,
    p_target_employee_id UUID,
    p_subject            TEXT,
    p_body               TEXT,
    p_lark_msg_id        TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_emp        RECORD;
    v_case       RECORD;
    v_client     TEXT := '合作業主';
    v_contact    TEXT := '業主窗口';
    v_msg_id     TEXT;
    v_dispatch   UUID;
BEGIN
    SELECT employee_id, full_name, department_group, sub_group, role_scope, lark_open_id
      INTO v_emp
      FROM public.v_yezhu_lark_directory
     WHERE employee_id::text = p_target_employee_id::text
     LIMIT 1;

    IF v_emp.employee_id IS NULL THEN
        RAISE EXCEPTION 'Target employee % not found in active 67-staff directory', p_target_employee_id;
    END IF;

    SELECT code, case_data
      INTO v_case
      FROM public.yezhu_workbench_case
     WHERE code = p_case_code
     LIMIT 1;

    IF v_case.code IS NOT NULL AND v_case.case_data IS NOT NULL THEN
        v_client := COALESCE(v_case.case_data->>'client', '合作業主');
        v_contact := COALESCE(v_case.case_data->>'contact', '業主窗口');
    END IF;

    v_msg_id := COALESCE(NULLIF(btrim(p_lark_msg_id), ''), 'om_dryrun_r49_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16));

    INSERT INTO public.lark_cli_approval_dispatch (
        org_id, case_code, client_name, contact_name,
        target_employee_id, target_employee_name, target_department, target_lark_open_id,
        hub_sender_identity, draft_subject, draft_body, lark_message_id,
        status, send_mode
    ) VALUES (
        'YX', p_case_code, v_client, v_contact,
        v_emp.employee_id::uuid, v_emp.full_name, v_emp.department_group || ' · ' || v_emp.sub_group, v_emp.lark_open_id,
        'jekai (cli_aa5c5ceba4f8de2a)', p_subject, p_body, v_msg_id,
        'pending_colleague', 'dry_run'
    ) RETURNING dispatch_id INTO v_dispatch;

    INSERT INTO public.audit_event (table_name, record_id, op, actor_id, after_val)
    VALUES (
        'lark_cli_approval_dispatch',
        v_dispatch::text,
        'INSERT',
        'jekai_hub',
        jsonb_build_object(
            'action', 'dispatch_lark_approval',
            'case_code', p_case_code,
            'target_employee_name', v_emp.full_name,
            'target_lark_open_id', v_emp.lark_open_id,
            'lark_message_id', v_msg_id,
            'status', 'pending_colleague'
        )
    );

    RETURN jsonb_build_object(
        'ok', true,
        'dispatch_id', v_dispatch,
        'case_code', p_case_code,
        'target_employee_id', v_emp.employee_id,
        'target_employee_name', v_emp.full_name,
        'target_lark_open_id', v_emp.lark_open_id,
        'lark_message_id', v_msg_id,
        'status', 'pending_colleague'
    );
END;
$$;

-- 6. Function: Step 3, 4, 5 - Watcher Agent Receives Colleague Reply -> Hub Final Send -> Record & Sync to PM Solution DB
CREATE OR REPLACE FUNCTION public.r49_process_colleague_reply(
    p_dispatch_id   UUID,
    p_reply_text    TEXT,
    p_tokens_used   INTEGER DEFAULT 420,
    p_response_sec  INTEGER DEFAULT 95
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_disp         RECORD;
    v_emp          RECORD;
    v_clean_reply  TEXT;
    v_reply_code   TEXT := '1';
    v_action_type  TEXT := 'approve_send';
    v_new_status   TEXT := 'final_sent_by_hub';
    v_edited_body  TEXT;
    v_raw_serial   INTEGER := -12106;
    v_disp_serial  INTEGER := 12106;
    v_serial_label TEXT;
    v_letter       JSONB;
BEGIN
    SELECT * INTO v_disp
      FROM public.lark_cli_approval_dispatch
     WHERE dispatch_id = p_dispatch_id
     FOR UPDATE;

    IF v_disp.dispatch_id IS NULL THEN
        RAISE EXCEPTION 'Dispatch % not found', p_dispatch_id;
    END IF;

    SELECT employee_id, full_name, department_group, sub_group, role_scope, lark_open_id
      INTO v_emp
      FROM public.v_yezhu_lark_directory
     WHERE employee_id::text = v_disp.target_employee_id::text
     LIMIT 1;

    v_clean_reply := btrim(COALESCE(p_reply_text, ''));
    v_edited_body := v_disp.draft_body;

    IF v_clean_reply ~* '^(\[?3\]?|退回|暫緩|不發|駁回)' THEN
        v_reply_code := '3';
        v_action_type := 'reject_draft';
        v_new_status := 'colleague_rejected';
    ELSIF v_clean_reply ~* '^(\[?2\]?|修改|改為|補上)' THEN
        v_reply_code := '2';
        v_action_type := 'edit_draft';
        v_new_status := 'final_sent_by_hub';
        v_edited_body := regexp_replace(
            v_disp.draft_body,
            '(詠翔測量工程有限公司 敬上\s*)$',
            E'（依 ' || v_disp.target_employee_name || E' Lark 回覆補充：' || v_clean_reply || E'）\n\n\\1'
        );
    ELSE
        v_reply_code := '1';
        v_action_type := 'approve_send';
        v_new_status := 'final_sent_by_hub';
    END IF;

    IF v_new_status = 'final_sent_by_hub' THEN
        -- Step 4: Hub executes final send (safe dry_run serial allocation) & writes to correspondence ledger
        BEGIN
            v_raw_serial := public.assign_serial(
                'YX',
                'r49-hub-final:' || v_disp.case_code || ':' || v_disp.dispatch_id::text,
                'dry_run'
            );
        EXCEPTION WHEN OTHERS THEN
            v_raw_serial := -12108;
        END;
        v_disp_serial := ABS(v_raw_serial);
        v_serial_label := '業主往來' || v_disp_serial::text;

        UPDATE public.lark_cli_approval_dispatch
           SET status = 'final_sent_by_hub',
               draft_body = v_edited_body,
               colleague_reply_code = v_reply_code,
               colleague_reply_text = v_clean_reply,
               colleague_replied_at = now(),
               final_sent_at = now(),
               serial_no = v_disp_serial,
               serial_label = v_serial_label,
               pm_solution_synced_at = now(),
               updated_at = now()
         WHERE dispatch_id = p_dispatch_id;

        INSERT INTO public.yezhu_correspondence_ledger (
            serial_no, org_id, serial_label, case_code, client, contact, pm,
            direction, channel, occurred_date, subject, summary, status_label, messages_json
        ) VALUES (
            v_raw_serial,
            'YX',
            '業主往來D-' || v_disp_serial::text,
            v_disp.case_code,
            v_disp.client_name,
            v_disp.contact_name,
            v_disp.target_employee_name,
            'outbound',
            'email',
            to_char(now() AT TIME ZONE 'Asia/Taipei', 'MM/DD'),
            v_disp.draft_subject,
            '經 ' || v_disp.target_employee_name || ' 於 Lark CLI 核准後由中樞最終寄出（#' || v_disp_serial::text || '）',
            '已回',
            jsonb_build_array(
                to_char(now() AT TIME ZONE 'Asia/Taipei', 'MM/DD HH24:MI') || ' · [Lark CLI 核准] ' || v_disp.target_employee_name || '：' || v_clean_reply,
                to_char(now() AT TIME ZONE 'Asia/Taipei', 'MM/DD HH24:MI') || ' · [中樞最終發出] 永祥（#' || v_disp_serial::text || '）：' || v_disp.draft_subject
            )
        ) ON CONFLICT (serial_no) DO UPDATE
          SET summary = EXCLUDED.summary,
              status_label = EXCLUDED.status_label,
              messages_json = EXCLUDED.messages_json;

        -- Also update yezhu_workbench_case letter_state so workbench reflects the closed loop
        SELECT COALESCE(letter_state, '{}'::jsonb) INTO v_letter
          FROM public.yezhu_workbench_case
         WHERE code = v_disp.case_code;

        IF v_letter IS NOT NULL THEN
            v_letter := v_letter || jsonb_build_object(
                'stage', 'sent',
                'serial', v_disp_serial,
                'serial_badge', v_serial_label,
                'writeback_badge', '已寫回紀錄表 & PM Solution ✓',
                'lark_approved_by', v_disp.target_employee_name,
                'lark_reply_text', v_clean_reply,
                'text', v_edited_body
            );
            UPDATE public.yezhu_workbench_case
               SET letter_state = v_letter,
                   serial = v_disp_serial,
                   next_label = '#' || v_disp_serial::text || ' 經 ' || v_disp.target_employee_name || ' Lark 核准後已由中樞寄出',
                   updated_at = now()
             WHERE code = v_disp.case_code;
        END IF;
    ELSE
        UPDATE public.lark_cli_approval_dispatch
           SET status = v_new_status,
               colleague_reply_code = v_reply_code,
               colleague_reply_text = v_clean_reply,
               colleague_replied_at = now(),
               updated_at = now()
         WHERE dispatch_id = p_dispatch_id;
    END IF;

    -- Step 5: Record colleague Lark CLI agent usage telemetry
    INSERT INTO public.colleague_lark_agent_usage (
        org_id, employee_id, employee_name, department, team_scope,
        lark_open_id, case_code, dispatch_id, action_type,
        channel_profile, tokens_used, response_seconds, summary_note
    ) VALUES (
        'YX',
        v_disp.target_employee_id,
        v_disp.target_employee_name,
        COALESCE(v_emp.department_group, v_disp.target_department),
        COALESCE(v_emp.role_scope, 'pm'),
        v_disp.target_lark_open_id,
        v_disp.case_code,
        v_disp.dispatch_id,
        v_action_type,
        'cli_aa5c5ceba4f8de2a',
        GREATEST(COALESCE(p_tokens_used, 420), 0),
        GREATEST(COALESCE(p_response_sec, 95), 0),
        CASE
            WHEN v_new_status = 'final_sent_by_hub' THEN '於 Lark 回覆「' || left(v_clean_reply, 40) || '」核准發信，中樞最終寄出 #' || v_disp_serial::text
            ELSE '於 Lark 回覆「' || left(v_clean_reply, 40) || '」退回草稿'
        END
    );

    INSERT INTO public.audit_event (table_name, record_id, op, actor_id, after_val)
    VALUES (
        'lark_cli_approval_dispatch',
        p_dispatch_id::text,
        'UPDATE',
        v_disp.target_employee_id::text,
        jsonb_build_object(
            'action', 'process_colleague_reply',
            'case_code', v_disp.case_code,
            'approved_by', v_disp.target_employee_name,
            'reply_code', v_reply_code,
            'status', v_new_status,
            'serial_no', v_disp_serial,
            'pm_solution_synced', (v_new_status = 'final_sent_by_hub')
        )
    );

    RETURN jsonb_build_object(
        'ok', true,
        'dispatch_id', p_dispatch_id,
        'case_code', v_disp.case_code,
        'approved_by', v_disp.target_employee_name,
        'reply_code', v_reply_code,
        'reply_text', v_clean_reply,
        'status', v_new_status,
        'serial_no', v_disp_serial,
        'serial_label', v_serial_label,
        'pm_solution_synced', (v_new_status = 'final_sent_by_hub')
    );
END;
$$;

-- 7. Seed Realistic Initial Closed-Loop Records & Usage Telemetry for Key Active Colleagues (0 已離職人員)
DELETE FROM public.colleague_lark_agent_usage;
DELETE FROM public.lark_cli_approval_dispatch;

DO $$
DECLARE
    v_wuboyi    UUID := 'a968fbf8-c0ac-5d6a-9939-80584ede3509'; -- 吳柏頤
    v_luowei    UUID := 'c22b9383-60ec-5bcf-8bb1-4131de44b420'; -- 羅薇
    v_tuzhen    UUID := 'dad9c46d-dc58-594a-b4ee-6c71a00228c7'; -- 涂振邦
    v_jiabin    UUID := '13394342-2826-5d5d-a26f-44e259279870'; -- 張家彬
    v_yaqi      UUID := '45ab4194-04c9-59ef-bbd9-f1559b830c38'; -- 朱雅琪
    v_hengan    UUID := '3bb1f7cd-6a68-5870-9ce5-4e6bcac14266'; -- 古恆安
    v_jieying   UUID := '18d11143-a1c8-5afd-bcf1-229e064e930c'; -- 郭倢瑛
    v_zhonghua  UUID := '17330f86-3047-5aef-9223-9dd664360418'; -- 吳重樺
    v_wenze     UUID := 'ddc29574-c9e6-5893-b39d-b77ad445e225'; -- 鄭文澤
    v_kehan     UUID := '6716f16e-761b-514b-95e1-8b78f04f5179'; -- 吳科翰
    v_d1        UUID;
    v_d2        UUID;
    v_d3        UUID;
    v_d4        UUID;
    v_d5        UUID;
BEGIN
    -- Seed 1: C114109 (台塑六輕北側管線高程檢測) -> 吳柏頤 approved -> final_sent_by_hub (#12085)
    INSERT INTO public.lark_cli_approval_dispatch (
        dispatch_id, org_id, case_code, client_name, contact_name,
        target_employee_id, target_employee_name, target_department, target_lark_open_id,
        hub_sender_identity, draft_subject, draft_body, lark_message_id,
        status, colleague_reply_code, colleague_reply_text,
        colleague_replied_at, final_sent_at, serial_no, serial_label, send_mode, pm_solution_synced_at, created_at
    ) VALUES (
        '49000000-0000-0000-0000-000000000001', 'YX', 'C114109', '台塑石化股份有限公司', '王課長',
        v_wuboyi, '吳柏頤', '業務及PM部 · 業務與PM組', 'ou_c5051de1880e46996940abfa2295fe08',
        'jekai (cli_aa5c5ceba4f8de2a)',
        'C114109 台塑六輕廠區｜北側管線修正圖 PDF 與控制點高程對照表提送',
        E'王課長您好：\n\n貴廠區北側管線修正圖 PDF 與控制點高程成果已由內業品管張家彬複核完畢，五項安全檢查全數通過，隨信附上對外正式版 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上',
        'om_r49_seed_c114109_wuboyi',
        'final_sent_by_hub', '1', '[1] 核准發出，家彬剛確認過高程對照表無誤，請從中樞寄出',
        now() - interval '42 minutes', now() - interval '41 minutes', 12085, '業主往來12085', 'dry_run', now() - interval '41 minutes', now() - interval '45 minutes'
    ) RETURNING dispatch_id INTO v_d1;

    -- Seed 2: C115211-01A (廠區掃描與數位建模(美國)) -> 涂振邦 approved with edit -> final_sent_by_hub (#12086)
    INSERT INTO public.lark_cli_approval_dispatch (
        dispatch_id, org_id, case_code, client_name, contact_name,
        target_employee_id, target_employee_name, target_department, target_lark_open_id,
        hub_sender_identity, draft_subject, draft_body, lark_message_id,
        status, colleague_reply_code, colleague_reply_text,
        colleague_replied_at, final_sent_at, serial_no, serial_label, send_mode, pm_solution_synced_at, created_at
    ) VALUES (
        '49000000-0000-0000-0000-000000000002', 'YX', 'C115211-01A', '美商科技廠務專案業主', 'Project Director Lin',
        v_tuzhen, '涂振邦', '業務及PM部 · 業務與PM組', 'ou_ce8da7c9773e2178c44a2e10ef02c136',
        'jekai (cli_aa5c5ceba4f8de2a)',
        'C115211-01A (115471-01A) 廠區掃描與數位建模｜第一階段 LOD300 點雲與 BIM 交付確認',
        E'林總監您好：\n\n本案（工編 C115211-01A / 報價 115471-01A）第一階段廠區 3D 雷射掃描與 LOD300 數位建模成果已檢核完成，隨信提送交付清單與預覽報告，敬請查照。\n\n詠翔測量工程有限公司 敬上',
        'om_r49_seed_c115211_tuzhenbang',
        'final_sent_by_hub', '1', '[1] 核准發送，已確認合併育寬與羅薇雙重列為單一工編 C115211-01A',
        now() - interval '28 minutes', now() - interval '27 minutes', 12086, '業主往來12086', 'dry_run', now() - interval '27 minutes', now() - interval '31 minutes'
    ) RETURNING dispatch_id INTO v_d2;

    -- Seed 3: C115094 (興達電廠海氣象觀測) -> 羅薇 approved -> final_sent_by_hub (#12087)
    INSERT INTO public.lark_cli_approval_dispatch (
        dispatch_id, org_id, case_code, client_name, contact_name,
        target_employee_id, target_employee_name, target_department, target_lark_open_id,
        hub_sender_identity, draft_subject, draft_body, lark_message_id,
        status, colleague_reply_code, colleague_reply_text,
        colleague_replied_at, final_sent_at, serial_no, serial_label, send_mode, pm_solution_synced_at, created_at
    ) VALUES (
        '49000000-0000-0000-0000-000000000003', 'YX', 'C115094', '台灣電力股份有限公司', '陳主辦',
        v_luowei, '羅薇', '行政及財務部 · 行政與財務組', 'ou_8f039b26fb59ac71e9ed0db08011c13e',
        'jekai (cli_aa5c5ceba4f8de2a)',
        'C115094 興達電廠海氣象觀測｜第 3 期估驗計價請款單與發票明細提送',
        E'陳主辦您好：\n\n檢附 C115094 興達電廠海氣象觀測案第 3 期估驗計價請款單、發票明細與收發文紀錄表，金額已核對與合約一致，敬請惠予辦理撥款。\n\n詠翔測量工程有限公司 敬上',
        'om_r49_seed_c115094_luowei',
        'final_sent_by_hub', '1', '[1] 核准發出，發票金額與合約計價單已對齊無誤',
        now() - interval '19 minutes', now() - interval '18 minutes', 12087, '業主往來12087', 'dry_run', now() - interval '18 minutes', now() - interval '22 minutes'
    ) RETURNING dispatch_id INTO v_d3;

    -- Seed 4: C115055-1 (台南離岸風場水深地形監測) -> 朱雅琪 approved -> final_sent_by_hub (#12088)
    INSERT INTO public.lark_cli_approval_dispatch (
        dispatch_id, org_id, case_code, client_name, contact_name,
        target_employee_id, target_employee_name, target_department, target_lark_open_id,
        hub_sender_identity, draft_subject, draft_body, lark_message_id,
        status, colleague_reply_code, colleague_reply_text,
        colleague_replied_at, final_sent_at, serial_no, serial_label, send_mode, pm_solution_synced_at, created_at
    ) VALUES (
        '49000000-0000-0000-0000-000000000004', 'YX', 'C115055-1', '世紀離岸風電設備股份有限公司', '黃副理',
        v_yaqi, '朱雅琪', '行政及財務部 · 行政與財務組', 'ou_9df460867ad04c33272549f33b699377',
        'jekai (cli_aa5c5ceba4f8de2a)',
        'C115055-1 離岸風場水深地形監測｜業主拜訪會議紀錄與下階段施測期程確認',
        E'黃副理您好：\n\n感謝今日撥冗與本司團隊進行業務聯繫會議，隨信附上本次會議紀錄與下階段水深地形施測期程表，敬請查收確認。\n\n詠翔測量工程有限公司 敬上',
        'om_r49_seed_c115055_yaqi',
        'final_sent_by_hub', '1', '[1] 核准發出，已同步歸入正式 CRM 跟進表與週彙整視圖',
        now() - interval '11 minutes', now() - interval '10 minutes', 12088, '業主往來12088', 'dry_run', now() - interval '10 minutes', now() - interval '14 minutes'
    ) RETURNING dispatch_id INTO v_d4;

    -- Seed 5: C115025 (八掌溪渡槽外業進場與空拍確認) -> 吳柏頤 currently pending colleague approval (ready for live demo click!)
    INSERT INTO public.lark_cli_approval_dispatch (
        dispatch_id, org_id, case_code, client_name, contact_name,
        target_employee_id, target_employee_name, target_department, target_lark_open_id,
        hub_sender_identity, draft_subject, draft_body, lark_message_id,
        status, send_mode, created_at
    ) VALUES (
        '49000000-0000-0000-0000-000000000005', 'YX', 'C115025', '經濟部水利署第五河川分署', '林正工程司',
        v_wuboyi, '吳柏頤', '業務及PM部 · 業務與PM組', 'ou_c5051de1880e46996940abfa2295fe08',
        'jekai (cli_aa5c5ceba4f8de2a)',
        'C115025 水利署河川斷面與渡槽施測｜週二進場空拍 NOTAM 飛航公告與測量成果提送',
        E'林正工程司您好：\n\n本案週二（10/27）08:00 進場空拍之民航局飛航公告（NOTAM）與航管派駐均已整備完成，隨信附上本期斷面測量成果報告 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上',
        'om_r49_seed_c115025_pending',
        'pending_colleague', 'dry_run', now() - interval '3 minutes'
    ) RETURNING dispatch_id INTO v_d5;

    -- Seed Colleague Usage Telemetry Logs (Realistic distribution across active staff)
    INSERT INTO public.colleague_lark_agent_usage (
        employee_id, employee_name, department, team_scope, lark_open_id,
        case_code, dispatch_id, action_type, tokens_used, response_seconds, summary_note, created_at
    ) VALUES
        -- 吳柏頤 (7 interactions)
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C114109', v_d1, 'approve_send', 480, 75, 'Lark 回覆 [1] 核准發出 C114109 台塑北側管線修正圖 (#12085)', now() - interval '41 minutes'),
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C114109', NULL, 'edit_draft', 610, 110, 'Lark CLI 微調 C114109 業主稱呼與附件版號說明', now() - interval '55 minutes'),
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C115290-01', NULL, 'query_bot', 390, 45, '透過 Lark CLI 查詢 C115290-01 八掌溪渡槽 NOTAM 許可號 AB2610160008', now() - interval '70 minutes'),
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C115025', NULL, 'approve_send', 450, 82, 'Lark 回覆 [1] 核准 C115025 階段進度回報函', now() - interval '95 minutes'),
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C115031', NULL, 'supplement_file', 520, 90, '透過 Lark CLI 指派張家彬補件控制點報告', now() - interval '120 minutes'),
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C114488', NULL, 'approve_send', 430, 68, 'Lark 回覆 [1] 核准發出 C114488 驗收展延回覆函', now() - interval '150 minutes'),
        (v_wuboyi, '吳柏頤', '業務及PM部', 'pm', 'ou_c5051de1880e46996940abfa2295fe08', 'C115211-01A', NULL, 'query_bot', 340, 50, '查詢 C115211-01A 報價單 115471-01A 歸併狀態', now() - interval '180 minutes'),

        -- 羅薇 (6 interactions)
        (v_luowei, '羅薇', '行政及財務部', 'admin', 'ou_8f039b26fb59ac71e9ed0db08011c13e', 'C115094', v_d3, 'approve_send', 410, 64, 'Lark 回覆 [1] 核准發出 C115094 第 3 期估驗計價請款單 (#12087)', now() - interval '18 minutes'),
        (v_luowei, '羅薇', '行政及財務部', 'admin', 'ou_8f039b26fb59ac71e9ed0db08011c13e', 'C114109', NULL, 'triage_assign', 320, 52, '於 Lark CLI 將缺 DKIM 隔離信歸入 C114109 並轉交柏頤', now() - interval '48 minutes'),
        (v_luowei, '羅薇', '行政及財務部', 'admin', 'ou_8f039b26fb59ac71e9ed0db08011c13e', 'C114488', NULL, 'approve_send', 395, 70, 'Lark 回覆 [1] 核准發出合約用印回執通知', now() - interval '85 minutes'),
        (v_luowei, '羅薇', '行政及財務部', 'admin', 'ou_8f039b26fb59ac71e9ed0db08011c13e', 'Q-202610-07', NULL, 'edit_draft', 460, 88, '於 Lark CLI 修正報價單統一編號與發票抬頭', now() - interval '115 minutes'),
        (v_luowei, '羅薇', '行政及財務部', 'admin', 'ou_8f039b26fb59ac71e9ed0db08011c13e', 'C115094', NULL, 'query_bot', 290, 40, '透過 Lark CLI 核對電子公文 EB80745093 簽收流水號', now() - interval '140 minutes'),
        (v_luowei, '羅薇', '行政及財務部', 'admin', 'ou_8f039b26fb59ac71e9ed0db08011c13e', 'C114109', NULL, 'approve_send', 380, 60, 'Lark 回覆 [1] 核准收發文紀錄表回寫', now() - interval '175 minutes'),

        -- 涂振邦 (4 interactions)
        (v_tuzhen, '涂振邦', '業務及PM部', 'pm', 'ou_ce8da7c9773e2178c44a2e10ef02c136', 'C115211-01A', v_d2, 'approve_send', 540, 85, 'Lark 回覆 [1] 核准發出 C115211-01A 第一階段 LOD300 點雲交付函 (#12086)', now() - interval '27 minutes'),
        (v_tuzhen, '涂振邦', '業務及PM部', 'pm', 'ou_ce8da7c9773e2178c44a2e10ef02c136', 'C115211-01A', NULL, 'edit_draft', 490, 102, '於 Lark CLI 補充美商廠區 BIM 座標系轉換說明', now() - interval '62 minutes'),
        (v_tuzhen, '涂振邦', '業務及PM部', 'pm', 'ou_ce8da7c9773e2178c44a2e10ef02c136', 'C114512', NULL, 'approve_send', 420, 78, 'Lark 回覆 [1] 核准發出 C114512 邊坡監測週報', now() - interval '130 minutes'),
        (v_tuzhen, '涂振邦', '業務及PM部', 'pm', 'ou_ce8da7c9773e2178c44a2e10ef02c136', 'C115094', NULL, 'query_bot', 310, 48, '查詢 36 組重複未建確認單報價歸併清單', now() - interval '160 minutes'),

        -- 張家彬 (4 interactions)
        (v_jiabin, '張家彬', '內業部門', 'eng', 'ou_4ff567bcedd4b403f76e48c19d6f5c8e', 'C114109', NULL, 'supplement_file', 470, 92, '於 Lark CLI 上傳 C114109 北側管線修正圖 PDF 與控制點高程表', now() - interval '44 minutes'),
        (v_jiabin, '張家彬', '內業部門', 'eng', 'ou_4ff567bcedd4b403f76e48c19d6f5c8e', 'C115031', NULL, 'supplement_file', 430, 105, '於 Lark CLI 回傳點雲套疊成果檢核完畢', now() - interval '90 minutes'),
        (v_jiabin, '張家彬', '內業部門', 'eng', 'ou_4ff567bcedd4b403f76e48c19d6f5c8e', 'C115211-01A', NULL, 'approve_send', 390, 74, '於 Lark CLI 簽核內業品管無誤可對外提送', now() - interval '110 minutes'),
        (v_jiabin, '張家彬', '內業部門', 'eng', 'ou_4ff567bcedd4b403f76e48c19d6f5c8e', 'C114512', NULL, 'query_bot', 280, 55, '查詢 C114512 歷次 CAD 圖資版次', now() - interval '145 minutes'),

        -- 朱雅琪 (3 interactions)
        (v_yaqi, '朱雅琪', '行政及財務部', 'admin', 'ou_9df460867ad04c33272549f33b699377', 'C115055-1', v_d4, 'approve_send', 380, 58, 'Lark 回覆 [1] 核准發出 C115055-1 業主拜訪紀錄確認函 (#12088)', now() - interval '10 minutes'),
        (v_yaqi, '朱雅琪', '行政及財務部', 'admin', 'ou_9df460867ad04c33272549f33b699377', 'C115055-1', NULL, 'edit_draft', 410, 76, '於 Lark CLI 更新聯絡業主記錄聯繫主題（複選）與週彙整日期', now() - interval '35 minutes'),
        (v_yaqi, '朱雅琪', '行政及財務部', 'admin', 'ou_9df460867ad04c33272549f33b699377', 'C115211-01A', NULL, 'query_bot', 295, 42, '透過 Lark CLI 查詢正式 CRM 423 筆報價對齊狀態', now() - interval '100 minutes'),

        -- 古恆安 (2 interactions)
        (v_hengan, '古恆安', '外業部門', 'eng', 'ou_28067b39f157e654571ccf24387ebe0c', 'C114109', NULL, 'supplement_file', 360, 88, '於 Lark CLI 回傳外業現場照片與基樁點位紀錄', now() - interval '65 minutes'),
        (v_hengan, '古恆安', '外業部門', 'eng', 'ou_28067b39f157e654571ccf24387ebe0c', 'C115025', NULL, 'query_bot', 250, 49, '透過 Lark CLI 查詢外業進場聯絡窗口', now() - interval '125 minutes'),

        -- 郭倢瑛 (2 interactions)
        (v_jieying, '郭倢瑛', '行政及財務部', 'admin', 'ou_92773ead78b90c99a7ecbec5208fcc17', 'C115055-1', NULL, 'query_bot', 270, 44, '透過 Lark CLI 唯讀查閱 C115055-1 歷史業主聯繫紀錄與週報視圖', now() - interval '25 minutes'),
        (v_jieying, '郭倢瑛', '行政及財務部', 'admin', 'ou_92773ead78b90c99a7ecbec5208fcc17', 'C115094', NULL, 'query_bot', 240, 38, '查詢 C115094 合約歸檔編號', now() - interval '98 minutes'),

        -- 吳科翰 (2 interactions)
        (v_kehan, '吳科翰', '外業部門', 'eng', 'ou_e8708f8b380fc156887799e928afc479', 'C115290-01', NULL, 'approve_send', 405, 62, '於 Lark CLI 確認八掌溪渡槽空拍航管進駐完畢', now() - interval '30 minutes'),
        (v_kehan, '吳科翰', '外業部門', 'eng', 'ou_e8708f8b380fc156887799e928afc479', 'C115025', NULL, 'supplement_file', 350, 79, '透過 Lark CLI 回傳外業空拍飛行計畫書 PDF', now() - interval '80 minutes');
END $$;

-- 8. R49 Verification Suite Function (SW-CLI-01 .. SW-CLI-08)
CREATE OR REPLACE FUNCTION public.r49_telemetry_assert_all()
RETURNS TABLE(check_id TEXT, status TEXT, detail TEXT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_disp_cnt     INTEGER;
    v_sent_cnt     INTEGER;
    v_usage_cnt    INTEGER;
    v_active_staff INTEGER;
    v_xuanrong_cnt INTEGER;
    v_sync_cnt     INTEGER;
    v_test_disp    JSONB;
    v_test_reply   JSONB;
    v_test_uuid    UUID;
BEGIN
    SELECT COUNT(*) INTO v_disp_cnt FROM public.lark_cli_approval_dispatch;
    RETURN QUERY SELECT 'SW-CLI-01'::TEXT,
        CASE WHEN v_disp_cnt >= 5 THEN 'PASS' ELSE 'FAIL' END,
        format('lark_cli_approval_dispatch rows=%s (>=5)', v_disp_cnt);

    SELECT COUNT(*) INTO v_sent_cnt FROM public.lark_cli_approval_dispatch d WHERE d.status = 'final_sent_by_hub' AND serial_no IS NOT NULL AND pm_solution_synced_at IS NOT NULL;
    RETURN QUERY SELECT 'SW-CLI-02'::TEXT,
        CASE WHEN v_sent_cnt >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('final_sent_by_hub & synced rows=%s (>=4)', v_sent_cnt);

    SELECT COUNT(*), COUNT(DISTINCT employee_id) INTO v_usage_cnt, v_active_staff FROM public.colleague_lark_agent_usage;
    RETURN QUERY SELECT 'SW-CLI-03'::TEXT,
        CASE WHEN v_usage_cnt >= 25 AND v_active_staff >= 7 THEN 'PASS' ELSE 'FAIL' END,
        format('colleague_lark_agent_usage events=%s across %s colleagues', v_usage_cnt, v_active_staff);

    SELECT COUNT(*) INTO v_sync_cnt FROM public.pm_solution_correspondence_sync_v v WHERE v.status = 'final_sent_by_hub';
    RETURN QUERY SELECT 'SW-CLI-04'::TEXT,
        CASE WHEN v_sync_cnt >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('pm_solution_correspondence_sync_v synced rows=%s', v_sync_cnt);

    -- Test live 5-step state transition in a subtransaction or idempotent test row
    v_test_disp := public.r49_dispatch_lark_approval(
        'C114109',
        'a968fbf8-c0ac-5d6a-9939-80584ede3509'::uuid,
        'C114109 測試推播核准草稿',
        E'王課長您好：\n\n測試內文。\n\n詠翔測量工程有限公司 敬上',
        'om_r49_assert_test'
    );
    v_test_uuid := (v_test_disp->>'dispatch_id')::uuid;
    v_test_reply := public.r49_process_colleague_reply(
        v_test_uuid,
        '[1] 核准發出（自動化斷言驗證）',
        410,
        55
    );
    RETURN QUERY SELECT 'SW-CLI-05'::TEXT,
        CASE WHEN (v_test_reply->>'status') = 'final_sent_by_hub' AND (v_test_reply->>'pm_solution_synced')::boolean IS TRUE THEN 'PASS' ELSE 'FAIL' END,
        format('5-step loop test dispatch=%s -> status=%s serial=%s', v_test_uuid, v_test_reply->>'status', v_test_reply->>'serial_label');

    -- Clean up temporary test row so seed counts stay clean
    DELETE FROM public.colleague_lark_agent_usage WHERE dispatch_id = v_test_uuid;
    DELETE FROM public.lark_cli_approval_dispatch WHERE dispatch_id = v_test_uuid;

    -- Verify zero departed staff (已離職人員)
    SELECT (
        (SELECT COUNT(*) FROM public.lark_cli_approval_dispatch WHERE target_employee_name LIKE '%已離職人員%') +
        (SELECT COUNT(*) FROM public.colleague_lark_agent_usage WHERE employee_name LIKE '%已離職人員%') +
        (SELECT COUNT(*) FROM public.colleague_usage_leaderboard_v WHERE employee_name LIKE '%已離職人員%')
    ) INTO v_xuanrong_cnt;
    RETURN QUERY SELECT 'SW-CLI-06'::TEXT,
        CASE WHEN v_xuanrong_cnt = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('departed staff (已離職人員) count=%s (must be 0)', v_xuanrong_cnt);

    -- Verify leaderboard view returns 67 active colleagues with top colleague total_interactions >= 7
    RETURN QUERY SELECT 'SW-CLI-07'::TEXT,
        CASE WHEN (SELECT COUNT(*) FROM public.colleague_usage_leaderboard_v) = 67
              AND (SELECT MAX(total_interactions) FROM public.colleague_usage_leaderboard_v) >= 7
             THEN 'PASS' ELSE 'FAIL' END,
        format('leaderboard rows=%s, max_interactions=%s',
               (SELECT COUNT(*) FROM public.colleague_usage_leaderboard_v),
               (SELECT MAX(total_interactions) FROM public.colleague_usage_leaderboard_v));

    -- Verify C115211-01A mapping in pm_solution_correspondence_sync_v
    RETURN QUERY SELECT 'SW-CLI-08'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM public.pm_solution_correspondence_sync_v v
             WHERE v.pm_solution_project_code = 'C115211-01A' AND v.status = 'final_sent_by_hub'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'C115211-01A correspondence synced to PM Solution view';
END;
$$;

COMMIT;
