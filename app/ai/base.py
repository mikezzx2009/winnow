"""AI 分析层的抽象接口 —— 可替换适配器。

业务代码只依赖 Analyzer 协议和 Analysis 数据结构；换模型/换厂商（订阅 Key → 按量付费、
MiniMax → 其它）只需实现一个新的 Analyzer 并在配置里切换，业务逻辑不动。
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Analysis:
    """一封邮件的重要性判断结果。"""

    is_important: bool
    confidence: float          # 0~1
    reason: str                # 简短中文理由
    category: str              # 工作/账单/社交/营销/垃圾/...
    prefiltered: bool = False  # True=由规则预筛得出，未调用模型


class Analyzer(Protocol):
    """重要性分析器协议。"""

    def analyze(self, *, subject: str, from_addr: str, body: str) -> Analysis:
        ...
