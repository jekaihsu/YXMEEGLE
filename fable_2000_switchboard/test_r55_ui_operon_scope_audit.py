"""R55 S01 Subagent 5 — :5188 UI/API boundary audit regression tests.

Covers the three interacting requirements for the all-staff people picker and
automatic team-scope filtering:

  1. The people picker can search ALL staff (not team-filtered): it returns the
     full active roster minus the actor themselves, and an engineering actor can
     find a pm_sales colleague by name (cross-team search works).
  2. Automatic team-scope filtering restricts the working case list correctly via
     public.session_list_for(): eng / pm / management viewers get confined,
     different row sets.
  3. A user cannot see another team's cases: a pm_sales viewer's visible case set
     does not leak engineering-only in-scope cases, and an engineering viewer does
     not see pm_sales-only cases.

SAFETY: read-only against the clone yongxiang_plumb_r39_clone only; every DB call
runs inside a transaction that is rolled back. Never connects to prod
yongxiang_plumb. No Email / Lark sends. Does not touch 吳科翰's demo rows.
"""
import psycopg
import pytest

DSN = "dbname=yongxiang_plumb_r39_clone"

# Stable seeded identities (from 009e_r46_lark_team_scope.sql r46_assert_all()).
ENG_EMP = "13394342-2826-5d5d-a26f-44e259279870"   # 張家彬  engineering_indoor
PM_EMP  = "a968fbf8-c0ac-5d6a-9939-80584ede3509"   # 吳柏頤  pm_sales
JK_EMP  = "1101fb67-0080-50c1-98e6-d02f7a0ae907"   # JK     management


@pytest.fixture()
def conn():
    c = psycopg.connect(DSN, autocommit=False)
    # Absolute prod guard.
    cur = c.execute("SELECT current_database()")
    assert cur.fetchone()[0] == "yongxiang_plumb_r39_clone"
    try:
        yield c
    finally:
        c.rollback()      # never persist anything
        c.close()


def _scope_of(conn, emp):
    r = conn.execute(
        "SELECT team_scope FROM public.staff_directory_v WHERE employee_id=%s",
        (emp,),
    ).fetchone()
    return r[0] if r else None


def _picker_names(conn, actor, ctx="handoff", q=None):
    rows = conn.execute(
        "SELECT full_name, team_scope FROM public.people_picker(%s,%s,NULL,%s)",
        (actor, ctx, q),
    ).fetchall()
    return rows


# ---------------------------------------------------------------- picker = ALL staff

def test_active_roster_is_67(conn):
    n = conn.execute(
        "SELECT count(*) FROM public.employee "
        "WHERE org_id='YX' AND employment_status='active'"
    ).fetchone()[0]
    assert n == 67


def test_picker_returns_full_roster_minus_self(conn):
    # Blank query -> whole company, excluding the actor only.
    rows = _picker_names(conn, PM_EMP, "handoff", None)
    names = {r[0] for r in rows}
    assert len(rows) == 66, f"expected 67-1 self, got {len(rows)}"
    # Actor must be excluded.
    actor_name = conn.execute(
        "SELECT full_name FROM public.staff_directory_v WHERE employee_id=%s",
        (PM_EMP,),
    ).fetchone()[0]
    assert actor_name not in names


def test_picker_is_not_team_filtered_cross_team_search(conn):
    # An ENGINEERING actor must be able to find a PM_SALES colleague by name.
    assert _scope_of(conn, ENG_EMP).startswith("engineering")
    pm_colleague = conn.execute(
        "SELECT full_name FROM public.staff_directory_v "
        "WHERE team_scope='pm_sales' AND employee_id<>%s LIMIT 1",
        (ENG_EMP,),
    ).fetchone()[0]
    rows = _picker_names(conn, ENG_EMP, "handoff", pm_colleague)
    found = {r[0] for r in rows}
    assert pm_colleague in found, (
        f"picker is wrongly team-filtered: eng actor cannot find pm colleague {pm_colleague}"
    )
    # And the returned colleague carries a DIFFERENT team_scope than the actor,
    # proving the picker spans teams.
    scopes = {r[1] for r in rows if r[0] == pm_colleague}
    assert scopes == {"pm_sales"}


def test_picker_spans_every_team_scope(conn):
    rows = _picker_names(conn, JK_EMP, "handoff", None)
    scopes = {r[1] for r in rows}
    # All five directory scopes must be reachable from the picker.
    assert {
        "admin_finance", "engineering_indoor", "engineering_outdoor",
        "management", "pm_sales",
    } <= scopes


# ---------------------------------------------------------------- team-scope restricts DATA

def _case_set(conn, viewer):
    rows = conn.execute(
        "SELECT case_id FROM public.session_list_for(%s, false)", (viewer,)
    ).fetchall()
    return {r[0] for r in rows}


def test_management_sees_strict_superset_of_team_viewer(conn):
    pm_cases = _case_set(conn, PM_EMP)
    mgmt_cases = _case_set(conn, JK_EMP)
    # Management (JK) sees everything a pm viewer sees, and strictly more.
    assert pm_cases <= mgmt_cases
    assert len(mgmt_cases) > len(pm_cases)


def test_team_scope_actually_restricts(conn):
    # A scoped viewer must NOT receive the full org case universe.
    pm_cases = _case_set(conn, PM_EMP)
    total = conn.execute(
        "SELECT count(*) FROM public.\"case\" k WHERE EXISTS("
        "SELECT 1 FROM public.card c WHERE c.case_id=k.id "
        "AND c.state IN ('open','escalated','dry_run'))"
    ).fetchone()[0]
    assert 0 < len(pm_cases) < total, (
        f"pm viewer saw {len(pm_cases)} of {total} active cases — scope not restricting"
    )


# ---------------------------------------------------------------- no cross-team leakage

def test_pm_viewer_cannot_see_engineering_only_cases(conn):
    """A pm_sales viewer must not see cases that are in-scope ONLY for engineering
    (field role) and are not that viewer's own assigned cards."""
    pm_cases = _case_set(conn, PM_EMP)

    # Engineering-only in-scope cases: field-role cards whose case has no
    # pm_sales/management-mappable role card.
    eng_only = conn.execute(
        """
        WITH open_cards AS (
          SELECT c.case_id, c.role
            FROM public.card c
           WHERE c.state IN ('open','escalated','dry_run') AND c.case_id IS NOT NULL
        ),
        case_scopes AS (
          SELECT oc.case_id, array_agg(DISTINCT r.team_scope) AS scopes
            FROM open_cards oc
            JOIN public.inbox_role_scope r ON r.inbox_role = oc.role
           GROUP BY oc.case_id
        )
        SELECT case_id FROM case_scopes
         WHERE NOT ('pm_sales' = ANY(scopes) OR 'management' = ANY(scopes))
           AND ('engineering_indoor' = ANY(scopes) OR 'engineering_outdoor' = ANY(scopes))
        """
    ).fetchall()
    eng_only_ids = {r[0] for r in eng_only}

    # The pm viewer's OWN assigned cards are legitimately visible even if eng-scoped;
    # exclude those from the leakage check.
    pm_own = conn.execute(
        "SELECT DISTINCT case_id FROM public.card "
        "WHERE assignee_employee_id=%s AND state IN ('open','escalated','dry_run') "
        "AND case_id IS NOT NULL",
        (PM_EMP,),
    ).fetchall()
    pm_own_ids = {r[0] for r in pm_own}

    leaked = (pm_cases & eng_only_ids) - pm_own_ids
    assert not leaked, f"pm viewer leaked {len(leaked)} engineering-only case(s): {list(leaked)[:5]}"


def test_eng_viewer_cannot_see_pm_only_cases(conn):
    eng_cases = _case_set(conn, ENG_EMP)
    pm_only = conn.execute(
        """
        WITH open_cards AS (
          SELECT c.case_id, c.role FROM public.card c
           WHERE c.state IN ('open','escalated','dry_run') AND c.case_id IS NOT NULL
        ),
        case_scopes AS (
          SELECT oc.case_id, array_agg(DISTINCT r.team_scope) AS scopes
            FROM open_cards oc JOIN public.inbox_role_scope r ON r.inbox_role=oc.role
           GROUP BY oc.case_id
        )
        SELECT case_id FROM case_scopes
         WHERE 'pm_sales' = ANY(scopes)
           AND NOT ('engineering_indoor' = ANY(scopes) OR 'engineering_outdoor' = ANY(scopes)
                    OR 'management' = ANY(scopes))
        """
    ).fetchall()
    pm_only_ids = {r[0] for r in pm_only}
    eng_own = conn.execute(
        "SELECT DISTINCT case_id FROM public.card "
        "WHERE assignee_employee_id=%s AND state IN ('open','escalated','dry_run') "
        "AND case_id IS NOT NULL",
        (ENG_EMP,),
    ).fetchall()
    eng_own_ids = {r[0] for r in eng_own}
    leaked = (eng_cases & pm_only_ids) - eng_own_ids
    assert not leaked, f"eng viewer leaked {len(leaked)} pm-only case(s)"
