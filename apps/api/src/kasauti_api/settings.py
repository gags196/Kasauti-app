from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KASAUTI_", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://kasauti:kasauti@localhost:5432/kasauti"
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (Cloudflare R2, S3-compatible)
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_scans: str = "kasauti-scans"
    r2_bucket_answers: str = "kasauti-answers"
    r2_bucket_labeled: str = "kasauti-labeled-private"  # gold corpus — never public
    # Learner-facing figures (cropped diagrams), unlike scans/answers/labeled which are
    # ops-only — served on every question page via /api/v1/pyq/figures/{stimulus_id}.
    r2_bucket_question_assets: str = "kasauti-question-assets"

    # LLM / embeddings
    anthropic_api_key: str = ""
    voyage_api_key: str = ""
    embedding_model: str = "voyage-multilingual-2"
    embedding_dim: int = 1024

    # Founder-editable content, mounted into containers
    content_dir: Path = REPO_ROOT / "content"

    # Signs learner session tokens (api/v1/auth.py). The default is 32+ bytes on purpose:
    # a shorter key makes PyJWT emit InsecureKeyLengthWarning on every login, and a log
    # full of a warning nobody can act on is how a real one gets missed. `assert_secure`
    # refuses to let this value reach production.
    auth_secret: str = "dev-only-secret-change-in-production-32b"

    # Browser origins allowed to call /api/v1 (the Next.js learner app).
    # Comma-separated in .env: KASAUTI_CORS_ORIGINS=https://kasauti.in,https://www.kasauti.in
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # /admin (SQLAdmin) login — single founder account for Phase 1
    admin_username: str = "admin"
    admin_password: str = "change-me"


    def assert_secure(self) -> None:
        """Refuse to start outside dev with the shipped defaults.

        The admin password and the token-signing key both have working defaults so a
        fresh clone runs with no configuration. That convenience becomes a hole the
        moment it is deployed, and the failure is silent — everything works, for
        everyone.
        """
        if self.env == "dev":
            return
        defaults = {
            "KASAUTI_AUTH_SECRET": self.auth_secret.startswith("dev-only-secret"),
            "KASAUTI_ADMIN_PASSWORD": self.admin_password == "change-me",
        }
        unset = [name for name, is_default in defaults.items() if is_default]
        if unset:
            raise RuntimeError(
                f"Refusing to start in env={self.env!r} with default secrets: "
                + ", ".join(unset)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_secure()
    return settings
