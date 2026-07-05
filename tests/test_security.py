"""注册输入校验 + 密码哈希。"""

from app.security import hash_password, validate_password, validate_username, verify_password


def test_valid_username():
    assert validate_username("alice_01") is None
    assert validate_username("Bob") is None


def test_invalid_usernames():
    assert validate_username("ab") is not None          # 太短
    assert validate_username("a" * 33) is not None      # 太长
    assert validate_username("小明") is not None         # 非法字符
    assert validate_username("a b") is not None
    assert validate_username("") is not None


def test_password_rules():
    assert validate_password("12345678") is None
    assert validate_password("1234567") is not None
    assert validate_password("") is not None


def test_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
