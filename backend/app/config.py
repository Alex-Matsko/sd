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

    attachments_dir: str = "/data/attachments"

    cors_origins: list[str] = ["*"]

    seed_admin_email: str = "admin@o-horizons.com"
    seed_admin_password: str = "ChangeMe123!"


settings = Settings()
