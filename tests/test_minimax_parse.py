"""MiniMax 输出解析：模型可能返回代码围栏 / 夹带多余文字 / 缺字段，需健壮处理。"""

import pytest

from app.ai.minimax import _to_analysis, extract_json


def test_plain_json():
    data = extract_json('{"is_important": true, "confidence": 0.8, "reason": "工作", "category": "工作"}')
    assert data["is_important"] is True


def test_fenced_json():
    text = '```json\n{"is_important": false, "confidence": 0.95, "reason": "广告", "category": "营销"}\n```'
    data = extract_json(text)
    assert data["is_important"] is False
    assert data["category"] == "营销"


def test_json_with_surrounding_text():
    text = '好的，判断结果如下：{"is_important": true, "confidence": 0.7, "reason": "账单", "category": "账单"} 以上。'
    data = extract_json(text)
    assert data["category"] == "账单"


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError):
        extract_json("这里没有任何 JSON")


def test_to_analysis_missing_fields_biases_important():
    # 缺 is_important 时倾向「重要」（漏判代价更大）
    analysis = _to_analysis({})
    assert analysis.is_important is True
    assert analysis.category == "其它"


def test_to_analysis_clamps_confidence():
    assert _to_analysis({"confidence": 5}).confidence == 1.0
    assert _to_analysis({"confidence": -1}).confidence == 0.0
    assert _to_analysis({"confidence": "bad"}).confidence == 0.0
