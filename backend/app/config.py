from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sd:sd@localhost:5432/sd"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # Portal sessions are longer-lived than staff ones: a client checks in
    # occasionally and being logged out mid-message is worse than the
    # marginal risk, since the portal exposes only that client's own data.
    portal_token_expire_minutes: int = 720
    # Public base URL of the portal, used to build magic links in emails.
    portal_base_url: str = "http://localhost:8081/portal"
    portal_magic_link_ttl_minutes: int = 30

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


    # Set to "production" on the customer's VM. Nothing behaves differently
    # because of it - it only decides whether the checks below shout.
    environment: str = "development"


settings = Settings()

# Values that are fine on a laptop and dangerous on a server. They're printed
# at startup rather than enforced, because refusing to boot would strand an
# operator mid-deploy with a system that won't come up; a loud, specific
# warning in the logs is what actually gets acted on. See docs/deployment.md.
INSECURE_DEFAULTS = {
    "JWT_SECRET": (settings.jwt_secret, "change-me"),
    "SETTINGS_ENCRYPTION_KEY": (settings.settings_encryption_key, "jP7WgoQPzPJpZgjNEQ7irtTLLEYhHQfpKxKZSQhcvlk="),
    "SEED_ADMIN_PASSWORD": (settings.seed_admin_password, "ChangeMe123!"),
}


def insecure_settings() -> list[str]:
    """Names of settings still holding their published default value."""
    problems = [name for name, (actual, default) in INSECURE_DEFAULTS.items() if actual == default]
    if settings.cors_origins == ["*"]:
        problems.append("CORS_ORIGINS")
    return problems


def warn_about_insecure_settings() -> None:
    problems = insecure_settings()
    if not problems:
        return
    banner = "!" * 72
    detail = ", ".join(problems)
    if settings.environment == "production":
        print(f"\n{banner}\nВНИМАНИЕ: в проде используются небезопасные значения по умолчанию: {detail}", flush=True)
        print("Ключ шифрования опубликован в репозитории — секреты интеграций фактически не защищены.", flush=True)
        print(f"См. docs/deployment.md, раздел «Секреты».\n{banner}\n", flush=True)
    else:
        print(f"[config] dev-значения по умолчанию: {detail} (в проде обязательно заменить)", flush=True)
