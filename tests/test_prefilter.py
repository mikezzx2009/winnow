"""规则预筛：确保「明显营销」被拦下，而拿不准的（尤其重要通知）交给模型。"""

from email.message import EmailMessage

from app.ai.prefilter import run_prefilter


def _make(headers: dict, subject: str) -> EmailMessage:
    msg = EmailMessage()
    for key, value in headers.items():
        msg[key] = value
    msg["Subject"] = subject
    return msg


def test_list_unsubscribe_is_dropped():
    msg = _make({"List-Unsubscribe": "<mailto:unsub@x.com>"}, "本周精选")
    result = run_prefilter(msg, "本周精选")
    assert result is not None
    assert result.is_important is False
    assert result.prefiltered is True


def test_marketing_subject_is_dropped():
    msg = _make({}, "【限时】全场5折促销，点击抢购")
    result = run_prefilter(msg, "【限时】全场5折促销，点击抢购")
    assert result is not None
    assert result.is_important is False


def test_precedence_bulk_is_dropped():
    msg = _make({"Precedence": "bulk"}, "普通通知")
    assert run_prefilter(msg, "普通通知") is not None


def test_normal_mail_escalates_to_model():
    msg = _make({}, "关于明天的会议纪要")
    assert run_prefilter(msg, "关于明天的会议纪要") is None


def test_signin_alert_escalates_to_model():
    # 登录提醒：无退订头、主题非营销 —— 应交给模型，不被预筛误杀
    msg = _make({"From": "noreply@service.example.com"}, "新设备登录提醒")
    assert run_prefilter(msg, "新设备登录提醒") is None
