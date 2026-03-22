"""
CTFTime 查询服务层：提供检索、按 ID 查询和标签过滤能力。
"""

import logging
from typing import Any, Optional

from .ctftime import CTFTimeSource

logger = logging.getLogger(__name__)


class EventQueryService:
    """
    赛事查询服务：对 CTFTimeSource 的业务封装。
    """

    def __init__(self, ctftime_source: CTFTimeSource):
        """
        初始化聚合器
        
        Args:
            ctftime_source: CTFTime 数据源实例
        """
        self.ctftime_source = ctftime_source

    async def fetch_events(
        self, 
        days_ahead: int = 14,
        tag_filter: str = ""
    ) -> list[dict[str, Any]]:
        """
        从 CTFTime 拉取赛事并按标签过滤。
        
        Args:
            days_ahead: 查询多少天的赛事
            tag_filter: 可选的标签过滤条件
        
        Returns:
            赛事列表（字典格式）
        """
        events = await self.ctftime_source.fetch_events(days_ahead=days_ahead)
        out = [e.to_dict() for e in events]

        if tag_filter:
            out = await self.filter_by_tags(out, [tag_filter])
        
        # 按开始时间排序
        out.sort(key=lambda x: x.get("start_time", ""))
        
        logger.info(f"[CTF Pusher] 查询命中 {len(out)} 场赛事")
        return out

    async def fetch_all_sources(
        self,
        days_ahead: int = 14,
        tag_filter: str = ""
    ) -> list[dict[str, Any]]:
        """兼容旧调用，等价于 fetch_events。"""
        return await self.fetch_events(days_ahead=days_ahead, tag_filter=tag_filter)

    async def fetch_ctftime_only(
        self, 
        days_ahead: int = 14
    ) -> list[dict[str, Any]]:
        """
        仅从 CTFTime 拉取赛事
        
        Args:
            days_ahead: 查询多少天的赛事
        
        Returns:
            赛事列表（字典格式）
        """
        events = await self.ctftime_source.fetch_events(days_ahead=days_ahead)
        return [e.to_dict() for e in events]

    async def find_event_by_id(
        self, 
        event_id: str, 
        days_ahead: int = 45
    ) -> Optional[dict[str, Any]]:
        """
        根据赛事 ID 查找赛事
        
        Args:
            event_id: 要查找的赛事 ID
            days_ahead: 查询范围（天数）
        
        Returns:
            找到的赛事字典；未找到则返回 None
        """
        all_events = await self.fetch_events(days_ahead=days_ahead)
        
        for event in all_events:
            if str(event.get("id")) == str(event_id):
                return event
        
        return None

    async def filter_by_tags(
        self,
        events: list[dict[str, Any]],
        tags: list[str],
        match_any: bool = True
    ) -> list[dict[str, Any]]:
        """
        基于标签过滤赛事列表
        
        Args:
            events: 赛事列表
            tags: 要匹配的标签列表
            match_any: True 表示匹配任意一个标签（OR），False 表示匹配所有标签（AND）
        
        Returns:
            过滤后的赛事列表
        """
        if not tags:
            return events
        
        # 标准化标签（小写）
        filter_tags = [str(t).strip().lower() for t in tags]
        
        filtered = []
        for event in events:
            event_tags = [str(t).lower() for t in event.get("tags", [])]
            title = str(event.get("title", "")).lower()
            
            if match_any:
                # OR 逻辑：标题或标签中包含任一过滤标签
                match = any(
                    ft in title or any(ft in et for et in event_tags)
                    for ft in filter_tags
                )
            else:
                # AND 逻辑：标题或标签中包含全部过滤标签
                match = all(
                    ft in title or any(ft in et for et in event_tags)
                    for ft in filter_tags
                )
            
            if match:
                filtered.append(event)
        
        return filtered
