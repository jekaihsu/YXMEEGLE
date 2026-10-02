from scripts.formal_worker_log_summary import collect


def test_only_known_component_and_error_class_survive():
 found=[]
 collect({'timestamp':'safe','message':'prefix {"component":"source","error_type":"HTTPException","secret":"HIDDEN"}'},found)
 assert found==[('source','HTTPException')]
 assert 'HIDDEN'not in repr(found)


def test_untrusted_message_and_error_text_not_returned():
 found=[]
 collect([{'component':'user-secret','error_type':'HTTPException'},{'component':'source','error_type':'https://secret.example/token'}],found)
 assert found==[]
