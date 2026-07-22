from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sd:sd@localhost:5432/sd"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    default_tariff_code: str = "default"
    default_ticket_attachment_limit_mb: int = 25

    sla_warning_threshold: float = 0.75
    worker_interval_seconds: int = 60

    # Encrypts integration_settings.secrets_encrypted (IMAP/SMTP passwords, future
    # bot tokens/API keys) - urlsafe-base64 32-byte Fernet key. This default is a
    # fixed, publicly-known value for local dev only: generate your own with
    # `python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`
    # and set it in .env before storing any real credentials - rotating it after
    # secrets exist makes them undecryptable.
    settings_encryption_key: str = "jP7WgoQPzPJpZgjNEQ7irtTLLEYhHQfpKxKZSQhcvlk="

    attachments_dir: str = "/data/attachments"

    cors_origins: list[str] = ["*"]

    seed_admin_email: str = "admin@o-horizons.com"
    seed_admin_password: str = "ChangeMe123!"


settings = Settings()
