"""
配置管理模块
职责: 负责同步加载和异步热更新 config.json
特性:
  - 同步 load()：在 __init__ 中使用，自动创建缺失的 config.json
  - 异步 reload_async()：支持配置热更新
"""

import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# 默认配置字典
# ============================================================================
DEFAULT_CONFIG: dict[str, Any] = {
    "ctftime": {
        "enabled": True,
        "api_url": "https://ctftime.org/api/v1/events/",
        "limit": 50,
        "days_ahead": 14,
        "min_weight": 20.0,
        "request_timeout": 10,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AstrBot/CTFPlugin",
    },
    "subscription": {
        "enabled": True,
        "scan_interval_minutes": 10,
        "remind_windows_minutes": [120, 15],
    },
    "general": {
        "log_level": "INFO",
    },
}


class ConfigManager:
    """配置管理器：负责异步读取/写入 config.json"""

    def __init__(self, plugin_dir: str):
        """
        初始化配置管理器
        
        Args:
            plugin_dir: 插件根目录路径（ctf_plugin 所在目录）
        """
        self.plugin_dir = plugin_dir
        self.config_path = os.path.join(plugin_dir, "config.json")
        self._config: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """
        同步加载配置文件。如果文件不存在，创建包含默认值的模板。
        
        此方法在 __init__ 阶段调用，使用同步 I/O。
        热更新可使用 reload_async() 方法。
        
        Returns:
            合并后的配置字典 (用户配置 + 默认配置)
        """
        # 如果已加载过，直接返回缓存
        if self._config:
            return self._config.copy()

        # 初始化为默认配置的深拷贝
        self._config = self._deep_copy_config(DEFAULT_CONFIG)

        # 尝试读取用户配置文件
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                # 递归合并用户配置到默认配置
                self._config = self._merge_config(self._config, user_config)
                logger.info(f"[CTF Pusher] 配置文件已加载: {self.config_path}")
            except Exception as e:
                logger.error(
                    f"[CTF Pusher] 读取 config.json 失败，将使用默认配置: {e}"
                )
        else:
            # 文件不存在，创建包含默认值的模板
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
                logger.info(
                    f"[CTF Pusher] 未检测到 config.json，已创建默认配置模板: "
                    f"{self.config_path}"
                )
            except Exception as e:
                logger.warning(
                    f"[CTF Pusher] 创建默认配置文件失败，将使用内存配置: {e}"
                )

        return self._config.copy()

    async def reload_async(self) -> dict[str, Any]:
        """
        异步重新加载配置（清空缓存后重新读取）
        用于热更新场景
        
        Returns:
            重新加载后的配置字典
        """
        # 清空缓存
        self._config = {}
        # 同步加载（不需要 async）
        return self.load()

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        获取配置值，支持层级访问
        
        Args:
            *keys: 配置键路径，如 get("ctftime", "enabled")
            default: 默认值
        
        Returns:
            配置值或默认值
        """
        current = self._config
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
        return current if current is not None else default

    async def set(self, value: Any, *keys: str) -> None:
        """设置配置值（仅在内存中，不写入文件）"""
        if not keys:
            return
        
        current = self._config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value

    # ========================================================================
    # 私有方法
    # ========================================================================

    @staticmethod
    def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """递归合并两个配置字典 (override 覆盖 base 的值)"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _deep_copy_config(config: dict[str, Any]) -> dict[str, Any]:
        """深拷贝配置字典"""
        return json.loads(json.dumps(config))
