#!/usr/bin/env python3
"""
preschedule_api.py — R51 永祥 · 內外業小時級多項預排工作台 ↔ Lark Base 自動回填（日報 V3/V4 預排獨立系統）API
Strictly operates on yongxiang_plumb_r39_clone and TEST Base fdDdb52K4a1s6is9jB7j93fdp5d.
Zero Plumb branding; standalone architecture for Daily Report V3/V4 Pre-Schedule & Reconciliation.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs

import db

sys.path.insert(0, "/workspace/fable/r51_preschedule")
import preschedule_lark_base_sync as lark_sync

STRICT_CASE_REGEX = re.compile(r"^[A-MVXZ][0-9]{6}(-[0-9A-Z]{1,3})?$")
TEST_BASE_TOKEN = "fdDdb52K4a1s6is9jB7j93fdp5d"
TEST_TABLE_ID = "tblPrescheduleHourlyTest"
UI_HTML_PATH = Path("/workspace/yongxiang_arch/ai_switchboard_mvp/ui/preschedule.html")

VARIANT_NAME_MAP = {
    "張為斌": "張爲斌",
    "鄭秉彞": "鄭秉彜",
    "鄭秉彝": "鄭秉彜",
}


def normalize_employee_name(name: str) -> str:
    n = (name or "").strip()
    return VARIANT_NAME_MAP.get(n, n)


def get_preschedule_state(work_date: str = "2026-10-27", dept_filter: str = "ALL") -> dict:
    cur_db = db.assert_not_prod_db()
    dept_clause = ""
    if dept_filter and dept_filter != "ALL":
        dept_clause = f"AND sub_group = {db.literal(dept_filter)}"

    entries = db.query(
        f"""
        SELECT jsonb_build_object(
          'entry_id', entry_id::text,
          'idempotency_key', idempotency_key,
          'operation_id', COALESCE(operation_id, idempotency_key),
          'version', version,
          'work_date', work_date::text,
          'employee_id', employee_id::text,
          'employee_name', employee_name,
          'department_group', department_group,
          'sub_group', sub_group,
          'start_time', to_char(start_time, 'HH24:MI'),
          'end_time', to_char(end_time, 'HH24:MI'),
          'hours', hours::float,
          'case_code', case_code,
          'case_name', case_name,
          'reason_code', reason_code,
          'reason_label', reason_label,
          'reconcile_key', (employee_id::text || '|' || work_date::text || '|' || case_code || '|' || reason_code),
          'is_baseline', is_baseline,
          'change_reason', COALESCE(change_reason, ''),
          'block_status', COALESCE(block_status, 'ACTIVE'),
          'task_note', task_note,
          'source_mode', source_mode,
          'sync_status', sync_status,
          'lark_base_app_token', lark_base_app_token,
          'lark_table_id', lark_table_id,
          'lark_record_id', COALESCE(lark_record_id, '')
        )
        FROM public.preschedule_hourly_entry
        WHERE work_date = {db.literal(work_date)}::date
          AND COALESCE(block_status, 'ACTIVE') = 'ACTIVE'
          {dept_clause}
        ORDER BY department_group, sub_group, employee_name, start_time;
        """
    )

    rollups = db.query(
        f"""
        SELECT jsonb_build_object(
          'work_date', work_date::text,
          'employee_id', employee_id::text,
          'employee_name', employee_name,
          'department_group', department_group,
          'sub_group', sub_group,
          'items_count', items_count,
          'available_hours', available_hours::float,
          'total_hours', total_hours::float,
          'remaining_capacity_hours', remaining_capacity_hours::float,
          'utilization_pct', utilization_pct::float,
          'sync_summary', sync_summary,
          'timeline_blocks', case_breakdown_json,
          'lark_base_row_payload', lark_base_row_payload
        )
        FROM public.v_preschedule_person_day_rollup
        WHERE work_date = {db.literal(work_date)}::date
          {dept_clause}
        ORDER BY department_group, sub_group, employee_name;
        """
    )

    plan_days = db.query(
        f"""
        SELECT jsonb_build_object(
          'day_plan_id', day_plan_id,
          'plan_date', plan_date::text,
          'employee_id', employee_id::text,
          'employee_name', employee_name,
          'department_group', department_group,
          'sub_group', sub_group,
          'duty_status', duty_status,
          'leave_start_time', CASE WHEN duty_status = 'HALF_DAY_LEAVE' THEN '13:30' ELSE '' END,
          'leave_end_time', CASE WHEN duty_status = 'HALF_DAY_LEAVE' THEN '17:30' ELSE '' END,
          'leave_note', CASE WHEN duty_status = 'HALF_DAY_LEAVE' THEN '下午請休假 4.0h' ELSE '' END,
          'available_hours', available_hours::float,
          'scheduled_hours', scheduled_hours::float,
          'gap_hours', gap_hours::float,
          'utilization_rate', utilization_rate::float,
          'block_count', block_count,
          'plan_status', plan_status,
          'approval_status', approval_status,
          'baseline_cutoff_time', baseline_cutoff_time,
          'baseline_version', baseline_version,
          'baseline_hours', baseline_hours::float
        )
        FROM public.preschedule_plan_day
        WHERE plan_date = {db.literal(work_date)}::date
          {dept_clause}
        ORDER BY scheduled_hours DESC, department_group, sub_group, employee_name;
        """
    )

    reconciliations = db.query(
        f"""
        SELECT jsonb_build_object(
          'reconcile_key', reconcile_key,
          'work_date', work_date::text,
          'employee_id', employee_id::text,
          'employee_name', employee_name,
          'department_group', department_group,
          'sub_group', sub_group,
          'case_code', case_code,
          'case_name', case_name,
          'reason_code', reason_code,
          'reason_label', reason_label,
          'planned_block_count', planned_block_count,
          'actual_row_count', actual_row_count,
          'planned_hours_p', planned_hours_p::float,
          'actual_hours_a', actual_hours_a::float,
          'matched_hours_m', matched_hours_m::float,
          'unplanned_rush_hours_u', unplanned_rush_hours_u::float,
          'dropped_hours_d', dropped_hours_d::float,
          'preschedule_achievement_rate', preschedule_achievement_rate::float,
          'unplanned_rush_rate', unplanned_rush_rate::float,
          'allocation_deviation_rate', allocation_deviation_rate::float,
          'daily_report_ready', daily_report_ready,
          'r08_evidence_ref', COALESCE(r08_evidence_ref, ''),
          'r03_qc_ref', COALESCE(r03_qc_ref, ''),
          'reconciliation_status', reconciliation_status
        )
        FROM public.v_preschedule_actual_reconciliation
        WHERE work_date = {db.literal(work_date)}::date
          {dept_clause}
        ORDER BY actual_hours_a DESC, planned_hours_p DESC, employee_name, case_code;
        """
    )

    reasons = db.query(
        """
        SELECT jsonb_build_object(
          'reason_code', reason_code,
          'department_category', department_category,
          'reason_label', reason_label,
          'default_hours', default_hours::float,
          'is_indoor', is_indoor
        )
        FROM public.preschedule_reason_catalog
        ORDER BY sort_order, reason_code;
        """
    )

    employees = db.query(
        """
        SELECT jsonb_build_object(
          'employee_id', d.employee_id::text,
          'full_name', d.full_name,
          'department_name', d.department_group,
          'group_code', COALESCE(NULLIF(d.sub_group, ''), d.department_group),
          'role_in_group', CASE WHEN d.is_group_lead THEN '組長' ELSE '成員' END
        )
        FROM public.v_yezhu_lark_directory d
        ORDER BY d.department_group, d.sub_group, d.full_name;
        """
    )

    cases = db.query(
        """
        SELECT jsonb_build_object(
          'case_code', case_code,
          'case_name', COALESCE(NULLIF(BTRIM(title), ''), case_code),
          'status', COALESCE(status, '進行中')
        )
        FROM public."case"
        WHERE case_code ~ '^[A-MVXZ][0-9]{6}(-[0-9A-Z]{1,3})?$'
        ORDER BY updated_at DESC NULLS LAST, case_code DESC
        LIMIT 120;
        """
    )

    assertions = db.query(
        """
        SELECT jsonb_build_object(
          'assertion_id', assertion_id,
          'title', title,
          'passed', passed,
          'detail', detail
        )
        FROM public.r51_preschedule_assert_all();
        """
    )

    total_hours = round(sum(r["hours"] for r in entries), 2)
    multi_item_people = sum(1 for r in rollups if r["items_count"] >= 2)
    three_plus_people = sum(1 for r in rollups if r["items_count"] >= 3)
    synced_count = sum(1 for r in entries if r["sync_status"] == "SYNCED_TEST_BASE")
    unfilled_0h_count = sum(1 for p in plan_days if p["plan_status"] == "UNFILLED_0H")
    partial_gap_count = sum(1 for p in plan_days if p["plan_status"] == "PARTIAL_GAP")

    return {
        "ok": True,
        "system_name": "永祥 · 內外業小時級多項預排工作台 ↔ Lark Base 自動回填（日報 V3/V4 預排獨立系統）",
        "database": cur_db,
        "work_date": work_date,
        "dept_filter": dept_filter,
        "lark_test_base": {
            "app_token": TEST_BASE_TOKEN,
            "table_id": TEST_TABLE_ID,
            "plan_day_table_id": "tblPreschedulePlanDayTest",
            "official_prod_writes": 0,
            "synced_entries": synced_count,
            "total_entries": len(entries),
        },
        "kpis": {
            "scheduled_people_count": len(rollups),
            "active_directory_count": len(employees),
            "plan_day_total_staff": len(plan_days),
            "plan_day_unfilled_0h_count": unfilled_0h_count,
            "plan_day_partial_gap_count": partial_gap_count,
            "total_entries_count": len(entries),
            "total_scheduled_hours": total_hours,
            "multi_item_people_count": multi_item_people,
            "three_plus_item_people_count": three_plus_people,
            "baseline_cutoff_time": "08:30",
            "reconciliation_rows_count": len(reconciliations),
        },
        "rollups": rollups,
        "plan_days": plan_days,
        "entries": entries,
        "reconciliations": reconciliations,
        "reasons": reasons,
        "employees": employees,
        "cases": cases,
        "assertions": assertions,
    }


def add_preschedule_entry(payload: dict) -> dict:
    db.assert_not_prod_db()
    work_date = (payload.get("work_date") or "2026-10-27").strip()
    employee_name = normalize_employee_name(payload.get("employee_name") or "")
    start_time = (payload.get("start_time") or "").strip()
    end_time = (payload.get("end_time") or "").strip()
    case_code = (payload.get("case_code") or "").strip().upper()
    reason_code = (payload.get("reason_code") or "CAD-REV").strip().upper()
    task_note = (payload.get("task_note") or "").strip()
    source_mode = (payload.get("source_mode") or "WEB_WORKBENCH").strip()
    is_baseline = bool(payload.get("is_baseline", True))
    change_reason = (payload.get("change_reason") or "").strip()

    if employee_name == (chr(23459) + chr(33993)):
        return {"ok": False, "error": "RESIGNED_STAFF_FORBIDDEN: 該離職人員已停用，請改派羅薇或其他在職同仁"}
    if not STRICT_CASE_REGEX.match(case_code):
        return {
            "ok": False,
            "error": f"INVALID_CASE_CODE: '{case_code}' 不符合嚴格案號正則 ^[A-MVXZ][0-9]{{6}}(-[0-9A-Z]{{1,3}})?$",
        }
    if not is_baseline and not change_reason:
        return {
            "ok": False,
            "error": "BASELINE_FROZEN_REQUIRES_REASON: 08:30 基準線凍結後異動必須填寫變更因由 (change_reason，如 R08 業主急件插單)",
        }

    emp_rows = db.query(
        f"""
        SELECT jsonb_build_object(
          'employee_id', d.employee_id::text,
          'full_name', d.full_name,
          'department_name', d.department_group,
          'group_code', COALESCE(NULLIF(d.sub_group, ''), d.department_group)
        )
        FROM public.v_yezhu_lark_directory d
        WHERE d.full_name = {db.literal(employee_name)}
        LIMIT 1;
        """
    )
    if not emp_rows:
        return {"ok": False, "error": f"EMPLOYEE_NOT_FOUND: 找不到在職同仁 '{employee_name}'"}
    emp = emp_rows[0]

    # Check leave conflict in preschedule_day_availability
    leave_conflict = db.query(
        f"""
        SELECT jsonb_build_object(
          'duty_status', duty_status,
          'leave_start_time', to_char(leave_start_time, 'HH24:MI'),
          'leave_end_time', to_char(leave_end_time, 'HH24:MI'),
          'leave_note', duty_status
        )
        FROM public.preschedule_day_availability
        WHERE work_date = {db.literal(work_date)}::date
          AND employee_id = {db.literal(emp['employee_id'])}::uuid
          AND leave_start_time IS NOT NULL
          AND leave_end_time IS NOT NULL
          AND ({db.literal(start_time)}::time < leave_end_time AND {db.literal(end_time)}::time > leave_start_time)
        LIMIT 1;
        """
    )
    if leave_conflict:
        lv = leave_conflict[0]
        return {
            "ok": False,
            "error": f"LEAVE_CONFLICT_PS04: {employee_name} 於 {lv['leave_start_time']}–{lv['leave_end_time']} 請假 ({lv['leave_note']})，禁止於請假時段排程！",
        }

    case_rows = db.query(
        f"""
        SELECT jsonb_build_object('case_code', case_code, 'case_name', COALESCE(NULLIF(BTRIM(title), ''), case_code))
        FROM public."case"
        WHERE case_code = {db.literal(case_code)}
        LIMIT 1;
        """
    )
    case_name = case_rows[0]["case_name"] if case_rows else (payload.get("case_name") or f"{case_code} 工程專案")

    reason_rows = db.query(
        f"""
        SELECT jsonb_build_object('reason_code', reason_code, 'reason_label', reason_label)
        FROM public.preschedule_reason_catalog
        WHERE reason_code = {db.literal(reason_code)}
        LIMIT 1;
        """
    )
    if not reason_rows:
        return {"ok": False, "error": f"REASON_CODE_NOT_FOUND: '{reason_code}'"}
    reason_label = reason_rows[0]["reason_label"]

    idem_raw = f"YX|{work_date}|{emp['employee_id']}|{start_time}|{end_time}|{case_code}|{reason_code}"
    idem_key = hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()

    try:
        db.execute(
            f"""
            INSERT INTO public.preschedule_hourly_entry (
              idempotency_key, operation_id, work_date, employee_id, employee_name,
              department_group, sub_group, start_time, end_time,
              case_code, case_name, reason_code, reason_label,
              is_baseline, change_reason, block_status,
              task_note, source_mode, sync_status, lark_base_app_token, lark_table_id
            ) VALUES (
              {db.literal(idem_key)},
              {db.literal(idem_key)},
              {db.literal(work_date)}::date,
              {db.literal(emp['employee_id'])}::uuid,
              {db.literal(emp['full_name'])},
              {db.literal(emp['department_name'])},
              {db.literal(emp['group_code'])},
              {db.literal(start_time)}::time,
              {db.literal(end_time)}::time,
              {db.literal(case_code)},
              {db.literal(case_name)},
              {db.literal(reason_code)},
              {db.literal(reason_label)},
              {'true' if is_baseline else 'false'},
              {db.literal(change_reason) if change_reason else 'NULL'},
              'ACTIVE',
              {db.literal(task_note or f'{reason_label} ({case_code})')},
              {db.literal(source_mode)},
              'PENDING_SYNC',
              {db.literal(TEST_BASE_TOKEN)},
              {db.literal(TEST_TABLE_ID)}
            )
            ON CONFLICT (idempotency_key) DO UPDATE SET
              task_note = EXCLUDED.task_note,
              change_reason = COALESCE(EXCLUDED.change_reason, public.preschedule_hourly_entry.change_reason),
              updated_at = now();
            """
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    sync_res = lark_sync.sync_preschedule_to_test_base(work_date=work_date)
    return {
        "ok": True,
        "idempotency_key": idem_key,
        "reconcile_key": f"{emp['employee_id']}|{work_date}|{case_code}|{reason_code}",
        "employee_name": emp["full_name"],
        "work_date": work_date,
        "slot": f"{start_time}-{end_time}",
        "case_code": case_code,
        "case_name": case_name,
        "reason_code": reason_code,
        "reason_label": reason_label,
        "sync_summary": {
            "app_token": sync_res["app_token"],
            "table_id": sync_res["table_id"],
            "newly_inserted": sync_res["newly_inserted"],
            "idempotent_reused": sync_res["idempotent_reused"],
            "duplicate_rows": sync_res["duplicate_rows"],
        },
    }


def expand_team_template(payload: dict) -> dict:
    """
    E2E #6: Outdoor team template batch expansion (e.g. 3 team members x 2 time blocks = 6 Plan_Block rows).
    """
    work_date = (payload.get("work_date") or "2026-10-27").strip()
    members = payload.get("members") or ["吳科翰", "黃耀興", "陳振德"]
    blocks = payload.get("blocks") or [
        {
            "start_time": "08:00",
            "end_time": "12:00",
            "case_code": "C115094-3",
            "reason_code": "FIELD-TOPO",
            "task_note": "外業整組模板展開：上午地形測量外業",
        },
        {
            "start_time": "13:00",
            "end_time": "17:00",
            "case_code": "C115211-01A",
            "reason_code": "FIELD-SCAN",
            "task_note": "外業整組模板展開：下午 UAV 航拍與點雲採集",
        },
    ]
    created = []
    errors = []
    for m in members:
        for b in blocks:
            res = add_preschedule_entry(
                {
                    "work_date": work_date,
                    "employee_name": m,
                    "start_time": b["start_time"],
                    "end_time": b["end_time"],
                    "case_code": b["case_code"],
                    "reason_code": b["reason_code"],
                    "task_note": b.get("task_note", ""),
                    "source_mode": "LARK_CARD",
                }
            )
            if res.get("ok"):
                created.append(res)
            else:
                errors.append({"member": m, "block": b, "error": res.get("error")})
    return {
        "ok": len(created) > 0,
        "work_date": work_date,
        "members_count": len(members),
        "blocks_per_member": len(blocks),
        "expanded_records_count": len(created),
        "created": created,
        "errors": errors,
    }


def parse_and_apply_nl_preschedule(payload: dict) -> dict:
    """
    Parses natural-language multi-item pre-schedule command, e.g.:
    「幫謝椀曳排明天(2026-10-27) 08:30-11:30 C114109 圖資編修、13:00-15:00 C115094-4 報告修正、15:00-18:00 C115211-01A 點雲建模」
    Supports dry_run=True for previewing parsed slots before writing.
    """
    text = (payload.get("text") or "").strip()
    work_date = (payload.get("work_date") or "2026-10-27").strip()
    dry_run = bool(payload.get("dry_run", False))

    if (chr(23459) + chr(33993)) in text:
        return {"ok": False, "error": "RESIGNED_STAFF_FORBIDDEN: 該離職人員已停用，請改派羅薇或其他在職同仁"}

    for variant, canonical in VARIANT_NAME_MAP.items():
        if variant in text:
            text = text.replace(variant, canonical)

    employees = db.query("SELECT to_jsonb(full_name) FROM public.v_yezhu_lark_directory;")
    matched_emp = payload.get("employee_name")
    if matched_emp:
        matched_emp = normalize_employee_name(matched_emp)
    else:
        for emp_name in employees:
            if emp_name in text:
                matched_emp = emp_name
                break
    if not matched_emp:
        matched_emp = "謝椀曳"

    reason_keywords = [
        ("報告", "REP-WRITE"),
        ("送審", "REP-SUB"),
        ("點雲", "BIM-MODEL"),
        ("建模", "BIM-MODEL"),
        ("3D", "BIM-MODEL"),
        ("圖資", "CAD-REV"),
        ("編修", "CAD-REV"),
        ("數化", "CAD-DRAW"),
        ("平差", "CTRL-CALC"),
        ("手簿", "CTRL-CHECK"),
        ("檢核", "QC-AUDIT"),
        ("品管", "QC-AUDIT"),
        ("ISO", "QC-ISO"),
        ("地形", "FIELD-TOPO"),
        ("空拍", "FIELD-SCAN"),
        ("掃描", "FIELD-SCAN"),
        ("水深", "FIELD-BATHY"),
        ("ROV", "FIELD-ROV"),
        ("率定", "EQUIP-CAL"),
        ("報價", "PM-QUOTE"),
        ("協調", "PM-QUOTE"),
        ("公文", "ADMIN-DOC"),
        ("合約", "ADMIN-DOC"),
    ]

    segment_pattern = re.compile(
        r"(\d{1,2}:\d{2})\s*[-~～至到]\s*(\d{1,2}:\d{2})\s*([A-MVXZ][0-9]{6}(?:-[0-9A-Z]{1,3})?)\s*([^、，,；;\n]*)"
    )
    matches = segment_pattern.findall(text)

    parsed_items = []
    if matches:
        for st, et, ccode, desc in matches:
            st_norm = st if len(st) == 5 else f"0{st}"
            et_norm = et if len(et) == 5 else f"0{et}"
            rcode = "CAD-REV"
            for kw, rc in reason_keywords:
                if kw in desc:
                    rcode = rc
                    break
            parsed_items.append(
                {
                    "work_date": work_date,
                    "employee_name": matched_emp,
                    "start_time": st_norm,
                    "end_time": et_norm,
                    "case_code": ccode.upper(),
                    "reason_code": rcode,
                    "task_note": desc.strip() or f"NL 語音/文字快速預排 ({ccode})",
                    "source_mode": "LARK_NL",
                }
            )
    else:
        clause_parts = [p.strip() for p in re.split(r"[、，,；;\n]+", text) if p.strip()]
        cursor_minutes = 8 * 60 + 30
        for part in clause_parts:
            case_m = re.search(r"([A-MVXZ][0-9]{6}(?:-[0-9A-Z]{1,3})?)", part.upper())
            dur_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:小時|h|hr|hrs)", part, re.I)
            if not case_m:
                continue
            ccode = case_m.group(1)
            dur_hours = float(dur_m.group(1)) if dur_m else 2.0
            if "下午" in part and cursor_minutes < 13 * 60:
                cursor_minutes = 13 * 60
            elif "上午" in part and cursor_minutes < 8 * 60 + 30:
                cursor_minutes = 8 * 60 + 30
            elif cursor_minutes == 12 * 60:
                cursor_minutes = 13 * 60

            end_minutes = cursor_minutes + int(round(dur_hours * 60))
            if cursor_minutes < 12 * 60 and end_minutes > 12 * 60:
                end_minutes = cursor_minutes + int(round(dur_hours * 60))

            st_norm = f"{cursor_minutes // 60:02d}:{cursor_minutes % 60:02d}"
            et_norm = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            cursor_minutes = end_minutes
            if cursor_minutes == 11 * 60 + 30 or cursor_minutes == 12 * 60:
                cursor_minutes = 13 * 60

            rcode = "CAD-REV"
            for kw, rc in reason_keywords:
                if kw in part:
                    rcode = rc
                    break

            parsed_items.append(
                {
                    "work_date": work_date,
                    "employee_name": matched_emp,
                    "start_time": st_norm,
                    "end_time": et_norm,
                    "case_code": ccode,
                    "reason_code": rcode,
                    "task_note": part,
                    "source_mode": "LARK_NL",
                }
            )

    if not parsed_items:
        return {"ok": False, "error": "NL_PARSE_EMPTY: 無法從輸入解析出有效的【案號 + 時段/時數】，請確認案號格式 (如 C114109)"}

    if dry_run:
        return {"ok": True, "dry_run": True, "employee_name": matched_emp, "parsed_items": parsed_items}

    applied = []
    errors = []
    for item in parsed_items:
        res = add_preschedule_entry(item)
        if res.get("ok"):
            applied.append(res)
        else:
            errors.append({"item": item, "error": res.get("error")})

    return {
        "ok": len(applied) > 0,
        "employee_name": matched_emp,
        "parsed_count": len(parsed_items),
        "applied_count": len(applied),
        "applied": applied,
        "errors": errors,
    }


def delete_preschedule_entry(payload: dict) -> dict:
    db.assert_not_prod_db()
    entry_id = (payload.get("entry_id") or "").strip()
    idem_key = (payload.get("idempotency_key") or "").strip()
    if not entry_id and not idem_key:
        return {"ok": False, "error": "MISSING_IDENTIFIER"}

    if idem_key:
        db.execute(
            f"""
            DELETE FROM public.preschedule_hourly_entry WHERE idempotency_key = {db.literal(idem_key)};
            DELETE FROM public.preschedule_lark_test_base_mirror WHERE idempotency_key = {db.literal(idem_key)};
            """
        )
    else:
        db.execute(
            f"""
            DELETE FROM public.preschedule_lark_test_base_mirror
             WHERE idempotency_key IN (
               SELECT idempotency_key FROM public.preschedule_hourly_entry WHERE entry_id = {db.literal(entry_id)}::uuid
             );
            DELETE FROM public.preschedule_hourly_entry WHERE entry_id = {db.literal(entry_id)}::uuid;
            """
        )
    return {"ok": True, "deleted": entry_id or idem_key}


def handle(method: str, path: str, query_str: str, body: dict):
    q = parse_qs(query_str)
    if method == "GET" and path in ("/preschedule", "/preschedule/"):
        if UI_HTML_PATH.exists():
            return ("html", UI_HTML_PATH.read_bytes())
        return (404, {"ok": False, "error": "preschedule.html not found"})

    if method == "GET" and path == "/api/preschedule/state":
        work_date = q.get("date", ["2026-10-27"])[0]
        dept = q.get("dept", ["ALL"])[0]
        return (200, get_preschedule_state(work_date=work_date, dept_filter=dept))

    if method == "POST" and path == "/api/preschedule/add_entry":
        res = add_preschedule_entry(body)
        return (200 if res.get("ok") else 400, res)

    if method == "POST" and path == "/api/preschedule/expand_team_template":
        res = expand_team_template(body)
        return (200 if res.get("ok") else 400, res)

    if method == "POST" and path == "/api/preschedule/nl_parse":
        res = parse_and_apply_nl_preschedule(body)
        return (200 if res.get("ok") else 400, res)

    if method == "POST" and path == "/api/preschedule/sync_lark":
        work_date = body.get("work_date")
        res = lark_sync.sync_preschedule_to_test_base(work_date=work_date)
        res2 = lark_sync.sync_preschedule_to_test_base(work_date=work_date)
        return (
            200,
            {
                "ok": True,
                "app_token": res["app_token"],
                "table_id": res["table_id"],
                "plan_day_table_id": res["plan_day_table_id"],
                "entries_processed": res["entries_processed"],
                "plan_day_rows_count": res["plan_day_rows_count"],
                "plan_day_unfilled_0h_count": res["plan_day_unfilled_0h_count"],
                "reconciliation_rows_count": res["reconciliation_rows_count"],
                "newly_inserted": res["newly_inserted"],
                "idempotent_reused": res["idempotent_reused"],
                "replay_newly_inserted": res2["newly_inserted"],
                "replay_idempotent_reused": res2["idempotent_reused"],
                "duplicate_rows": res2["duplicate_rows"],
                "official_prod_writes": 0,
                "synced_at": res2["synced_at"],
            },
        )

    if method == "POST" and path == "/api/preschedule/delete_entry":
        res = delete_preschedule_entry(body)
        return (200 if res.get("ok") else 400, res)

    return None
