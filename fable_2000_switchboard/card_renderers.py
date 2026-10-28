"""Both clients consume GET /cards/{id}; all actions use the same POST route."""
def view(card):
    return {'id':str(card['id']),'kind':card['kind'],'proposed_fields':card['proposed_fields'],
            'proposed_fields_label':'待確認','evidence_numbers':card['evidence_numbers'],
            'action_url':f"/cards/{card['id']}/act"}

def lark(card):
    data=view(card)
    return {'renderer':'lark_bot','card':data,'buttons':[{'label':'確認','method':'POST','url':data['action_url'],'body':{'action':'confirm'}}]}

def plumb(card):
    return {'renderer':'plumb_inbox','card':view(card)}
