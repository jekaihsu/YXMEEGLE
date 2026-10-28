-- R54 (Fable points 1 & 2): remove R46 "acceptance view switching" / acting_as.
-- Clone only. Identity is always the authenticated Lark principal; no impersonation.
DO $guard$ BEGIN
  ASSERT current_database() = 'yongxiang_plumb_r39_clone';
  ASSERT current_database() <> 'yongxiang_plumb';
END $guard$;

-- 1. The effective principal is ALWAYS the authenticated principal. There is no
--    longer any "acting_as" indirection: a session can only ever be its own
--    employee. This removes R46's impersonation path at the data layer.
CREATE OR REPLACE FUNCTION public.r46_effective_employee_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT public.r46_authenticated_employee_id();
$$;

-- 2. Drop the impersonation routine entirely (it mutated acting_as_employee_id).
DROP FUNCTION IF EXISTS public.r46_impersonate(text, uuid);

-- 3. r47 labeling actor resolver must no longer reference acting_as.
CREATE OR REPLACE FUNCTION r47.actor()
 RETURNS uuid
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'r47'
AS $function$
DECLARE me uuid; h text:=current_setting('app.r47_session_sha256',true);
BEGIN
  IF h IS NULL OR h !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION '需要有效的 Lark 登入' USING ERRCODE='28000';
  END IF;
  SELECT e.id INTO me FROM public.api_session s JOIN public.employee e ON e.id=s.employee_id
   WHERE s.token_sha256=h AND s.expires_at>clock_timestamp()
     AND s.org_id=e.org_id AND e.org_id='YX' AND e.employment_status='active'
     AND e.identity_confirmed AND s.lark_open_id=e.lark_open_id;
  IF me IS NULL THEN RAISE EXCEPTION '登入已失效' USING ERRCODE='28000'; END IF;
  RETURN me;
END $function$;

-- 4. Clean baseline: remove the stale (all-expired) sandbox sessions so every
--    api_session row from now on is minted by the real Lark OAuth callback.
--    card_action_log(session_id, actor_employee_id) FKs api_session(id,
--    employee_id); the table is empty so this is unblocked.
DELETE FROM public.api_session;

-- 5. Physically remove the acting_as_employee_id column. After this,
--    card_action_log.actor_employee_id can only equal api_session.employee_id.
ALTER TABLE public.api_session DROP COLUMN IF EXISTS acting_as_employee_id;

-- 6. Re-prove the authorization invariants still hold.
SELECT public.r46_assert_all();
