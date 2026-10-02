from scripts.browser_step import public_output


def test_other_user_tabs_and_script_source_are_not_printed():
    raw='### Result\n{"ok":true}\n### Ran Playwright code\nprivate script\n### Open tabs\nhttps://unrelated/auth/callback?code=secret\n'
    assert public_output(raw)=='### Result\n{"ok":true}\n'


def test_callback_query_credentials_redacted_but_errors_remain():
    raw='### Error\nNavigation https://example/callback?code=secret&state=opaque&ok=1 failed\n'
    assert public_output(raw)=='### Error\nNavigation https://example/callback?code=[REDACTED]&state=[REDACTED]&ok=1 failed\n'
