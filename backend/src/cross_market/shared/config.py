from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    # 启动校验失败时也禁止回显原始环境变量，SecretStr 只保护已解析值。
    model_config = SettingsConfigDict(env_prefix="TR_", extra="ignore", hide_input_in_errors=True)

    api_token: SecretStr = SecretStr("")
    environment: str = "local"
    log_level: str = "INFO"
    version: str = "0.1.0"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = "tick_radar"
    mysql_user: str = "tick_radar"
    mysql_password: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    probe_timeout_seconds: float = Field(default=1, gt=0)
    cors_origins: list[str] = ["http://127.0.0.1:15173"]
    market_observation_enabled: bool = True
    quote_refresh_interval_seconds: int = Field(default=30, ge=10, le=300)
    quote_max_symbols: int = Field(default=50, ge=1, le=50)
    worker_name: str = "main"
    worker_lock_key: str = "lock:worker:main"
    worker_heartbeat_key: str = "health:worker:main"
    worker_heartbeat_interval_seconds: float = Field(default=10, gt=0)
    worker_heartbeat_ttl_seconds: int = Field(default=30, ge=1)
    worker_lock_ttl_seconds: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def validate_worker_timing(self):
        if self.worker_heartbeat_interval_seconds >= min(
            self.worker_heartbeat_ttl_seconds, self.worker_lock_ttl_seconds
        ):
            raise ValueError("心跳间隔必须小于心跳和锁的 TTL")
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mysql+asyncmy",
            username=self.mysql_user,
            password=self.mysql_password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )
