"""事件层纯函数测试：健康判断 + 连接异常分类。"""

from app.events import classify_connection_error, is_healthy


def test_healthy_when_fresh_and_no_errors():
    assert is_healthy(30, 0) is True


def test_unhealthy_when_stale():
    assert is_healthy(9999, 0) is False


def test_unhealthy_with_unresolved_errors():
    assert is_healthy(10, 2) is False


def test_unhealthy_without_heartbeat():
    assert is_healthy(None, 0) is False


def test_classify_auth_errors():
    assert classify_connection_error("LOGIN failed: invalid credentials") == "auth"
    assert classify_connection_error("Unsafe Login. Please contact kefu") == "auth"


def test_classify_connection_errors():
    assert classify_connection_error("Connection reset by peer") == "connection"
    assert classify_connection_error("timed out") == "connection"
