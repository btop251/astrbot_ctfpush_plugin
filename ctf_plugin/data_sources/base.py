"""
数据模型层：定义统一的 CTFEvent 数据结构。
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EventModel:
    """
    统一的 CTF 赛事数据模型
    
    用于将赛事数据标准化到同一结构
    所有字段均为可选（但通常会有值），缺失时使用默认值
    """
    
    # 必需字段
    id: str
    title: str
    source: str  # 当前插件固定为 "ctftime"
    start_time: str  # ISO8601 格式的时间字符串
    url: str
    
    # 可选字段
    end_time: str = ""  # ISO8601 格式的结束时间
    tags: list[str] = field(default_factory=list)  # 赛事标签
    weight: float = 0.0  # 权重指标（仅 CTFTime 有）
    is_invite_only: bool = False  # 是否需要邀请码
    restrictions: str = ""  # 限制条件描述文本
    
    # 其他扩展字段
    description: str = ""  # 赛事简介
    format_str: str = ""  # 竞赛格式 (如 "Jeopardy", "Attack-Defense")
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    def __hash__(self):
        """使 EventModel 可以用于 set 和 dict key """
        return hash((self.source, self.id))
    
    def __eq__(self, other):
        """比较两个 EventModel 是否相同"""
        if not isinstance(other, EventModel):
            return False
        return self.source == other.source and self.id == other.id
