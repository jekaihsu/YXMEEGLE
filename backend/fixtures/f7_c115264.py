"""Synthetic native-link shape; acceptance still requires deployed live replay."""
BASE='H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
CONF='tblmSQrcCs9vPQZx'
CONTRACT='tblobs4qPy2w9MZ6'
ITEM='tblwQPYk3c9RvCU7'


def fixture():
    def row(table,kind,rid,fields):
        return dict(base_token=BASE,table_id=table,kind=kind,record_id=rid,fields=fields)
    def link(table,rid):return [{'table_id':table,'record_ids':[rid]}]
    records=[row(CONF,'confirmation','recvsnzx3bjtAA',{'工程確認單編號':'C115264'})]
    contracts=('recvsctWu1CN83','recvsctWu1D17w','recvsctWu1ErKg','recvsctWu1cYnK')
    categories=(('報告',),('外業','控制','圖資'),('報告','外業','控制','圖資'),('報告','報告','外業','控制'))
    for cid,num,cats in zip(contracts,(3,1,1,2),categories):
        records.append(row(CONTRACT,'contract',cid,{'所屬成案確認單（日報關聯）':link(CONF,records[0]['record_id']),
            '工編號碼':f'C115264-{num}','合約項次':str(num),'分項金額(報出)':12345}))
        for i,category in enumerate(cats):
            records.append(row(ITEM,'reporting',f'recItem{num}{cid[-4:]}{i}',
                {'來源合約明細（日報關聯）':link(CONTRACT,cid),'工項類別':category,'對應營業額':999}))
    tables=[dict(base_token=BASE,table_id=table,status='ready',field_schema=fields) for table,fields in (
        (CONF,[]),
        (CONTRACT,[dict(field_id='fldDSpokn5',field_name='所屬成案確認單（日報關聯）',property={'table_id':CONF})]),
        (ITEM,[dict(field_id='flduW5c5uF',field_name='來源合約明細（日報關聯）',property={'table_id':CONTRACT}),
               dict(field_id='fldzDDIQkr',field_name='工項類別')]))]
    return records,tables
