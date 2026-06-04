import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE"), env_file_encoding="utf-8"
    )

    app_name: str = "commerce-orchestrator"
    app_env: str = "dev"
    log_level: str = "INFO"
    log_format: str = "auto"  # auto | json | text
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    postgres_db: str = "commerce"
    postgres_user: str = "commerce_user"
    postgres_password: str = "commerce_pass"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_host: str = "localhost"
    redis_port: int = 6379

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"

    payments_provider: str = "mock"  # mock | stripe
    stripe_api_key: str = "replace-with-secret"
    stripe_webhook_base_url: str = "http://127.0.0.1:8000"

    webhook_secret_key: str = "whsec_dev_secret"

    default_idempotency_ttl_seconds: int = 24 * 60 * 60

    @property
    def use_json_logs(self) -> bool:
        fmt = self.log_format.lower()
        if fmt == "json":
            return True
        if fmt == "text":
            return False
        return self.app_env.lower() in ("production", "prod", "staging")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_sync_dsn(self) -> str:
        """Sync DSN for Alembic migrations (psycopg2)."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_dsn(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def rabbitmq_dsn(self) -> str:
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/"
        )

    @property
    def stripe_mock_enabled(self) -> bool:
        return self.payments_provider.lower() == "mock"


settings = Settings()
