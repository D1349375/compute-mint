from billflow.redact import redact_pii


def test_emails_are_replaced():
    assert redact_pii("write to jane@example.com now") == "write to [email] now"


def test_dashed_phone_numbers_are_replaced():
    assert redact_pii("call 0900-000-000 today") == "call [phone] today"


def test_plain_digit_phone_numbers_are_replaced():
    assert redact_pii("call 0900000000 today") == "call [phone] today"
