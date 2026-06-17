"""
Centralized application configuration.

All environment-driven settings live here so the rest of the codebase
never reads os.environ directly. This makes it trivial to switch between
demo mode (no Tesseract/AI credentials needed) and a real OCR/AI setup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- App ---
    app_name: str = "AI Invoice & Document Processing Automation System"
    env: str = "development"
    demo_mode: bool = True

    # --- Database ---
    database_url: str = "sqlite:///./app.db"

    # --- File storage ---
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10
    allowed_file_types: str = "pdf,png,jpg,jpeg"

    # --- OCR ---
    tesseract_cmd: str = ""

    # --- AI Analysis ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # --- Classification thresholds ---
    classification_auto_threshold: float = 0.80
    classification_review_threshold: float = 0.60

    # --- Validation rules ---
    high_amount_warning_threshold: float = 10000
    valid_currencies: str = "MYR,USD,SGD"

    # --- Export ---
    export_dir: str = "./exports"

    @property
    def allowed_file_types_list(self) -> list[str]:
        return [ext.strip().lower() for ext in self.allowed_file_types.split(",") if ext.strip()]

    @property
    def valid_currencies_list(self) -> list[str]:
        return [c.strip().upper() for c in self.valid_currencies.split(",") if c.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
