"""
CTFTime 数据源模块
负责从 CTFTime.org API 拉取赛事数据
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

# 安全导入 aiohttp，如果缺失则标记
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from .base import EventModel

logger = logging.getLogger(__name__)


class CTFTimeSource:
    """
    CTFTime 数据源：从 CTFTime.org 官方 API 拉取国际赛事数据
    
    特性:
      - 使用官方 API，数据质量有保证
      - 支持按权重过滤（需要更高质量的赛事）
      - 代码中假定可能因为网络墙问题导致超时
    """

    API_URL = "https://ctftime.org/api/v1/events/"
    REQUEST_TIMEOUT = 10  # 秒

    def __init__(self, config: dict[str, Any]):
        """
        初始化数据源
        
        Args:
            config: 包含 "ctftime" 配置段的字典
        """
        self.config = config
        self._enabled = config.get("ctftime", {}).get("enabled", True)

    async def fetch_events(
        self, 
        days_ahead: int | None = None, 
        limit: int | None = None
    ) -> list[EventModel]:
        """
        异步抓取 CTFTime 赛事
        
        Args:
            days_ahead: 查询多少天的赛事（默认从配置读取）
            limit: 最多返回多少条结果（默认从配置读取）
        
        Returns:
            清洗后的 EventModel 列表；若出错则返回空列表
        """
        
        # 如果数据源被禁用
        if not self._enabled:
            logger.debug("[CTF Pusher] CTFTime 数据源已禁用")
            return []
        
        # 如果 aiohttp 未安装，优雅降级
        if not HAS_AIOHTTP:
            logger.error("[CTF Pusher] aiohttp 未安装，无法使用 CTFTime 数据源")
            return []
        
        # 读取配置
        cfg = self.config.get("ctftime", {})
        days_ahead = days_ahead or int(cfg.get("days_ahead", 14))
        limit = limit or int(cfg.get("limit", 50))
        min_weight = float(cfg.get("min_weight", 20.0))
        request_timeout = float(cfg.get("request_timeout", self.REQUEST_TIMEOUT))
        user_agent = cfg.get("user_agent", "AstrBot/CTFPlugin")
        
        # 构建请求参数
        now = datetime.now(timezone.utc)
        params = {
            "limit": limit,
            "start": int(now.timestamp()),
            "finish": int((now + timedelta(days=days_ahead)).timestamp()),
        }
        
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
        }
        
        try:
            # 使用 aiohttp 发起异步请求
            timeout = aiohttp.ClientTimeout(total=request_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.API_URL, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"[CTF Pusher] CTFTime API 请求失败: HTTP {resp.status}"
                        )
                        return []
                    
                    payload = await resp.json()
        
        except asyncio.TimeoutError:
            logger.warning(
                f"[CTF Pusher] CTFTime 请求超时 (>{request_timeout}s)，"
                f"可能受网络墙影响"
            )
            return []
        
        except Exception as e:
            logger.error(f"[CTF Pusher] CTFTime 网络异常: {type(e).__name__}: {e}")
            return []
        
        # 清洗和过滤数据
        out: list[EventModel] = []
        
        try:
            for item in payload:
                event = self._normalize_event_data(item)
                
                # 过滤掉需要邀请码的赛事
                if event.is_invite_only:
                    continue
                
                # 过滤掉权重过低的赛事（确保质量）
                if event.weight < min_weight:
                    continue
                
                out.append(event)
        
        except Exception as e:
            logger.error(f"[CTF Pusher] CTFTime 数据清洗失败: {e}")
        
        # 按权重降序排列
        out.sort(key=lambda x: x.weight, reverse=True)
        
        logger.info(f"[CTF Pusher] CTFTime 返回 {len(out)} 场赛事")
        return out

    @staticmethod
    def _normalize_event_data(raw_data: dict[str, Any]) -> EventModel:
        """
        将原始的 CTFTime API 响应数据标准化为 EventModel
        
        Args:
            raw_data: CTFTime API 返回的原始赛事对象
        
        Returns:
            标准化的 EventModel 对象
        """
        # 检查是否需要邀请码（基于字段内容）
        txt = " ".join(
            [
                str(raw_data.get("description", "")),
                str(raw_data.get("format", "")),
                str(raw_data.get("title", "")),
            ]
        ).lower()
        is_invite_only = any(
            keyword in txt 
            for keyword in ["invite", "invitation", "邀请码", "仅限受邀"]
        )
        
        # 提取和标准化标签
        tags = raw_data.get("tags", []) or []
        tags_normalized = [
            str(t).strip().lower() 
            for t in tags 
            if str(t).strip()
        ]
        
        return EventModel(
            id=str(raw_data.get("id", "")),
            title=str(raw_data.get("title", "未知赛事")),
            source="ctftime",
            start_time=str(raw_data.get("start", "")),
            end_time=str(raw_data.get("finish", "")),
            url=str(raw_data.get("ctftime_url") or raw_data.get("url") or ""),
            tags=tags_normalized,
            weight=float(raw_data.get("weight", 0.0) or 0.0),
            is_invite_only=is_invite_only,
            description=str(raw_data.get("description", "")),
            format_str=str(raw_data.get("format", "")),
        )


# 在导入时进行验证和提示
if not HAS_AIOHTTP:
    logger.warning("[CTF Pusher] aiohttp 未安装，CTFTime 数据源会被禁用")
