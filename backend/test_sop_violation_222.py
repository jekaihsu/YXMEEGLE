"""#222：外業工作單 SOP 單選口徑與欄名解析（「是」=違反；「否」/空白不算）。"""
from backend.reports.compute import is_sop_violation, sop_select_value
from backend.reports.registry import TABLES

FLAG = '違反檢核程序'
FIELD_TABLE = next(t for t in TABLES if t.table_id == 'tbl97f1uXqi7Qz0k')


def test_yes_counts_as_violation_old_and_new_names():
    assert is_sop_violation({'是否有檢核程序': '是'})
    assert is_sop_violation({'違反SOP': '是'})
    assert is_sop_violation({'違反SOP': ['是']})
    # 新名優先
    assert is_sop_violation({'違反SOP': '是', '是否有檢核程序': '否'})


def test_no_and_empty_are_not_violation():
    assert not is_sop_violation({'是否有檢核程序': '否'})
    assert not is_sop_violation({'違反SOP': '否'})
    assert not is_sop_violation({'違反SOP': ['否']})
    assert not is_sop_violation({'是否有檢核程序': None})
    assert not is_sop_violation({'違反SOP': None})
    assert not is_sop_violation({'違反SOP': ''})
    assert not is_sop_violation({})
    # 新名優先：新名為否時，即使舊名是「是」也不算違反
    assert not is_sop_violation({'違反SOP': '否', '是否有檢核程序': '是'})


def test_reason_field_is_not_mistaken_for_select():
    # 緣由即使含「是」也不能當成違反單選
    assert not is_sop_violation({'違反SOP緣由': '是，測試用假資料', '違反檢核程序 緣由': '是'})
    assert not is_sop_violation({'違反SOP緣由': '測試用假資料，非正式紀錄', '是否有檢核程序': '否'})
    assert sop_select_value({'違反SOP緣由': '是', '違反SOP': '否'}) == '否'
    assert sop_select_value({'違反SOP緣由': '是', '是否有檢核程序': '是'}) == '是'


def test_registry_lists_old_and_new_field_names():
    names = FIELD_TABLE.fields
    assert '是否有檢核程序' in names
    assert '違反SOP' in names
    assert '違反檢核程序 緣由' in names
    assert '違反SOP緣由' in names
