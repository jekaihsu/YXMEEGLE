"""The v3 report boundary. Monetary cost and salary fields are excluded.
Case detail contract/billing amounts and progress ratios are allowed because 案件 is already registered for sales and progress behind the same gate; monetary cost and salary fields stay excluded.
"""
from dataclasses import dataclass

BASE_TOKEN = 'Sdw1bG1djaHsVGsRPvmjyVWipgg'
CRM_BASE_TOKEN = 'Yda8bPhWFaAuFisOJt9jsy2QpDf'
FLAGS = ('⚠案件不符', '⚠組別權重=0', '⚠工項不符', '⚠負值', '⚠已結案新列')

@dataclass(frozen=True)
class Table:
    name: str
    table_id: str
    kind: str
    fields: tuple[str, ...]
    used_by: tuple[str, ...]
    base_token: str = BASE_TOKEN

TABLES = (
    Table('外業工作單', 'tbl97f1uXqi7Qz0k', 'field', ('工作單號','所屬成本單','所屬案件','案件編號','組別','出工日期','工作日期-薪資','營業額人員-明細','此單出工人','工項','最終營業額點數','檢核狀態','控制組檢核','是否有檢核程序','違反檢核程序 緣由','備註'), ('review','progress')),
    Table('外業成本單', 'tblQCy3eU0wsUj1I', 'field_cost', ('工作日期','組別','第一台車','第二台車','第三台車','出發里程1','結束里程1','出發里程2','結束里程2','出發里程3','結束里程3','使用儀器'), ('review','assets')),
    Table('內業工作單', 'tblTP5Naz52FBpFg', 'office', ('工作單號','所屬成本單','所屬案件','案件編號','工作日期-營業額明細','營業額組別-明細','姓名','內業工項','最終營業額點數','檢核狀態','雅雯檢核','備註') + FLAGS, ('review','progress')),
    Table('內業成本單', 'tbl8JdWLLwlPFuoF', 'office_cost', ('工作日期','內業組別','內業組長檢核','PM檢核'), ('review',)),
    Table('案件', 'tblWsSaOcy4nKuGI', 'case', ('案件編號','案件名稱','業主','PM','狀態','預期營業額點數','預期合約金額','實際合約金額','案件可請款總額','累計外業營業額點數','累計內業營業額點數','營業額進度','成本進度','計價進度','可請款未請','應收未收','累計已請款','累計已入帳'), ('sales','progress')),
    Table('合約明細', 'tblCPwtDjBstnEOQ', 'contract', ('所屬案件','預期營業額點數','已完成營業額點數','還差營業額點數'), ('progress',)),
    Table('工作預排', 'tblN8c3WN44233aG', 'plan', ('條類型','開始日期','結束日期','業別','組別','案件','預估營業額點數','車輛','儀器','人員','預排工作項目','工作內容'), ('progress','assets')),
    Table('車輛', 'tblryKpRlYXJ9Y2E', 'vehicle', ('車牌','啟用','備註','第一台車紀錄','第二台車紀錄','第三台車紀錄'), ('assets',)),
    Table('儀器費率', 'tblfgeEtMuBTg72O', 'instrument', ('儀器名稱','日租金','啟用','狀態','類別','備註','使用此儀器的成本單'), ('assets',)),
    Table('人員名單', 'tblmlpA6nG5Ou7NQ', 'people', ('姓名','所屬組別'), ('review','progress','contacts')),
    Table('外業組別營業額統計', 'tblCys3XcRulzlQ4', 'monthly', ('組別月份','月份日期','組別','營業額點數'), ('progress',)),
    Table('回報問題', 'tblwKTWB3AIM786y', 'issue', ('文字','文字 2','單選','日期'), ('sources',)),
    Table('跟進／拜訪紀錄','tblReHxTlKydHguQ','crm_contact',tuple('活動ID,客戶,客戶(同步),同步業主,活動類型,活動時間,原建立時間,建立時間,執行人,原建立者,建立人,工程編號,報編（尚未成案可填）,同步報價編號,工程名稱,業主窗口,聯繫方式,聯繫主題,活動主旨,內容摘要,結果,下一步,下一跟進日,處理結果,已完成,有效日期,是否本週（有效日期）,彙整週(週一),原記錄ID'.split(',')),('contacts',),CRM_BASE_TOKEN),
    Table('聯絡業主記錄','tblJW1agkDHqZJ9k','v3_contact',tuple('摘要,工程編號,工程名稱,報編（尚未成案可填）,聯繫日期,建立時間,有效日期,聯繫人員,業主窗口,聯繫方式,聯繫主題,聯繫內容/業主回覆,下次追蹤日,待辦事項,處理結果,是否本週,是否本週（有效日期）,彙整週(週一)'.split(',')),('contacts',),BASE_TOKEN),
)
BY_KIND = {t.kind: t for t in TABLES}
