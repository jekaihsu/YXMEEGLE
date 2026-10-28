"""API column whitelists; unknown columns and nested price fields fail closed."""
BASE={
1:'outbound_id status channel case_id quote_id invoice_id recipient_name recipient_email customer_name final_body first_lines attachments gate_checks source_command_body_stripped',
2:'case_id case_code stage contract_status customer_id customer_name quote_id quote_no quote_status quoted_total quote_lines contract_items commitments timeline master_cap dispatched_total remaining_cap cap_ratio',
3:'invoice_id case_id period_no invoice_no invoice_date due_date amount_due retention_amount allocated reversed recognized_diff unpaid candidate_notices release_gates',
4:'task_id case_id case_code customer_id node_name status executor_id checker_id started_at exec_done_at dwell_days exec_sla_days rejection_count playbook_rules latest_rejection_mail last_passed_reply',
5:'cost_item_id case_id case_code kind nature status amount supplier_name supplier_license_status estimated actual overrun_ratio contract_total',
6:'settlement_id case_id case_code settlement_status vp_signed_by vp_signed_at gm_signed_by gm_signed_at contract_total billed_total received_total retention_outstanding total_points open_commitments provisional_items_with_work',
}
EXTRA={5:'labor_std_cost external_cost misc_cost projected_total_cost margin_ratio_now margin_ratio_after',6:'labor_std_cost external_cost projected_total_cost projected_margin'}
VIEWS={1:('canvas_v1_outbound_preview','outbound_id'),2:('canvas_v2_quote_commitment_compare','case_id'),3:('canvas_v3_release_and_receipt','invoice_id'),4:('canvas_v4_review_rejection','task_id'),5:('canvas_v5_subcontract_margin','cost_item_id'),6:('canvas_v6_settlement_triway','settlement_id')}
NESTED_FIELDS=set('id item_id line_no item_code item_name work_item_id description name unit qty quantity done_amount unit_price amount line_amount target_points status party kind due_date written_confirm_comm_id linked_contract_item_id occurred_at event summary floor_price traffic_light'.split())

def columns(view_no,role):
    if role not in ('sales','pm','vp','admin','finance','field_member','field_lead','inner_lead','gm','it','payroll'):
        return ()
    return tuple((BASE.get(view_no,'')+(' '+EXTRA.get(view_no,'') if role in ('pm','vp','gm') else '')).split())

def project(view_no,role,row):
    def nested(value):
        allowed=NESTED_FIELDS|({'standard_cost_price'} if role in ('pm','vp','gm') else set())
        if isinstance(value,list):return [nested(item) for item in value]
        if isinstance(value,dict):return {k:nested(v) for k,v in value.items() if k in allowed}
        return value
    return {key:nested(row[key]) if isinstance(row[key],(dict,list)) else row[key] for key in columns(view_no,role) if key in row}
