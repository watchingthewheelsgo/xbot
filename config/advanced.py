"""
高级配置管理
增强的 Pydantic 配置，支持分组、运行时修改和验证
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Literal
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

from loguru import logger

load_dotenv()


class LogLevel(str, Enum):
    """日志级别枚举"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseConfig(BaseSettings):
    """数据库配置"""

    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    url: str = Field(default="sqlite+aiosqlite:///./xbot.db")
    echo: bool = Field(default=False)
    pool_size: int = Field(default=5, ge=1, le=20)
    max_overflow: int = Field(default=10, ge=0, le=50)
    pool_recycle: int = Field(default=3600, ge=300)
    pool_pre_ping: bool = Field(default=True)
    connection_timeout: int = Field(default=30, ge=5)
    max_retries: int = Field(default=3, ge=0, le=10)


class LLMProvider(str, Enum):
    """LLM 提供商枚举"""

    OPENAI = "openai"
    AZURE = "azure"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class LLMConfig(BaseSettings):
    """LLM 配置"""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    api_key: str = Field(default="")
    base_url: Optional[str] = Field(default=None)
    model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, ge=1, le=128000)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    timeout: int = Field(default=60, ge=5, le=300)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay: int = Field(default=1, ge=0, le=60)

    # 代理设置
    proxy: Optional[str] = Field(default=None)
    proxy_cert: Optional[str] = Field(default=None)

    # 模型别名映射
    model_aliases: Dict[str, str] = Field(default_factory=dict)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if v and len(v) < 10:
            logger.warning("API key seems unusually short")
        return v


class ChannelConfig(BaseSettings):
    """消息渠道配置"""

    model_config = SettingsConfigDict(
        env_prefix="CHANNEL_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    enabled_channels: List[str] = Field(default_factory=list)
    default_channel: str = Field(default="telegram")

    # 消息限制
    max_message_length: int = Field(default=4096, ge=100)
    chunk_size: int = Field(default=2000, ge=100)
    chunk_delay: float = Field(default=0.1, ge=0.01, le=10.0)

    # 限流设置
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_messages: int = Field(default=20, ge=1)
    rate_limit_period: int = Field(default=60, ge=1)

    # 静默时段
    quiet_enabled: bool = Field(default=False)
    quiet_start: str = Field(default="22:00")
    quiet_end: str = Field(default="08:00")
    quiet_timezone: str = Field(default="Asia/Shanghai")


class SchedulerConfig(BaseSettings):
    """调度器配置"""

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    enabled: bool = Field(default=True)
    timezone: str = Field(default="UTC")
    workers: int = Field(default=3, ge=1, le=10)
    queue_size: int = Field(default=1000, ge=10)
    max_retries: int = Field(default=3, ge=0, le=10)

    # 数据源抓取间隔（分钟）
    fetch_interval_rss: int = Field(default=15, ge=1)
    fetch_interval_crypto: int = Field(default=5, ge=1)
    fetch_interval_markets: int = Field(default=5, ge=1)
    fetch_interval_economic: int = Field(default=60, ge=10)
    fetch_interval_news: int = Field(default=10, ge=1)

    # 定时任务
    daily_briefing_time: str = Field(default="08:00")
    market_summary_time: str = Field(default="16:30")


class SecurityConfig(BaseSettings):
    """安全配置"""

    model_config = SettingsConfigDict(
        env_prefix="SECURITY_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    # 白名单
    allowlist_enabled: bool = Field(default=True)
    allowlist_path: str = Field(
        default_factory=lambda: str(
            Path.home() / ".config" / "xbot" / "mount_allowlist.json"
        )
    )

    # 验证
    validate_inputs: bool = Field(default=True)
    sanitize_html: bool = Field(default=True)

    # 访问控制
    allowed_admin_ids: List[str] = Field(default_factory=list)
    allowed_chat_ids: List[str] = Field(default_factory=list)
    trusted_domains: List[str] = Field(default_factory=list)


class CacheConfig(BaseSettings):
    """缓存配置"""

    model_config = SettingsConfigDict(
        env_prefix="CACHE_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    enabled: bool = Field(default=True)
    backend: Literal["memory", "redis", "disk"] = Field(default="memory")

    # 内存缓存
    max_items: int = Field(default=1000, ge=10)
    ttl: int = Field(default=300, ge=0)  # 秒

    # Redis 缓存
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_key_prefix: str = Field(default="xbot:")

    # 磁盘缓存
    disk_path: str = Field(default="./cache")
    disk_max_size_mb: int = Field(default=100, ge=1)


class MemoryConfig(BaseSettings):
    """记忆系统配置"""

    model_config = SettingsConfigDict(
        env_prefix="MEMORY_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    enabled: bool = Field(default=True)
    storage_type: Literal["file", "database"] = Field(default="file")
    base_path: str = Field(default="./memory")

    # 保留策略
    max_items: int = Field(default=10000, ge=100)
    max_age_days: int = Field(default=90, ge=1)

    # 搜索配置
    search_fuzzy: bool = Field(default=True)
    search_limit: int = Field(default=20, ge=1, le=100)


class ObservabilityConfig(BaseSettings):
    """可观测性配置"""

    model_config = SettingsConfigDict(
        env_prefix="OBSERVABILITY_",
        env_file=".env",
        env_nested_delimiter="__",
    )

    # 日志
    level: LogLevel = Field(default=LogLevel.INFO)
    format: Literal["json", "text"] = Field(default="text")
    file_path: Optional[str] = Field(default="xbot.log")
    rotation: str = Field(default="10 MB")
    retention: str = Field(default="30 days")

    # 指标
    metrics_enabled: bool = Field(default=False)
    metrics_port: int = Field(default=9090, ge=1024, le=65535)
    metrics_path: str = Field(default="/metrics")

    # 追踪
    tracing_enabled: bool = Field(default=False)
    tracing_endpoint: Optional[str] = Field(default=None)
    tracing_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)


class AdvancedSettings(BaseSettings):
    """
    高级设置集合

    支持分层配置和运行时修改
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="allow",
        case_sensitive=False,
    )

    # 子配置
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig())
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig())
    channel: ChannelConfig = Field(default_factory=lambda: ChannelConfig())
    scheduler: SchedulerConfig = Field(default_factory=lambda: SchedulerConfig())
    security: SecurityConfig = Field(default_factory=lambda: SecurityConfig())
    cache: CacheConfig = Field(default_factory=lambda: CacheConfig())
    memory: MemoryConfig = Field(default_factory=lambda: MemoryConfig())
    observability: ObservabilityConfig = Field(
        default_factory=lambda: ObservabilityConfig()
    )

    # 运行时配置
    debug_mode: bool = Field(default=False, alias="DEBUG")
    dry_run: bool = Field(default=False, alias="DRY_RUN")
    verbose: bool = Field(default=False, alias="VERBOSE")

    # 通用
    timezone: str = Field(default="UTC")
    data_dir: str = Field(default="./data")
    log_dir: str = Field(default="./logs")

    # 运行时状态
    _runtime: Dict[str, Any] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="after")
    def validate_all(self) -> "AdvancedSettings":
        """验证所有配置"""
        if self.debug_mode:
            logger.debug("Debug mode enabled")
            self.observability.level = LogLevel.DEBUG

        if self.dry_run:
            logger.warning("Dry run mode enabled - no actual changes will be made")

        return self

    def get_llm_api_key(self) -> str:
        """获取 LLM API 密钥（优先从 llm 配置读取）"""
        return self.llm.api_key

    def get_database_url(self) -> str:
        """获取数据库 URL"""
        return self.database.url

    def get_timezone(self) -> str:
        """获取时区"""
        return self.timezone

    def get_runtime_value(self, key: str, default: Any = None) -> Any:
        """获取运行时值"""
        return self._runtime.get(key, default)

    def set_runtime_value(self, key: str, value: Any) -> None:
        """设置运行时值"""
        self._runtime[key] = value
        logger.debug(f"Runtime value set: {key} = {value}")

    def reload_from_env(self) -> None:
        """从环境变量重新加载配置"""
        new_settings = AdvancedSettings()
        # 复制所有字段
        for field_name, field_value in new_settings:
            setattr(self, field_name, field_value)
        logger.info("Configuration reloaded from environment")

    def export(self) -> Dict[str, Any]:
        """导出所有配置（排除敏感信息）"""
        sensitive_keys = ["api_key", "secret", "password", "token"]
        export_dict = self.model_dump()

        def _sanitize(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    k: _sanitize(v)
                    if not any(sk in k.lower() for sk in sensitive_keys)
                    else "***"
                    for k, v in obj.items()
                }
            elif isinstance(obj, list):
                return [_sanitize(item) for item in obj]
            return obj

        return _sanitize(export_dict)

    def validate(self) -> List[str]:
        """验证配置，返回警告列表"""
        warnings = []

        # 检查 LLM 配置
        if not self.llm.api_key and self.llm.provider in [
            LLMProvider.OPENAI,
            LLMProvider.AZURE,
        ]:
            warnings.append("LLM API key not set")

        # 检查数据库配置
        if not self.database.url:
            warnings.append("Database URL not set")

        # 检查通道配置
        if not self.channel.enabled_channels:
            warnings.append("No channels enabled")

        # 检查目录
        for dir_path in [self.data_dir, self.log_dir]:
            path = Path(dir_path)
            if path.exists() and not path.is_dir():
                warnings.append(f"Path exists but is not a directory: {dir_path}")

        return warnings


# 全局配置实例
_global_settings: Optional[AdvancedSettings] = None


def get_settings() -> AdvancedSettings:
    """获取或创建全局设置实例"""
    global _global_settings
    if _global_settings is None:
        _global_settings = AdvancedSettings()
    return _global_settings


def init_settings(env_file: Optional[str] = None) -> AdvancedSettings:
    """
    初始化配置

    Args:
        env_file: 环境变量文件路径
    """
    global _global_settings

    if env_file:
        from dotenv import load_dotenv

        load_dotenv(env_file)

    _global_settings = AdvancedSettings()

    # 验证配置
    warnings = _global_settings.validate()
    for warning in warnings:
        logger.warning(f"Configuration warning: {warning}")

    return _global_settings


def reload_settings() -> AdvancedSettings:
    """重新加载配置"""
    return init_settings()
