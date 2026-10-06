from scripts.deploy_verify import verification_passed


def test_deploy_verification_requires_every_check_to_pass():
    assert verification_passed({'checks': {'html': True, 'assets': True}})
    assert not verification_passed({'checks': {'html': True, 'assets': False}})
    assert not verification_passed({'checks': {}})
    assert not verification_passed({'checks': {'assets': 1}})
