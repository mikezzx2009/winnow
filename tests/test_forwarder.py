"""转发邮件构造：信封头正确改写、原始正文与附件完整保留。"""

from email.message import EmailMessage

from app.mail.smtp_forwarder import build_forward_message

FROM_126 = "someone@126.com"
TARGET = "target@icloud.com"
PREFIX = "[Winnow] "


def _original_with_attachment() -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "张三 <zhangsan@example.com>"
    msg["To"] = "someone@126.com"
    msg["Subject"] = "原始主题"
    msg["Message-ID"] = "<orig-123@example.com>"
    msg.set_content("这是正文内容")
    msg.add_attachment(
        b"binarydata", maintype="application", subtype="octet-stream", filename="report.bin"
    )
    return msg


def test_envelope_headers_rewritten():
    fwd = build_forward_message(
        _original_with_attachment(), from_addr=FROM_126, to_addr=TARGET, subject_prefix=PREFIX
    )
    assert FROM_126 in fwd["From"]
    assert "via Winnow" in fwd["From"]
    assert fwd["To"] == TARGET
    assert "zhangsan@example.com" in fwd["Reply-To"]        # 回复能回到真人
    assert fwd["Subject"] == "[Winnow] 原始主题"
    assert fwd["X-Original-From"] == "张三 <zhangsan@example.com>"
    assert fwd["X-Winnow-Forwarded"] == "yes"


def test_message_id_is_regenerated():
    fwd = build_forward_message(
        _original_with_attachment(), from_addr=FROM_126, to_addr=TARGET, subject_prefix=PREFIX
    )
    assert fwd["Message-ID"] != "<orig-123@example.com>"
    assert fwd["X-Original-Message-ID"] == "<orig-123@example.com>"
    # 新 Message-ID 域名应为 126 地址域
    assert "126.com" in fwd["Message-ID"]


def test_body_and_attachment_preserved():
    fwd = build_forward_message(
        _original_with_attachment(), from_addr=FROM_126, to_addr=TARGET, subject_prefix=PREFIX
    )
    assert fwd.is_multipart()
    filenames = [p.get_filename() for p in fwd.walk() if p.get_filename()]
    assert "report.bin" in filenames
    bodies = [p.get_content() for p in fwd.walk() if p.get_content_type() == "text/plain"]
    assert any("这是正文内容" in b for b in bodies)
