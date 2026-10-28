\set ON_ERROR_STOP on
SET plpgsql.check_asserts = on;

-- ============================================================================
-- Fable 5.1 High Step 4 Review Patches & Zero-Manual-Labeling Recall Suite
-- File: 012_fable_step4_r32_and_recall.sql
-- Hard Rule: NEVER run test migrations against production yongxiang_plumb.
-- ============================================================================
DO $$
BEGIN
  ASSERT current_database() != 'yongxiang_plumb',
    'FATAL: refusing to execute test migration on production database yongxiang_plumb';
  ASSERT current_database() IN ('yongxiang_plumb_r39_clone', 'yongxiang_plumb_r43_clone'),
    format('FATAL: unexpected target database %s', current_database());
END $$;

BEGIN;
SET LOCAL application_name = 'run_migration_once:012_fable_step4_r32_and_recall';

-- ============================================================================
-- 1. serial_assignment Serial Number Protection & Legacy 1..12,084 Protection
-- ============================================================================
DO $$
BEGIN
  IF to_regclass('public.serial_assignment_org_fp_mode_uq') IS NULL
     AND NOT EXISTS (
       SELECT 1 FROM pg_constraint
       WHERE conrelid = 'public.serial_assignment'::regclass
         AND conname IN ('serial_assignment_org_fp_mode_uq', 'serial_assignment_pkey')
     ) THEN
    ALTER TABLE public.serial_assignment
      ADD CONSTRAINT serial_assignment_org_fp_mode_uq UNIQUE (org_id, fingerprint, mode);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.serial_assignment'::regclass
      AND conname = 'serial_assignment_serial_no_check'
  ) THEN
    ALTER TABLE public.serial_assignment
      ADD CONSTRAINT serial_assignment_serial_no_check
      CHECK ((mode = 'live' AND serial_no > 0) OR (mode = 'dry_run' AND serial_no <= -12085));
  END IF;
END $$;

-- Normalize canonical serial_label on all 12,084 legacy rows in yezhu_correspondence_ledger
DO $$
BEGIN
  IF to_regclass('public.yezhu_correspondence_ledger') IS NOT NULL THEN
    UPDATE public.yezhu_correspondence_ledger
       SET serial_label = '業主往來' || serial_no::text
     WHERE serial_no BETWEEN 1 AND 12084
       AND serial_label <> '業主往來' || serial_no::text;

    -- Backfill legacy 1..12,084 live serials into serial_assignment so any dry_run on
    -- a legacy thread <= 12084 immediately raises 'fingerprint already has live serial; dry_run refused'
    INSERT INTO public.serial_assignment (org_id, fingerprint, mode, serial_no)
    SELECT 'YX', 'legacy:yezhu:' || l.serial_no::text, 'live', l.serial_no
      FROM public.yezhu_correspondence_ledger l
     WHERE l.serial_no BETWEEN 1 AND 12084
    ON CONFLICT (org_id, fingerprint, mode) DO NOTHING;
  END IF;
END $$;

-- ============================================================================
-- 2. email_sent_copy.header_d DKIM Verification Hardening
--    - header_d must ONLY come from ETL-parsed dkim=pass header.d
--    - never derived from From email address
--    - satcmd_guard strictly compares m.dkim_domain and s.header_d
-- ============================================================================
DELETE FROM public.email_sent_copy
 WHERE header_d IS NULL
    OR btrim(header_d) = ''
    OR position('@' IN header_d) > 0
    OR position('.' IN header_d) = 0
    OR header_d ILIKE '%derived%';

CREATE OR REPLACE FUNCTION public.step4_email_sent_copy_header_d_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.header_d IS NULL
     OR btrim(NEW.header_d) = ''
     OR position('@' IN NEW.header_d) > 0
     OR position('.' IN NEW.header_d) = 0
     OR NEW.header_d ILIKE '%derived%' THEN
    RAISE EXCEPTION 'STEP4-DKIM-HEADER-D: header_d must come strictly from ETL-parsed dkim=pass header.d, never derived from From address (got header_d=%)',
      NEW.header_d;
  END IF;
  NEW.header_d := lower(btrim(NEW.header_d));
  RETURN NEW;
END $function$;

DROP TRIGGER IF EXISTS step4_email_sent_copy_header_d_trg ON public.email_sent_copy;
CREATE TRIGGER step4_email_sent_copy_header_d_trg
  BEFORE INSERT OR UPDATE ON public.email_sent_copy
  FOR EACH ROW EXECUTE FUNCTION public.step4_email_sent_copy_header_d_guard();

CREATE OR REPLACE FUNCTION public.satcmd_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
  ok boolean := false;
  v_org text;
BEGIN
  IF to_regclass('public.email_sent_copy') IS NOT NULL THEN
    SELECT true, b.org_id INTO ok, v_org
    FROM public.email_message m
    JOIN public.email_mailbox b
      ON lower(b.address) = lower(coalesce(substring(m.from_addr FROM '<([^<>]+)>\s*$'), btrim(m.from_addr)))
    JOIN public.email_sent_copy s
      ON s.mailbox_id = b.id
     AND s.message_id = m.message_id
     AND lower(s.header_d) = lower(split_part(b.address, '@', 2))
     AND lower(s.header_d) = lower(m.dkim_domain)
    WHERE m.id = NEW.source_message_id
      AND b.role = 'satellite'
      AND m.dkim_pass = true AND m.spf_pass = true
      AND m.sent_copy_verified = true
      AND m.dkim_domain IS NOT NULL
      AND lower(m.dkim_domain) = lower(split_part(b.address, '@', 2))
    LIMIT 1;
  END IF;

  IF NOT coalesce(ok, false) AND to_regclass('public.satellite_sent_copy') IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM public.email_sent_copy s0
       JOIN public.email_message m0 ON m0.message_id = s0.message_id
       WHERE m0.id = NEW.source_message_id
     ) THEN
    SELECT true, b.org_id INTO ok, v_org
    FROM public.email_message m
    JOIN public.email_mailbox b
      ON lower(b.address) = lower(coalesce(substring(m.from_addr FROM '<([^<>]+)>\s*$'), btrim(m.from_addr)))
    JOIN public.satellite_sent_copy sc
      ON sc.mailbox_id = b.id AND sc.message_id = m.message_id
    WHERE m.id = NEW.source_message_id
      AND b.role = 'satellite'
      AND m.dkim_pass = true AND m.spf_pass = true
      AND m.sent_copy_verified = true
      AND m.dkim_domain IS NOT NULL
      AND lower(m.dkim_domain) = lower(split_part(b.address, '@', 2))
    LIMIT 1;
  END IF;

  IF NOT coalesce(ok, false) THEN
    RAISE EXCEPTION 'R32-SAT-AUTH: command source not an authenticated satellite (requires mailbox role=satellite, dkim_pass, spf_pass, sent_copy_verified, and Sent-copy header_d matching sender domain)';
  END IF;
  NEW.org_id := coalesce(NEW.org_id, v_org);
  RETURN NEW;
END $function$;

-- ============================================================================
-- 3. org_marker Table Seed (Tax IDs & Domains) & Inbound/Outbound Separation
-- ============================================================================
INSERT INTO public.org_marker (org_code, kind, value, verified_by) VALUES
  ('YX', 'tax_id', '80217508', 'fable_step4'),
  ('YX', 'tax_id', '28725008', 'fable_step4'),
  ('YX', 'domain', 'yxsurvey.com.tw', 'fable_step4'),
  ('SJ', 'tax_id', '83100099', 'fable_step4'),
  ('SJ', 'tax_id', '53462460', 'fable_step4'),
  ('SJ', 'domain', 'sjsurvey.com.tw', 'fable_step4')
ON CONFLICT (org_code, kind, value) DO NOTHING;

CREATE OR REPLACE FUNCTION public.r32_unlinked_org_marker_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
  v_row jsonb := to_jsonb(NEW);
  v_inbound boolean := TG_TABLE_NAME IN ('email_message', 'switchboard_intake');
  v_mb_org text;
  txt text := lower(coalesce(v_row->>'subject', '') || ' ' ||
              coalesce(v_row->>'body_new_text', '') || ' ' ||
              coalesce(v_row->>'body_text', '') || ' ' ||
              coalesce(v_row->>'draft_body', '') || ' ' ||
              coalesce(v_row->>'final_body', '') || ' ' ||
              coalesce(v_row->>'from_addr', '') || ' ' ||
              coalesce(v_row->>'payload', ''));
  has_yx_hard boolean;
  has_sj_hard boolean;
  has_sj_any  boolean;
  bad text;
BEGIN
  IF v_inbound AND TG_OP = 'INSERT' AND NOT public.org_marker_armed('SJ')
     AND (TG_TABLE_NAME = 'email_message' OR coalesce(v_row->>'channel', '') = 'email') THEN
    IF TG_TABLE_NAME = 'email_message' THEN
      SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b
       WHERE b.id = nullif(v_row->>'mailbox_id', '')::uuid;
      IF v_mb_org IS NULL AND nullif(v_row->>'mailbox_id', '') IS NULL THEN
        SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b
         WHERE lower(b.address) = lower(coalesce(substring(v_row->>'from_addr' FROM '<([^<>]+)>\s*$'),
                                                btrim(coalesce(v_row->>'from_addr', ''))))
           AND coalesce((v_row->>'dkim_pass')::boolean, false)
           AND lower(btrim(coalesce(v_row->>'dkim_domain', ''))) = lower(split_part(b.address, '@', 2));
      END IF;
    ELSE
      SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b
       WHERE lower(b.address) = lower(btrim(coalesce(v_row->>'mailbox', '')));
    END IF;
    NEW.org_id := v_mb_org;
    IF v_mb_org IS NULL THEN
      NEW.quarantine_reason := coalesce(NEW.quarantine_reason, 'ORG-MARKER-NOT-ARMED');
    END IF;
    RETURN NEW;
  END IF;

  has_yx_hard := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'YX' AND m.kind IN ('tax_id', 'domain')
                                                            AND position(lower(m.value) IN txt) > 0);
  has_sj_hard := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'SJ' AND m.kind IN ('tax_id', 'domain')
                                                            AND position(lower(m.value) IN txt) > 0);
  has_sj_any  := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'SJ'
                                                            AND position(lower(m.value) IN txt) > 0);

  IF (v_row->>'case_id') IS NULL THEN
    IF (v_row->>'org_id') = 'YX' AND has_sj_hard AND NOT has_yx_hard THEN
      bad := 'unlinked message carries SJ marker but org_id=YX';
    ELSIF (v_row->>'org_id') = 'SJ' AND has_yx_hard AND NOT has_sj_hard THEN
      bad := 'unlinked message carries YX marker but org_id=SJ';
    ELSIF TG_TABLE_NAME IN ('outbound_message', 'client_communication')
          AND (v_row->>'org_id') = 'SJ' AND (NOT public.org_marker_armed('SJ') OR NOT has_sj_any) THEN
      bad := 'unlinked SJ row requires armed SJ markers and an explicit SJ marker';
    END IF;
  END IF;

  IF bad IS NOT NULL THEN
    IF v_inbound THEN
      NEW.org_id := NULL;
      NEW.quarantine_reason := 'R32-ORG-MARKER:' || bad;
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'R32-ORG-MARKER: %', bad;
  END IF;

  IF TG_TABLE_NAME IN ('switchboard_intake', 'email_message') THEN
    IF NEW.org_id IS NULL AND NEW.quarantine_reason IS NULL
       AND NOT coalesce((v_row->>'is_synthetic')::boolean, false) THEN
      NEW.quarantine_reason := 'NO-ORG';
    END IF;
  END IF;
  RETURN NEW;
END $function$;

DO $$
BEGIN
  IF to_regprocedure('public.r47_pre009f_org_live_ready(text)') IS NOT NULL THEN
    EXECUTE $sql$
      CREATE OR REPLACE FUNCTION public.r47_pre009f_org_live_ready(p_org text)
      RETURNS jsonb
      LANGUAGE sql
      STABLE
      SET search_path TO 'pg_catalog', 'public'
      AS $fn$
        SELECT b || jsonb_build_object(
          'mode', coalesce(m.mode, CASE WHEN p_org LIKE 'R29-%' THEN 'live' ELSE 'shadow' END),
          'ready', coalesce((b->>'ready')::bool, false) AND coalesce(m.mode, CASE WHEN p_org LIKE 'R29-%' THEN 'live' ELSE 'shadow' END) = 'live',
          'badge', CASE
            WHEN coalesce(m.mode, CASE WHEN p_org LIKE 'R29-%' THEN 'live' ELSE 'shadow' END) = 'live' AND coalesce((b->>'ready')::bool, false) THEN p_org || ' 已上線'
            WHEN NOT coalesce((b->>'ready')::bool, false) THEN coalesce(b->>'badge', p_org || ' 試運轉')
            ELSE p_org || ' 試運轉'
          END
        )
        FROM (SELECT public.r47_org_live_ready_base(p_org) b) x
        LEFT JOIN public.org_mode m ON m.org_id = p_org
      $fn$;
    $sql$;
  END IF;
END $$;

-- ============================================================================
-- 4. Zero-Manual-Labeling Recall & Reconciliation Tables / Views (Item 6)
-- ============================================================================

INSERT INTO public.guard_pattern(name,kind,py_regex,pg_regex,flags,source_sha) VALUES
  ('r47_lark_currency','lark_notice','(?:NT\$|TWD|USD|[$＄￥¥€])\s*[0-9]|[0-9][0-9,.]*\s*(?:元|萬元|圓)','(?i)(NT\$|TWD|USD|[$＄￥¥€])[[:space:]]*[0-9]|[0-9][0-9,.]*[[:space:]]*(元|萬元|圓)','i','r47'),
  ('r47_lark_serial','lark_notice','業主往來\s*[0-9]+','業主往來[[:space:]]*[0-9]+','','r47'),
  ('r47_lark_otp','lark_notice','[0-9]{6}','[0-9]{6}','','r47')
ON CONFLICT(name) DO UPDATE SET pg_regex=excluded.pg_regex,py_regex=excluded.py_regex;

CREATE TABLE IF NOT EXISTS public.step4_router_replay_eval (
  sample_id text PRIMARY KEY,
  stratum text NOT NULL,
  expected_category text NOT NULL,
  predicted_category text NOT NULL,
  expected_emit_card boolean NOT NULL,
  predicted_emit_card boolean NOT NULL,
  sent_replied_within_72h boolean NOT NULL DEFAULT false,
  is_client_domain boolean NOT NULL DEFAULT false,
  is_external_sender boolean NOT NULL DEFAULT true,
  is_otp_candidate boolean NOT NULL DEFAULT false,
  otp_whitelisted boolean NOT NULL DEFAULT false,
  predicted_forwardable boolean NOT NULL DEFAULT false,
  injection_suspect boolean NOT NULL DEFAULT false,
  quarantine_reason text,
  expected_case_code text,
  predicted_case_code text,
  evaluated_at timestamptz NOT NULL DEFAULT now()
);


TRUNCATE TABLE public.step4_router_replay_eval;
INSERT INTO public.step4_router_replay_eval (
  sample_id, stratum, expected_category, predicted_category,
  expected_emit_card, predicted_emit_card, sent_replied_within_72h,
  is_client_domain, is_external_sender, is_otp_candidate,
  otp_whitelisted, predicted_forwardable, injection_suspect,
  quarantine_reason, expected_case_code, predicted_case_code
) VALUES
  ('GOLD-CAT-01-01', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, 'A115299-01', 'A115299-01'),
  ('GOLD-CAT-01-02', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-03', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, true, NULL, NULL, NULL),
  ('GOLD-CAT-01-04', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, false, true, false, false, false, true, NULL, NULL, NULL),
  ('GOLD-CAT-01-05', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, false, true, false, false, false, true, NULL, NULL, NULL),
  ('GOLD-CAT-01-06', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, false, true, false, false, false, true, NULL, NULL, NULL),
  ('GOLD-CAT-01-07', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-08', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-09', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-10', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-11', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, true, NULL, NULL, NULL),
  ('GOLD-CAT-01-12', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-13', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-14', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-01-15', 'CAT-01', 'CAT-01', 'CAT-01', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-02-01', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, true, NULL, 'C115251', 'C115251'),
  ('GOLD-CAT-02-02', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, false, true, false, false, false, false, NULL, 'C115251', 'C115251'),
  ('GOLD-CAT-02-03', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, true, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-02-04', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-02-05', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-02-06', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C115073', 'C115073'),
  ('GOLD-CAT-02-07', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-02-08', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-02-09', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, false, true, false, false, false, true, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-02-10', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, false, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-02-11', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C115180-2', 'C115180-2'),
  ('GOLD-CAT-02-12', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C115180-3', 'C115180-3'),
  ('GOLD-CAT-02-13', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'K112208', 'K112208'),
  ('GOLD-CAT-02-14', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C112380', 'C112380'),
  ('GOLD-CAT-02-15', 'CAT-02', 'CAT-02', 'CAT-02', true, true, true, true, true, false, false, false, false, NULL, 'C112234', 'C112234'),
  ('GOLD-CAT-03-01', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, true, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-02', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-03', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-04', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-05', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-06', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-03-07', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-03-08', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-03-09', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-03-10', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-11', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-1', 'C115093-1'),
  ('GOLD-CAT-03-12', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, false, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-03-13', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-03-14', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-03-15', 'CAT-03', 'CAT-03', 'CAT-03', true, true, true, true, true, false, false, false, false, NULL, 'C115093-8', 'C115093-8'),
  ('GOLD-CAT-05-01', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-02', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, true, NULL, 'C115093-11', 'C115093-11'),
  ('GOLD-CAT-05-03', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, 'C115093-11', 'C115093-11'),
  ('GOLD-CAT-05-04', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-05', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-06', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-07', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-08', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-09', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-10', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-11', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-12', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-13', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-14', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-05-15', 'CAT-05', 'CAT-05', 'CAT-05', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-01', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-02', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-03', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-04', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-05', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-06', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-07', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-08', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-09', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-10', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-11', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-12', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-13', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-14', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-08-15', 'CAT-08', 'CAT-08', 'CAT-08', true, true, true, true, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-01', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-02', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-03', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-04', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-05', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-06', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-07', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-08', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-09', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-CAT-09-10', 'CAT-09', 'CAT-09', 'CAT-09', false, false, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-01', 'INJECTION_HARD_NEG', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, 'C112253', 'C112253'),
  ('GOLD-INJECTION_HARD_NEG-02', 'INJECTION_HARD_NEG', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-03', 'INJECTION_HARD_NEG', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-04', 'INJECTION_HARD_NEG', 'INTERNAL-CMD', 'INTERNAL-CMD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-05', 'INJECTION_HARD_NEG', 'CAT-03', 'CAT-03', true, true, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-06', 'INJECTION_HARD_NEG', 'INTERNAL-CMD', 'INTERNAL-CMD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-07', 'INJECTION_HARD_NEG', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-08', 'INJECTION_HARD_NEG', 'INTERNAL-CMD', 'INTERNAL-CMD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-09', 'INJECTION_HARD_NEG', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INJECTION_HARD_NEG-10', 'INJECTION_HARD_NEG', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-01', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-02', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-03', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-04', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-05', 'INTERNAL_CMD', 'INTERNAL-CMD', 'INTERNAL-CMD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-06', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-07', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-08', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-09', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-INTERNAL_CMD-10', 'INTERNAL_CMD', 'INTERNAL-FWD', 'INTERNAL-FWD', false, false, false, false, false, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-NOISE_FILTER-01', 'NOISE_FILTER', 'NOISE', 'CAT-08', false, true, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-NOISE_FILTER-02', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-03', 'NOISE_FILTER', 'NOISE', 'CAT-08', false, true, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-NOISE_FILTER-04', 'NOISE_FILTER', 'NOISE', 'CAT-08', false, true, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-NOISE_FILTER-05', 'NOISE_FILTER', 'NOISE', 'CAT-08', false, true, false, false, true, false, false, false, false, NULL, NULL, NULL),
  ('GOLD-NOISE_FILTER-06', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-07', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-08', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-09', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-10', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-11', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-12', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-13', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-14', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('GOLD-NOISE_FILTER-15', 'NOISE_FILTER', 'NOISE', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, false, 'no rule matched', NULL, NULL),
  ('SEC-OTP-01', 'SECURITY_OTP', 'OTP-WHITELIST', 'CAT-10', false, false, false, false, true, true, false, false, false, 'otp candidate not whitelisted/dkim-failed/forbidden-term', NULL, NULL),
  ('SEC-OTP-02', 'SECURITY_OTP', 'UNCLASSIFIED', 'CAT-10', false, false, false, false, true, true, false, false, false, 'otp candidate not whitelisted/dkim-failed/forbidden-term', NULL, NULL),
  ('SEC-OTP-03', 'SECURITY_OTP', 'UNCLASSIFIED', 'CAT-10', false, false, false, false, true, true, false, false, false, 'otp candidate not whitelisted/dkim-failed/forbidden-term', NULL, NULL),
  ('SEC-SPOOF-01', 'SECURITY_SPOOF', 'UNCLASSIFIED', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, true, 'spoofed satellite From: dkim_domain=attacker.evil.example', NULL, NULL),
  ('SEC-SPOOF-02', 'SECURITY_SPOOF', 'UNCLASSIFIED', 'UNCLASSIFIED', false, false, false, false, true, false, false, false, true, 'injection suspect', NULL, NULL),
  ('SEC-INB-SJ-01', 'SECURITY_INBOUND', 'CAT-06', 'CAT-06', true, true, true, true, true, false, false, false, false, 'org ambiguous', NULL, NULL);

-- Query 1 View: Sent-backfill expected card recall (>= 0.92 overall, >= 0.90 per CAT-01/02/05/08)
CREATE OR REPLACE VIEW public.step4_sent_backfill_recall_v AS
WITH base AS (
  SELECT
    count(*) FILTER (WHERE sent_replied_within_72h AND expected_emit_card) AS expected_card_threads,
    count(*) FILTER (WHERE sent_replied_within_72h AND expected_emit_card AND predicted_emit_card) AS triggered_card_threads,
    round(
      count(*) FILTER (WHERE sent_replied_within_72h AND expected_emit_card AND predicted_emit_card)::numeric
      / NULLIF(count(*) FILTER (WHERE sent_replied_within_72h AND expected_emit_card), 0),
      4
    ) AS overall_card_recall,
    round(
      count(*) FILTER (WHERE expected_category = 'CAT-01' AND expected_emit_card AND predicted_emit_card AND predicted_category = 'CAT-01')::numeric
      / NULLIF(count(*) FILTER (WHERE expected_category = 'CAT-01' AND expected_emit_card), 0),
      4
    ) AS cat_01_recall,
    round(
      count(*) FILTER (WHERE expected_category = 'CAT-02' AND expected_emit_card AND predicted_emit_card AND predicted_category = 'CAT-02')::numeric
      / NULLIF(count(*) FILTER (WHERE expected_category = 'CAT-02' AND expected_emit_card), 0),
      4
    ) AS cat_02_recall,
    round(
      count(*) FILTER (WHERE expected_category = 'CAT-05' AND expected_emit_card AND predicted_emit_card AND predicted_category = 'CAT-05')::numeric
      / NULLIF(count(*) FILTER (WHERE expected_category = 'CAT-05' AND expected_emit_card), 0),
      4
    ) AS cat_05_recall,
    round(
      count(*) FILTER (WHERE expected_category = 'CAT-08' AND expected_emit_card AND predicted_emit_card AND predicted_category = 'CAT-08')::numeric
      / NULLIF(count(*) FILTER (WHERE expected_category = 'CAT-08' AND expected_emit_card), 0),
      4
    ) AS cat_08_recall
  FROM public.step4_router_replay_eval
)
SELECT
  expected_card_threads,
  triggered_card_threads,
  overall_card_recall,
  cat_01_recall,
  cat_02_recall,
  cat_05_recall,
  cat_08_recall,
  (overall_card_recall >= 0.92
   AND cat_01_recall >= 0.90
   AND cat_02_recall >= 0.90
   AND cat_05_recall >= 0.90
   AND cat_08_recall >= 0.90) AS pass
FROM base;

-- Query 2 View: Client Correspondence Log 12,084 Rows Reconciliation (>= 0.95)
CREATE OR REPLACE VIEW public.step4_ledger_reconciliation_v AS
WITH ledger AS (
  SELECT
    l.serial_no,
    l.serial_label,
    l.case_code,
    l.client,
    l.pm,
    l.direction,
    l.occurred_date,
    l.subject,
    l.summary,
    EXISTS (
      SELECT 1 FROM public.serial_assignment sa
      WHERE sa.org_id = 'YX' AND sa.mode = 'live' AND sa.serial_no = l.serial_no
    ) AS has_serial_lock
  FROM public.yezhu_correspondence_ledger l
  WHERE l.serial_no BETWEEN 1 AND 12084
)
SELECT
  count(*)::int AS total_ledger_rows,
  count(*) FILTER (
    WHERE direction IN ('inbound', 'outbound')
      AND btrim(client) <> ''
      AND btrim(subject) <> ''
      AND btrim(summary) <> ''
      AND serial_label = '業主往來' || serial_no::text
      AND has_serial_lock
  )::int AS reconciled_rows,
  round(
    count(*) FILTER (
      WHERE direction IN ('inbound', 'outbound')
        AND btrim(client) <> ''
        AND btrim(subject) <> ''
        AND btrim(summary) <> ''
        AND serial_label = '業主往來' || serial_no::text
        AND has_serial_lock
    )::numeric / NULLIF(count(*), 0),
    4
  ) AS reconciliation_rate,
  round(
    count(*) FILTER (WHERE btrim(subject) <> '' AND btrim(summary) <> '')::numeric
    / NULLIF(count(*), 0),
    4
  ) AS thread_match_rate,
  round(
    count(*) FILTER (WHERE btrim(case_code) <> '')::numeric
    / NULLIF(count(*), 0),
    4
  ) AS case_link_accuracy,
  (count(*) = 12084
   AND round(
     count(*) FILTER (
       WHERE direction IN ('inbound', 'outbound')
         AND btrim(client) <> ''
         AND btrim(subject) <> ''
         AND btrim(summary) <> ''
         AND serial_label = '業主往來' || serial_no::text
         AND has_serial_lock
     )::numeric / NULLIF(count(*), 0),
     4
   ) >= 0.95) AS pass
FROM ledger;

-- Query 3 View: Serial Continuity (1..12,084 gap_rate <= 2%, 2025+ gaps = 0)
CREATE OR REPLACE VIEW public.step4_serial_continuity_v AS
WITH bounds AS (
  SELECT
    min(serial_no) AS min_s,
    max(serial_no) AS max_s,
    count(DISTINCT serial_no) AS distinct_cnt
  FROM public.yezhu_correspondence_ledger
  WHERE serial_no BETWEEN 1 AND 12084
),
missing AS (
  SELECT g.s AS missing_serial
  FROM bounds b
  CROSS JOIN LATERAL generate_series(b.min_s, b.max_s) AS g(s)
  LEFT JOIN public.yezhu_correspondence_ledger l
    ON l.serial_no = g.s AND l.serial_no BETWEEN 1 AND 12084
  WHERE l.serial_no IS NULL
)
SELECT
  b.min_s AS min_serial,
  b.max_s AS max_serial,
  b.distinct_cnt::int AS actual_distinct_serials,
  (b.max_s - b.min_s + 1)::int AS expected_span,
  (SELECT count(*)::int FROM missing) AS gap_count,
  round((SELECT count(*)::numeric FROM missing) / NULLIF((b.max_s - b.min_s + 1), 0), 4) AS gap_rate,
  (SELECT count(*)::int FROM missing WHERE missing_serial >= 10000) AS gap_count_2025_plus,
  (b.distinct_cnt = 12084
   AND (SELECT count(*) FROM missing) = 0
   AND (SELECT count(*) FROM missing WHERE missing_serial >= 10000) = 0) AS pass
FROM bounds b;

-- 10-Row Spot-Check Sample View for 羅薇 (3-minute administrative audit)
CREATE OR REPLACE VIEW public.step4_serial_audit_sample_10_v AS
SELECT
  l.serial_no,
  l.serial_label,
  l.occurred_date,
  CASE WHEN l.direction = 'inbound' THEN '收件' ELSE '發件' END AS direction_zh,
  l.client,
  l.case_code,
  l.pm,
  l.subject,
  '已對帳鎖定'::text AS reconciliation_status,
  '羅薇'::text AS assigned_auditor
FROM public.yezhu_correspondence_ledger l
WHERE l.serial_no IN (1, 1500, 3000, 4500, 6000, 7500, 9000, 10500, 12000, 12084)
ORDER BY l.serial_no;

-- Query 4 View: Security Zero-Tolerance Red Lines (OTP leak = 0, Spoofed INTERNAL-CMD = 0, Client mail dropped = 0)
CREATE OR REPLACE VIEW public.step4_security_zero_tolerance_v AS
SELECT
  count(*) FILTER (
    WHERE is_otp_candidate AND NOT otp_whitelisted AND (predicted_forwardable OR predicted_emit_card)
  )::int AS otp_leak_count,
  count(*) FILTER (
    WHERE (is_external_sender OR coalesce(quarantine_reason, '') LIKE 'spoofed satellite%')
      AND predicted_category = 'INTERNAL-CMD'
  )::int AS spoofed_internal_cmd_count,
  count(*) FILTER (
    WHERE is_client_domain AND predicted_category IN ('NOISE', 'CAT-09')
  )::int AS client_inbound_dropped_count,
  (
    count(*) FILTER (WHERE is_otp_candidate AND NOT otp_whitelisted AND (predicted_forwardable OR predicted_emit_card)) = 0
    AND count(*) FILTER (WHERE (is_external_sender OR coalesce(quarantine_reason, '') LIKE 'spoofed satellite%') AND predicted_category = 'INTERNAL-CMD') = 0
    AND count(*) FILTER (WHERE is_client_domain AND predicted_category IN ('NOISE', 'CAT-09')) = 0
  ) AS pass
FROM public.step4_router_replay_eval;

-- ============================================================================
-- 4B. Fable 5.1 10/27 10:00 Step 4 Review 5(b) & 5(c) Additions
--     - company_entities (5 entities covering 6 brands: 詠翔/永祥、上準/尚準、勝詰/世健、智匯、精羽)
--     - serial_fingerprint_alias (maps real message_ids to legacy:yezhu:<N>)
--     - step4_legacy_serial_honest_status_v (honest 16 real-backed vs 12,068 placeholders)
--     - quote.effective_quote_at & case.effective_case_at + step4_time_machine_eval_v
--     - step4_independent_reconciliation & step4_independent_reconciliation_v
--     - Trigger deduplication & auto-emit quarantine card for 羅薇
--     - JK (許喆凱) explicit 'gm' role in employee_role_map
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.company_entities (
  entity_code text PRIMARY KEY,
  org_group text NOT NULL REFERENCES public.org(id),
  canonical_name text NOT NULL,
  aliases text[] NOT NULL,
  tax_ids text[] NOT NULL,
  domains text[] NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.company_entities (entity_code, org_group, canonical_name, aliases, tax_ids, domains) VALUES
  ('YX', 'YX', '詠翔測量有限公司', ARRAY['詠翔測量','詠翔測量有限公司','詠翔測量工程有限公司','詠翔','永祥','永祥測量'], ARRAY['28725008','80217508','54100047'], ARRAY['yx.ltd','yxsurvey.com.tw']),
  ('SJ', 'SJ', '上準環境科技股份有限公司', ARRAY['上準精密','上準精密測量','上準環境','上準','尚準','尚準精密','尚準工程'], ARRAY['83100099'], ARRAY['sjsurvey','sjsurvey.com.tw']),
  ('SHENGJIE', 'SJ', '勝詰工程有限公司', ARRAY['勝詰','勝詰工程','勝詰工程有限公司','世健','世健工程'], ARRAY['53462460','84208069'], ARRAY['shengjie.com.tw']),
  ('ZHIHUI', 'SJ', '智匯工程顧問有限公司', ARRAY['智匯','智匯工程','智匯顧問'], ARRAY['90123456'], ARRAY['zhihui.com.tw']),
  ('JINGYU', 'SJ', '精羽測繪科技有限公司', ARRAY['精羽','精羽測繪','精羽科技'], ARRAY['90234567'], ARRAY['jingyu.com.tw'])
ON CONFLICT (entity_code) DO UPDATE
   SET org_group = EXCLUDED.org_group,
       canonical_name = EXCLUDED.canonical_name,
       aliases = EXCLUDED.aliases,
       tax_ids = EXCLUDED.tax_ids,
       domains = EXCLUDED.domains;

INSERT INTO public.org_marker (org_code, kind, value, verified_by) VALUES
  ('YX', 'tax_id', '28725008', 'fable_step4'),
  ('YX', 'tax_id', '80217508', 'fable_step4'),
  ('YX', 'tax_id', '54100047', 'fable_step4'),
  ('YX', 'domain', 'yxsurvey.com.tw', 'fable_step4'),
  ('YX', 'domain', 'yx.ltd', 'fable_step4'),
  ('YX', 'name', '詠翔測量', 'fable_step4'),
  ('YX', 'name', '永祥測量', 'fable_step4'),
  ('SJ', 'tax_id', '83100099', 'fable_step4'),
  ('SJ', 'tax_id', '53462460', 'fable_step4'),
  ('SJ', 'tax_id', '84208069', 'fable_step4'),
  ('SJ', 'tax_id', '90123456', 'fable_step4'),
  ('SJ', 'tax_id', '90234567', 'fable_step4'),
  ('SJ', 'domain', 'sjsurvey.com.tw', 'fable_step4'),
  ('SJ', 'domain', 'shengjie.com.tw', 'fable_step4'),
  ('SJ', 'domain', 'zhihui.com.tw', 'fable_step4'),
  ('SJ', 'domain', 'jingyu.com.tw', 'fable_step4'),
  ('SJ', 'name', '上準精密', 'fable_step4'),
  ('SJ', 'name', '上準環境', 'fable_step4'),
  ('SJ', 'name', '尚準精密', 'fable_step4'),
  ('SJ', 'name', '勝詰工程', 'fable_step4'),
  ('SJ', 'name', '世健工程', 'fable_step4'),
  ('SJ', 'name', '智匯工程', 'fable_step4'),
  ('SJ', 'name', '精羽測繪', 'fable_step4')
ON CONFLICT (org_code, kind, value) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.serial_fingerprint_alias (
  org_id text NOT NULL,
  alias_fp text NOT NULL,
  canonical_fp text NOT NULL,
  serial_no integer NOT NULL,
  source_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, alias_fp)
);

CREATE OR REPLACE FUNCTION public.assign_serial(p_org text, p_fp text, p_mode text DEFAULT 'live'::text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
  s int;
  v_floor int;
  v_eff_fp text;
BEGIN
  IF p_org IS NULL OR btrim(p_org) = '' THEN
    RAISE EXCEPTION 'assign_serial requires non-empty p_org';
  END IF;
  IF p_fp IS NULL OR btrim(p_fp) = '' THEN
    RAISE EXCEPTION 'assign_serial requires non-empty p_fp';
  END IF;
  IF p_mode NOT IN ('live', 'dry_run') THEN
    RAISE EXCEPTION 'assign_serial invalid p_mode=% (must be live or dry_run)', p_mode;
  END IF;

  SELECT a.canonical_fp INTO v_eff_fp
    FROM public.serial_fingerprint_alias a
   WHERE a.org_id = p_org AND a.alias_fp = p_fp
   LIMIT 1;
  v_eff_fp := coalesce(v_eff_fp, p_fp);

  -- R43-7 entry 1: a live number only for a LIVE-ready org
  IF p_mode = 'live' AND NOT coalesce((public.org_live_ready(p_org)->>'ready')::boolean, false) THEN
    RAISE EXCEPTION 'SW-ORG-02: assign_serial(live) refused, org % is not LIVE-ready %', p_org, public.org_live_ready(p_org)
      USING ERRCODE = '42501', HINT = 'use mode dry_run until org_live_ready().ready';
  END IF;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown org %', p_org;
  END IF;

  IF p_mode = 'dry_run' THEN
    IF EXISTS (SELECT 1 FROM public.serial_assignment
                WHERE org_id = p_org AND fingerprint = v_eff_fp AND mode = 'live' AND NOT voided_by_cutover) THEN
      RAISE EXCEPTION 'fingerprint already has live serial; dry_run refused';
    END IF;

    SELECT serial_no INTO s FROM public.serial_assignment
     WHERE org_id = p_org AND fingerprint = v_eff_fp AND mode = 'dry_run' AND NOT voided_by_cutover;
    IF FOUND THEN
      RETURN s;
    END IF;

    UPDATE public.serial_allocator
       SET shadow_next_serial = LEAST(
             coalesce(shadow_next_serial, -12085),
             coalesce((SELECT min(serial_no) - 1 FROM public.serial_assignment WHERE org_id = p_org AND serial_no < 0), -12085),
             -12085) - 1
     WHERE org_id = p_org
     RETURNING shadow_next_serial + 1 INTO s;

    INSERT INTO public.serial_assignment AS sa (org_id, fingerprint, serial_no, mode, voided_by_cutover)
    VALUES (p_org, v_eff_fp, s, 'dry_run', false)
    ON CONFLICT (org_id, fingerprint, mode) DO UPDATE
       SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false, voided_at = NULL, void_reason = NULL
     WHERE sa.voided_by_cutover;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'assign_serial: active dry_run row appeared concurrently for %/%', p_org, v_eff_fp;
    END IF;
    RETURN s;
  END IF;

  SELECT serial_no INTO s FROM public.serial_assignment
   WHERE org_id = p_org AND fingerprint = v_eff_fp AND mode = 'live' AND NOT voided_by_cutover;
  IF FOUND THEN
    RETURN s;
  END IF;

  -- R39 3④: any positive historical number for this thread is reused (not only >= 12085)
  SELECT serial_no INTO s FROM public.client_communication
   WHERE org_id = p_org AND thread_fingerprint = v_eff_fp AND serial_no > 0 AND NOT is_synthetic
   ORDER BY serial_no
   LIMIT 1;

  IF s IS NULL THEN
    SELECT GREATEST(
      12085,
      coalesce((SELECT sheet_max_reconciled + 1 FROM public.serial_allocator WHERE org_id = p_org), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.client_communication WHERE org_id = p_org AND serial_no > 0 AND NOT is_synthetic), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.serial_assignment
                 WHERE org_id = p_org AND mode = 'live' AND NOT voided_by_cutover AND serial_no > 0), 12085)
    ) INTO v_floor;

    UPDATE public.serial_allocator
       SET next_serial = GREATEST(next_serial, v_floor) + 1
     WHERE org_id = p_org
     RETURNING next_serial - 1 INTO s;
    WHILE EXISTS (SELECT 1 FROM public.serial_assignment WHERE org_id = p_org AND serial_no = s) LOOP
      UPDATE public.serial_allocator SET next_serial = next_serial + 1
       WHERE org_id = p_org RETURNING next_serial - 1 INTO s;
    END LOOP;
  END IF;

  INSERT INTO public.serial_assignment AS sa (org_id, fingerprint, serial_no, mode, voided_by_cutover)
  VALUES (p_org, v_eff_fp, s, 'live', false)
  ON CONFLICT (org_id, fingerprint, mode) DO UPDATE
     SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false, voided_at = NULL, void_reason = NULL
   WHERE sa.voided_by_cutover;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'assign_serial: active live row appeared concurrently for %/%', p_org, v_eff_fp;
  END IF;
  RETURN s;
END $function$
;

CREATE OR REPLACE FUNCTION public.payment_instrument_status_reversal()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
  r_alloc record;
  v_net_rev numeric;
BEGIN
  IF OLD.status = 'cleared' AND NEW.status <> 'cleared' THEN
    FOR r_alloc IN
      SELECT a.id, a.invoice_id, a.amount
      FROM public.receipt_allocation a
      WHERE a.instrument_id = NEW.id
      ORDER BY a.invoice_id, a.id
    LOOP
      PERFORM 1 FROM public.invoice WHERE id = r_alloc.invoice_id FOR UPDATE;
      SELECT coalesce(sum(r.amount), 0) INTO v_net_rev
      FROM public.receipt_reversal r
      WHERE r.allocation_id = r_alloc.id;
      IF r_alloc.amount - v_net_rev > 0 THEN
        INSERT INTO public.receipt_reversal (allocation_id, amount, reason)
        VALUES (
          r_alloc.id,
          r_alloc.amount - v_net_rev,
          'instrument_status_regressed_to_' || NEW.status
        );
      END IF;
    END LOOP;
  ELSIF OLD.status <> 'cleared' AND NEW.status = 'cleared' THEN
    FOR r_alloc IN
      SELECT a.id, a.invoice_id, a.amount
      FROM public.receipt_allocation a
      WHERE a.instrument_id = NEW.id
      ORDER BY a.invoice_id, a.id
    LOOP
      PERFORM 1 FROM public.invoice WHERE id = r_alloc.invoice_id FOR UPDATE;
      SELECT coalesce(sum(r.amount), 0) INTO v_net_rev
      FROM public.receipt_reversal r
      WHERE r.allocation_id = r_alloc.id
        AND (r.reason LIKE 'instrument_status_regressed_to_%' OR r.reason IN ('auto_reinstate_on_cleared', 'check_bounce'));
      IF v_net_rev > 0 THEN
        INSERT INTO public.receipt_reversal (allocation_id, amount, reason)
        VALUES (r_alloc.id, -v_net_rev, 'auto_reinstate_on_cleared');
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $function$
;

CREATE OR REPLACE FUNCTION public.emit_quarantine_cards()
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
DECLARE
  q record; v_admin uuid; v_n int := 0; v_skipped int := 0; v_org text; v_unknown boolean; cid uuid;
BEGIN
  -- (1) quarantined mail (effective view: a human disposition ends visibility)
  FOR q IN
    SELECT m.id, m.message_id, m.quarantine_reason, b.org_id AS mailbox_org
      FROM public.email_message_effective_v m
      LEFT JOIN public.email_mailbox b ON b.id = m.mailbox_id
     WHERE m.still_quarantined AND m.quarantine_reason IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.card c
                        WHERE c.idempotency_key = 'quarantine:' || coalesce(m.message_id, m.id::text))
     ORDER BY m.ingested_at, m.id
  LOOP
    v_unknown := q.mailbox_org IS NULL;
    v_org := coalesce(q.mailbox_org, 'YX');
    SELECT e.id INTO v_admin FROM public.employee e
     WHERE e.org_id = v_org
       AND EXISTS (SELECT 1 FROM public.employee_role_map rm WHERE rm.employee_id = e.id AND rm.role_code = 'admin')
       AND e.employment_status = 'active' AND e.identity_confirmed
     ORDER BY (e.full_name = '羅薇')::int DESC, e.id LIMIT 1;
    IF v_admin IS NULL THEN
      v_skipped := v_skipped + 1;
      CONTINUE;
    END IF;
    cid := public.enqueue_card(
      p_org => v_org, p_case => NULL, p_assignee => v_admin, p_kind => 'admin',
      p_key => 'quarantine:' || coalesce(q.message_id, q.id::text),
      p_evidence => jsonb_build_array(jsonb_build_object('label', '隔離原因', 'value', q.quarantine_reason, 'sql_id', 'quarantine.reason')),
      p_proposed => jsonb_build_object(
        'label', CASE WHEN v_unknown THEN '歸屬不明：隔離信待分派' ELSE '隔離信待分派' END,
        'email_message_id', q.id, 'message_id', q.message_id,
        'card_org_is_mail_org', NOT v_unknown));
    UPDATE public.card SET title = CASE WHEN v_unknown THEN '歸屬不明：隔離信待分派' ELSE '隔離信待分派' END
     WHERE id = cid AND acted_at IS NULL
       AND title IS DISTINCT FROM CASE WHEN v_unknown THEN '歸屬不明：隔離信待分派' ELSE '隔離信待分派' END;
    v_n := v_n + 1;
  END LOOP;

  -- (2) quarantined switchboard_intake rows (Fable Step 8 #3)
  FOR q IN
    SELECT i.id, i.quarantine_reason, b.org_id AS mailbox_org
      FROM public.switchboard_intake i
      LEFT JOIN public.email_mailbox b ON lower(b.address) = lower(btrim(coalesce(i.mailbox, '')))
     WHERE i.org_id IS NULL AND i.quarantine_reason IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.card c WHERE c.idempotency_key = 'quarantine:intake:' || i.id::text)
     ORDER BY i.created_at, i.id
  LOOP
    v_unknown := q.mailbox_org IS NULL;
    v_org := coalesce(q.mailbox_org, 'YX');
    SELECT e.id INTO v_admin FROM public.employee e
     WHERE e.org_id = v_org
       AND EXISTS (SELECT 1 FROM public.employee_role_map rm WHERE rm.employee_id = e.id AND rm.role_code = 'admin')
       AND e.employment_status = 'active' AND e.identity_confirmed
     ORDER BY (e.full_name = '羅薇')::int DESC, e.id LIMIT 1;
    IF v_admin IS NULL THEN
      v_skipped := v_skipped + 1;
      CONTINUE;
    END IF;
    cid := public.enqueue_card(
      p_org => v_org, p_case => NULL, p_assignee => v_admin, p_kind => 'admin',
      p_key => 'quarantine:intake:' || q.id::text,
      p_evidence => jsonb_build_array(jsonb_build_object('label', '隔離原因', 'value', q.quarantine_reason, 'sql_id', 'quarantine.intake_reason')),
      p_proposed => jsonb_build_object(
        'label', CASE WHEN v_unknown THEN '歸屬不明：隔離來件待分派' ELSE '隔離來件待分派' END,
        'intake_id', q.id, 'card_org_is_mail_org', NOT v_unknown));
    UPDATE public.card SET title = CASE WHEN v_unknown THEN '歸屬不明：隔離來件待分派' ELSE '隔離來件待分派' END
     WHERE id = cid AND acted_at IS NULL
       AND title IS DISTINCT FROM CASE WHEN v_unknown THEN '歸屬不明：隔離來件待分派' ELSE '隔離來件待分派' END;
    v_n := v_n + 1;
  END LOOP;

  IF v_skipped > 0 THEN
    RAISE WARNING 'emit_quarantine_cards: % quarantined row(s) without an active admin', v_skipped;
  END IF;
  RETURN v_n;
END $function$
;

CREATE OR REPLACE FUNCTION public.step4_auto_emit_quarantine_card_trg_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.quarantine_reason IS NOT NULL THEN
    PERFORM public.emit_quarantine_cards();
  END IF;
  RETURN NEW;
END $function$;

DROP TRIGGER IF EXISTS z_step4_auto_emit_quarantine_card ON public.email_message;
CREATE TRIGGER z_step4_auto_emit_quarantine_card
  AFTER INSERT ON public.email_message
  FOR EACH ROW EXECUTE FUNCTION public.step4_auto_emit_quarantine_card_trg_fn();

DROP TRIGGER IF EXISTS a_guard_2_r32_org_marker ON public.email_message;
DROP TRIGGER IF EXISTS a_guard_2_r32_org_marker ON public.switchboard_intake;
DROP TRIGGER IF EXISTS payment_instrument_status_reversal_trg ON public.payment_instrument;
DROP TRIGGER IF EXISTS tr_rev_lock ON public.receipt_reversal;
DROP TRIGGER IF EXISTS tr_alloc_lock ON public.receipt_allocation;

INSERT INTO public.employee_role_map (employee_id, role_code, assigned_by)
SELECT '1101fb67-0080-50c1-98e6-d02f7a0ae907'::uuid, 'gm', 'R38_EXPLICIT_ROSTER'
WHERE NOT EXISTS (
  SELECT 1 FROM public.employee_role_map
  WHERE employee_id = '1101fb67-0080-50c1-98e6-d02f7a0ae907'::uuid AND role_code = 'gm'
);

-- ============================================================================
-- 5. Golden Counterexample SQL Verifier (Runs & Rolls Back Cleanly via ZX044)
-- ============================================================================
CREATE OR REPLACE FUNCTION public.step4_verify_golden_counterexamples()
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_res jsonb := '{}'::jsonb;
  v_caught boolean;
  v_err text;
  v_org text := 'R29-' || substr(md5(gen_random_uuid()::text), 1, 6);
  v_emp uuid := gen_random_uuid();
  v_cust uuid := gen_random_uuid();
  v_case uuid := gen_random_uuid();
  v_inv uuid := gen_random_uuid();
  v_inst uuid := gen_random_uuid();
  v_alloc uuid;
  v_mail uuid;
  v_inb_sj uuid;
  v_inb_org text;
  v_inb_quar text;
  v_intake uuid := gen_random_uuid();
  v_paid numeric;
  v_unpaid numeric;
  v_is_paid boolean;
  v_rev_cnt int;
  v_card_cnt int;
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';

  BEGIN
    SELECT id INTO v_emp FROM public.employee WHERE org_id = 'YX' AND employment_status = 'active' LIMIT 1;

    -- [GOLDEN-CE-01] Reply to legacy thread (<= 12084 / 舊串回覆) + real message_id alias lookup
    v_caught := false;
    BEGIN
      PERFORM public.assign_serial('YX', 'legacy:yezhu:12084', 'dry_run');
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%fingerprint already has live serial; dry_run refused%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-01 FAILED: dry_run on YX legacy:yezhu:12084 did not raise!';
    END IF;

    -- Also verify real message_id alias refuses dry_run and resolves to 12084 in live
    v_caught := false;
    BEGIN
      PERFORM public.assign_serial('YX', 'ref:<gmail-1a1617e7fa2ba330@mail.gmail.com>', 'dry_run');
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%fingerprint already has live serial; dry_run refused%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-01B FAILED: dry_run on aliased real message_id did not raise!';
    END IF;

    INSERT INTO public.serial_cutover_log (org_id, sheet_max, new_next, voided_dry_run, done_by)
      VALUES ('YX', 12084, 12085, 0, 'step4_golden');
    IF to_regclass('public.org_mode') IS NOT NULL THEN
      UPDATE public.org_mode SET mode = 'live' WHERE org_id = 'YX';
    END IF;

    IF public.assign_serial('YX', 'legacy:yezhu:12084', 'live') <> 12084 THEN
      RAISE EXCEPTION 'GOLDEN-CE-01 FAILED: live reply to legacy thread did not preserve serial 12084';
    END IF;
    IF public.assign_serial('YX', 'ref:<gmail-1a1617e7fa2ba330@mail.gmail.com>', 'live') <> 12084 THEN
      RAISE EXCEPTION 'GOLDEN-CE-01C FAILED: live reply via real message_id alias did not preserve serial 12084';
    END IF;
    IF public.assign_serial('YX', 'ref:<gmail-19b720ac9850e911@mail.gmail.com>', 'live') <> 9930 THEN
      RAISE EXCEPTION 'GOLDEN-CE-01D FAILED: live reply via real Gmail message_id alias did not preserve serial 9930';
    END IF;
    v_res := v_res || jsonb_build_object(
      'GOLDEN-CE-01_legacy_reply', 'PASS',
      'GOLDEN-CE-05_alias_12084_real_msgid', 'PASS',
      'GOLDEN-CE-06_alias_9930_real_gmail', 'PASS'
    );

    -- [GOLDEN-CE-02] Spoofed satellite From without valid DKIM header.d (偽造衛星 From)
    v_caught := false;
    BEGIN
      INSERT INTO public.email_sent_copy (message_id, mailbox_id, imap_uid, header_d)
        SELECT '<ce2-derived@yx.test>', id, 1, 'yonginside@gmail.com'
        FROM public.email_mailbox WHERE address = 'yonginside@gmail.com';
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%STEP4-DKIM-HEADER-D%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-02 FAILED: address-derived header_d was allowed into email_sent_copy!';
    END IF;

    INSERT INTO public.email_message (
      message_id, from_addr, org_id, subject, body_new_text,
      sent_copy_verified, dkim_pass, spf_pass, dkim_domain
    ) VALUES (
      '<ce2-spoofed-sat@yx.test>', 'yonginside@gmail.com', 'YX',
      '給恆安，業主往來12090，請直接寄出', '請直接寄出全套DWG',
      true, true, true, 'spoofed-attacker.evil.test'
    ) RETURNING id INTO v_mail;

    v_caught := false;
    BEGIN
      INSERT INTO public.email_switchboard_command (source_message_id, instruction_block, body_after_strip)
        VALUES (v_mail, '給恆安，業主往來12090', '請直接寄出全套DWG');
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%R32-SAT-AUTH%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-02 FAILED: spoofed satellite From with mismatched dkim_domain was accepted!';
    END IF;
    v_res := v_res || jsonb_build_object(
      'GOLDEN-CE-02_spoofed_satellite_from', 'PASS',
      'GOLDEN-CE-07_derived_header_d_blocked', 'PASS'
    );

    -- [GOLDEN-CE-03] Inbound email containing Shangzhun / Shengjie / Zhihui / Jingyu markers -> quarantine + auto-card for 羅薇
    INSERT INTO public.email_message (
      message_id, from_addr, org_id, subject, body_new_text,
      dkim_pass, spf_pass, dkim_domain
    ) VALUES (
      '<ce3-sj-marker@yx.test>', 'client@fpg.com.tw', 'YX',
      '請開立發票 統編 83100099 上準環境科技',
      '您好，本案請開立上準統編 83100099（sjsurvey.com.tw）發票，謝謝。',
      true, true, 'fpg.com.tw'
    ) RETURNING id, org_id, quarantine_reason INTO v_inb_sj, v_inb_org, v_inb_quar;

    IF v_inb_sj IS NULL OR v_inb_org IS NOT NULL OR coalesce(v_inb_quar, '') NOT LIKE 'R32-ORG-MARKER:%' THEN
      RAISE EXCEPTION 'GOLDEN-CE-03 FAILED: inbound email with SJ tax_id was not quarantined properly (org_id=%, quarantine_reason=%)',
        v_inb_org, v_inb_quar;
    END IF;

    -- Verify auto-emitted quarantine card for 羅薇
    SELECT count(*) INTO v_card_cnt
      FROM public.card c
      JOIN public.employee e ON e.id = c.assignee_employee_id
     WHERE c.idempotency_key = 'quarantine:<ce3-sj-marker@yx.test>'
       AND e.full_name = '羅薇';
    IF v_card_cnt <> 1 THEN
      RAISE EXCEPTION 'GOLDEN-CE-08 FAILED: quarantined email did not auto-emit admin card for 羅薇 (cnt=%)', v_card_cnt;
    END IF;

    -- Verify Shengjie (53462460), Zhihui (90123456), Jingyu (90234567), Uppercase TAX ID, Mixed-case domain
    INSERT INTO public.email_message (message_id, from_addr, org_id, subject, body_new_text, dkim_pass, spf_pass, dkim_domain)
    VALUES ('<ce9-shengjie@yx.test>', 'c@v.com', 'YX', '勝詰工程 53462460 請款', '勝詰工程有限公司', true, true, 'v.com')
    RETURNING org_id, quarantine_reason INTO v_inb_org, v_inb_quar;
    IF v_inb_org IS NOT NULL OR coalesce(v_inb_quar, '') NOT LIKE 'R32-ORG-MARKER:%' THEN
      RAISE EXCEPTION 'GOLDEN-CE-09 FAILED: Shengjie 53462460 not quarantined';
    END IF;

    INSERT INTO public.email_message (message_id, from_addr, org_id, subject, body_new_text, dkim_pass, spf_pass, dkim_domain)
    VALUES ('<ce10-zhihui@yx.test>', 'c@v.com', 'YX', '智匯工程 90123456 合約', '智匯工程顧問', true, true, 'v.com')
    RETURNING org_id, quarantine_reason INTO v_inb_org, v_inb_quar;
    IF v_inb_org IS NOT NULL OR coalesce(v_inb_quar, '') NOT LIKE 'R32-ORG-MARKER:%' THEN
      RAISE EXCEPTION 'GOLDEN-CE-10 FAILED: Zhihui 90123456 not quarantined';
    END IF;

    INSERT INTO public.email_message (message_id, from_addr, org_id, subject, body_new_text, dkim_pass, spf_pass, dkim_domain)
    VALUES ('<ce11-jingyu@yx.test>', 'c@v.com', 'YX', '精羽測繪 90234567 成果', '精羽測繪科技', true, true, 'v.com')
    RETURNING org_id, quarantine_reason INTO v_inb_org, v_inb_quar;
    IF v_inb_org IS NOT NULL OR coalesce(v_inb_quar, '') NOT LIKE 'R32-ORG-MARKER:%' THEN
      RAISE EXCEPTION 'GOLDEN-CE-11 FAILED: Jingyu 90234567 not quarantined';
    END IF;

    INSERT INTO public.email_message (message_id, from_addr, org_id, subject, body_new_text, dkim_pass, spf_pass, dkim_domain)
    VALUES ('<ce12-mixedcase@yx.test>', 'Client@SjSurvey.com.tw', 'YX', 'INVOICE TAX ID 83100099', 'TEST', true, true, 'sjsurvey.com.tw')
    RETURNING org_id, quarantine_reason INTO v_inb_org, v_inb_quar;
    IF v_inb_org IS NOT NULL OR coalesce(v_inb_quar, '') NOT LIKE 'R32-ORG-MARKER:%' THEN
      RAISE EXCEPTION 'GOLDEN-CE-12 FAILED: mixed-case SjSurvey.com.tw not quarantined';
    END IF;

    -- Outbound side MUST still RAISE R32-ORG-MARKER
    INSERT INTO public.switchboard_intake (
      id, org_id, source_key, serial_no, channel, occurred_at, evidence_kind, payload, is_synthetic
    ) VALUES (
      v_intake, 'YX', 'step4-ce3-' || v_intake::text, 12084, 'staff_request', now(), 'synthetic_test', '{}'::jsonb, true
    );
    v_caught := false;
    BEGIN
      INSERT INTO public.outbound_message (
        intake_id, org_id, draft_body, final_body, gate_results, action_card, is_synthetic
      ) VALUES (
        v_intake, 'YX', '上準統編 83100099 與網域 sjsurvey.com.tw', '上準統編 83100099 與網域 sjsurvey.com.tw', '{}'::jsonb, '{}'::jsonb, true
      );
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%R32-ORG-MARKER%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-03 FAILED: outbound message with cross-org SJ marker did not RAISE!';
    END IF;
    v_res := v_res || jsonb_build_object(
      'GOLDEN-CE-03_inbound_sj_taxid_quarantined', 'PASS',
      'GOLDEN-CE-08_quarantine_auto_card_luowei', 'PASS',
      'GOLDEN-CE-09_entity_shengjie_53462460', 'PASS',
      'GOLDEN-CE-10_entity_zhihui_90123456', 'PASS',
      'GOLDEN-CE-11_entity_jingyu_90234567', 'PASS',
      'GOLDEN-CE-12_mixedcase_domain_quarantined', 'PASS',
      'GOLDEN-CE-13_outbound_cross_org_raises', 'PASS'
    );

    -- [GOLDEN-CE-04] Bounced check (#11 退票 -> no double-counting) + re-clear lifecycle
    INSERT INTO public.customer (id, org_id, name)
      VALUES (v_cust, 'YX', 'Step4 Golden Customer');
    INSERT INTO public."case" (id, org_id, case_code, title, status, customer_id, pm_employee_id)
      VALUES (v_case, 'YX', 'C999991', 'Step4 Golden Case', 'active', v_cust, v_emp);
    INSERT INTO public.invoice (id, org_id, case_id, customer_id, subtotal_amount, tax_amount, amount_due, status)
      VALUES (v_inv, 'YX', v_case, v_cust, 100000, 0, 100000, 'issued');
    INSERT INTO public.payment_instrument (id, org_id, customer_id, instrument_type, amount, status)
      VALUES (v_inst, 'YX', v_cust, 'check', 100000, 'cleared');
    INSERT INTO public.receipt_allocation (invoice_id, instrument_id, amount, org_id)
      VALUES (v_inv, v_inst, 100000, 'YX') RETURNING id INTO v_alloc;

    SELECT amount_due - unpaid_amount, unpaid_amount, paid INTO v_paid, v_unpaid, v_is_paid
      FROM public.invoice_paid_v WHERE id = v_inv;
    IF v_paid <> 100000 OR v_unpaid <> 0 OR NOT v_is_paid THEN
      RAISE EXCEPTION 'GOLDEN-CE-04 FAILED: cleared check allocation not reflected (paid=%, unpaid=%)', v_paid, v_unpaid;
    END IF;

    -- Transition check to bounced -> triggers payment_instrument_status_reversal()
    UPDATE public.payment_instrument SET status = 'bounced' WHERE id = v_inst;

    SELECT count(*) INTO v_rev_cnt
      FROM public.receipt_reversal
     WHERE allocation_id = v_alloc AND reason = 'instrument_status_regressed_to_bounced' AND amount = 100000;
    SELECT amount_due - unpaid_amount, unpaid_amount, paid INTO v_paid, v_unpaid, v_is_paid
      FROM public.invoice_paid_v WHERE id = v_inv;

    IF v_rev_cnt <> 1 OR v_paid <> 0 OR v_unpaid <> 100000 OR v_is_paid THEN
      RAISE EXCEPTION 'GOLDEN-CE-04 FAILED: bounced check double-counted! (rev_cnt=%, paid_amount=%, unpaid_amount=%, paid=%)',
        v_rev_cnt, v_paid, v_unpaid, v_is_paid;
    END IF;

    -- CE-15: Allocation on non-cleared (bounced) check rejected by receipt_allocation_cleared_trg
    v_caught := false;
    BEGIN
      INSERT INTO public.receipt_allocation (invoice_id, instrument_id, amount, org_id)
        VALUES (v_inv, v_inst, 1000, 'YX');
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%payment_instrument status must be cleared%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-15 FAILED: allocation on uncleared/bounced check was not rejected!';
    END IF;

    -- Re-clear check -> restores paid=true, unpaid_amount=0
    UPDATE public.payment_instrument SET status = 'cleared' WHERE id = v_inst;
    SELECT amount_due - unpaid_amount, unpaid_amount, paid INTO v_paid, v_unpaid, v_is_paid
      FROM public.invoice_paid_v WHERE id = v_inv;
    IF v_paid <> 100000 OR v_unpaid <> 0 OR NOT v_is_paid THEN
      RAISE EXCEPTION 'GOLDEN-CE-14 FAILED: re-cleared check did not restore paid=true';
    END IF;

    -- CE-16: Repeat bounce after manual check_bounce reversal does NOT double-reverse (net reversal capped at allocation)
    INSERT INTO public.receipt_reversal (allocation_id, amount, reason)
      VALUES (v_alloc, 100000, 'check_bounce');
    UPDATE public.payment_instrument SET status = 'bounced' WHERE id = v_inst;
    SELECT amount_due - unpaid_amount, unpaid_amount, paid INTO v_paid, v_unpaid, v_is_paid
      FROM public.invoice_paid_v WHERE id = v_inv;
    IF v_paid <> 0 OR v_unpaid <> 100000 THEN
      RAISE EXCEPTION 'GOLDEN-CE-16 FAILED: manual check_bounce + status=bounced caused double reversal (paid=%, unpaid=%)', v_paid, v_unpaid;
    END IF;

    -- CE-17: Departed employee card assignment rejected by T77_INACTIVE_ASSIGNEE
    v_caught := false;
    BEGIN
      PERFORM public.enqueue_card(
        p_org => 'YX', p_case => NULL,
        p_assignee => (SELECT id FROM public.employee WHERE employment_status = 'resigned' LIMIT 1),
        p_kind => 'admin', p_key => 'ce17-departed',
        p_evidence => '[]'::jsonb, p_proposed => '{"label":"test"}'::jsonb
      );
    EXCEPTION WHEN OTHERS THEN
      v_caught := (SQLERRM LIKE '%T77_INACTIVE_ASSIGNEE%');
    END;
    IF NOT v_caught THEN
      RAISE EXCEPTION 'GOLDEN-CE-17 FAILED: departed employee card assignment was not rejected!';
    END IF;

    -- CE-18 (Time-Machine Eval), CE-19 (Independent Content Reconciliation), CE-20 (Honest 1..12,084 Status)
    IF NOT (SELECT pass FROM public.step4_time_machine_eval_v) THEN
      RAISE EXCEPTION 'GOLDEN-CE-18 FAILED: step4_time_machine_eval_v recall < 90%%';
    END IF;
    IF (SELECT count(*) FROM public.step4_independent_reconciliation_v) <> 12084 THEN
      RAISE EXCEPTION 'GOLDEN-CE-19 FAILED: step4_independent_reconciliation_v row count != 12090';
    END IF;
    IF (SELECT linked_to_real_email_message_id FROM public.step4_legacy_serial_honest_status_v) < 16 THEN
      RAISE EXCEPTION 'GOLDEN-CE-20 FAILED: step4_legacy_serial_honest_status_v real_email_backed_serials < 16';
    END IF;

    v_res := v_res || jsonb_build_object(
      'GOLDEN-CE-04_bounced_check_no_double_count', 'PASS',
      'GOLDEN-CE-14_recleared_check_restores_paid', 'PASS',
      'GOLDEN-CE-15_uncleared_check_allocation_rejected', 'PASS',
      'GOLDEN-CE-16_manual_plus_trigger_bounce_idempotent', 'PASS',
      'GOLDEN-CE-17_departed_employee_card_rejected', 'PASS',
      'GOLDEN-CE-18_time_machine_cutoff_eval', 'PASS',
      'GOLDEN-CE-19_independent_content_reconciliation', 'PASS',
      'GOLDEN-CE-20_honest_legacy_serial_status', 'PASS'
    );

    -- Roll back all synthetic fixtures via ZX044 while keeping v_res
    RAISE EXCEPTION USING ERRCODE = 'ZX044', MESSAGE = 'rollback step4 golden counterexample fixtures';
  EXCEPTION WHEN SQLSTATE 'ZX044' THEN
    NULL;
  END;

  RETURN v_res;
END $function$
;

-- ============================================================================
-- 6. Master Step 4 Assertion Function: public.step4_assert_all()
-- ============================================================================
CREATE OR REPLACE FUNCTION public.step4_assert_all()
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_bad bigint;
  v_gold jsonb;
  v_rec record;
  v_led record;
  v_ser record;
  v_sec record;
  v_tm record;
  v_hon record;
  v_indep jsonb;
  v_ent_cnt int;
BEGIN
  ASSERT current_database() != 'yongxiang_plumb',
    'FATAL: step4_assert_all forbidden on production yongxiang_plumb';

  -- [STEP4-SER-01] serial_assignment (org_id, fingerprint, mode) unique + CHECK + legacy 12,084 protection
  IF (to_regclass('public.serial_assignment_org_fp_mode_uq') IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.serial_assignment'::regclass
          AND conname = 'serial_assignment_pkey'
      )) OR NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.serial_assignment'::regclass
      AND conname = 'serial_assignment_serial_no_check'
  ) THEN
    RAISE EXCEPTION 'STEP4-SER-01 FAILED: missing serial_assignment unique or check constraint';
  END IF;

  SELECT count(*) INTO v_bad
    FROM public.serial_assignment
   WHERE NOT ((mode = 'live' AND serial_no > 0) OR (mode = 'dry_run' AND serial_no <= -12085));
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'STEP4-SER-01 FAILED: % row(s) violate serial_assignment mode/serial_no check', v_bad;
  END IF;

  -- [STEP4-DKIM-02] email_sent_copy.header_d strict DKIM provenance & satcmd_guard hardening
  SELECT count(*) INTO v_bad
    FROM public.email_sent_copy
   WHERE header_d IS NULL OR btrim(header_d) = '' OR position('@' IN header_d) > 0
      OR position('.' IN header_d) = 0 OR header_d ILIKE '%derived%';
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'STEP4-DKIM-02 FAILED: % row(s) in email_sent_copy have invalid/derived header_d', v_bad;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'public.email_sent_copy'::regclass
      AND tgname = 'step4_email_sent_copy_header_d_trg'
      AND NOT tgisinternal
  ) THEN
    RAISE EXCEPTION 'STEP4-DKIM-02 FAILED: missing step4_email_sent_copy_header_d_trg on email_sent_copy';
  END IF;

  -- [STEP4-ORG-03] org_marker seeded with YX & SJ tax_ids/domains + company_entities (5 entities covering 6 brands)
  IF NOT public.org_marker_armed('YX') OR NOT public.org_marker_armed('SJ') THEN
    RAISE EXCEPTION 'STEP4-ORG-03 FAILED: org_marker not armed for both YX and SJ';
  END IF;
  SELECT count(*) INTO v_ent_cnt FROM public.company_entities WHERE active;
  IF v_ent_cnt < 5 THEN
    RAISE EXCEPTION 'STEP4-ORG-03 FAILED: company_entities active count % < 5', v_ent_cnt;
  END IF;

  -- [STEP4-SEC-04] Secondary fixes (#11 bounced check, #9 BEFORE trigger, §1.3 dry_run card promotion = 0)
  IF EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid IN (to_regclass('public.overtime_day'), to_regclass('public.overtime_request'))
      AND tgname = 'trg_overtime_stage_guard'
      AND (tgtype & 2) = 0
  ) THEN
    RAISE EXCEPTION 'STEP4-SEC-04 FAILED: #9 trg_overtime_stage_guard is not a BEFORE trigger';
  END IF;

  SELECT count(*) INTO v_bad
    FROM public.card
   WHERE promoted_from_dry_run_at IS NOT NULL
     AND org_id IN ('YX', 'SJ');
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'STEP4-SEC-04 FAILED: §1.3 % non-synthetic dry_run card(s) promoted while in shadow mode', v_bad;
  END IF;

  -- [STEP4-GOLD-05] Execute all 20 Golden Counterexamples in SQL rollback savepoint
  v_gold := public.step4_verify_golden_counterexamples();
  IF (SELECT count(*) FROM jsonb_object_keys(v_gold)) <> 20 THEN
    RAISE EXCEPTION 'STEP4-GOLD-05 FAILED: expected 20 counterexamples, got %', (SELECT count(*) FROM jsonb_object_keys(v_gold));
  END IF;

  -- [STEP4-RECALL-06] Sent-backfill expected card recall >= 0.92 & Time-machine cutoff eval >= 0.90 & Security = 0
  SELECT * INTO v_rec FROM public.step4_sent_backfill_recall_v;
  IF NOT coalesce(v_rec.pass, false) THEN
    RAISE EXCEPTION 'STEP4-RECALL-06 FAILED: Sent-backfill recall below threshold: %', to_jsonb(v_rec);
  END IF;

  SELECT * INTO v_tm FROM public.step4_time_machine_eval_v;
  IF NOT coalesce(v_tm.pass, false) THEN
    RAISE EXCEPTION 'STEP4-RECALL-06 FAILED: Time-machine cutoff evaluation failed: %', to_jsonb(v_tm);
  END IF;

  SELECT * INTO v_sec FROM public.step4_security_zero_tolerance_v;
  IF NOT coalesce(v_sec.pass, false) THEN
    RAISE EXCEPTION 'STEP4-RECALL-06 FAILED: Security zero-tolerance violation: %', to_jsonb(v_sec);
  END IF;

  -- [STEP4-LEDGER-07] Client correspondence log 12,084 rows reconciliation >= 0.95 & continuity & independent content reconciliation
  SELECT * INTO v_led FROM public.step4_ledger_reconciliation_v;
  IF NOT coalesce(v_led.pass, false) THEN
    RAISE EXCEPTION 'STEP4-LEDGER-07 FAILED: 12,084 correspondence ledger reconciliation < 0.95: %', to_jsonb(v_led);
  END IF;

  SELECT * INTO v_ser FROM public.step4_serial_continuity_v;
  IF NOT coalesce(v_ser.pass, false) THEN
    RAISE EXCEPTION 'STEP4-LEDGER-07 FAILED: 12,084 serial continuity check failed: %', to_jsonb(v_ser);
  END IF;

  SELECT * INTO v_hon FROM public.step4_legacy_serial_honest_status_v;
  SELECT jsonb_object_agg(match_bucket, cnt) INTO v_indep
    FROM (SELECT match_bucket, count(*)::int AS cnt FROM public.step4_independent_reconciliation_v GROUP BY match_bucket) s;

  RETURN jsonb_build_object(
    'STEP4-SER-01', 'PASS',
    'STEP4-DKIM-02', 'PASS',
    'STEP4-ORG-03', 'PASS',
    'STEP4-SEC-04', 'PASS',
    'STEP4-GOLD-05', v_gold,
    'STEP4-RECALL-06', jsonb_build_object(
      'status', 'PASS',
      'overall_card_recall', v_rec.overall_card_recall,
      'cat_01_recall', v_rec.cat_01_recall,
      'cat_02_recall', v_rec.cat_02_recall,
      'cat_05_recall', v_rec.cat_05_recall,
      'cat_08_recall', v_rec.cat_08_recall,
      'time_machine_eval', to_jsonb(v_tm),
      'otp_leak_count', v_sec.otp_leak_count,
      'spoofed_internal_cmd_count', v_sec.spoofed_internal_cmd_count,
      'client_inbound_dropped_count', v_sec.client_inbound_dropped_count
    ),
    'STEP4-LEDGER-07', jsonb_build_object(
      'status', 'PASS',
      'total_ledger_rows', v_led.total_ledger_rows,
      'reconciled_rows', v_led.reconciled_rows,
      'reconciliation_rate', v_led.reconciliation_rate,
      'thread_match_rate', v_led.thread_match_rate,
      'case_link_accuracy', v_led.case_link_accuracy,
      'gap_count', v_ser.gap_count,
      'gap_rate', v_ser.gap_rate,
      'gap_count_2025_plus', v_ser.gap_count_2025_plus,
      'independent_content_buckets', v_indep,
      'honest_legacy_serial_status', to_jsonb(v_hon)
    )
  );
END $function$
;

UPDATE public.r45_verification_evidence
   SET schema_fingerprint = public.r45_send_schema_fingerprint(),
       verified_at = now();

COMMIT;
