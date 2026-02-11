"""
Application configuration

Supports both SQLite (local dev) and Azure SQL Server (production).
Set DATABASE_URL env var to switch:
  - sqlite:///./data/autoapply.db          → SQLite (default)
  - mssql+pyodbc://user:pass@server/db?... → Azure SQL Server
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    # SQLite (local):  sqlite:///./data/autoapply.db
    # Azure SQL:       mssql+pyodbc://user:pass@server.database.windows.net/dbname?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
    database_url: str = "sqlite:///./data/autoapply.db"
    
    # CV Loader
    cv_loader_type: str = "local"  # local, azure_blob, s3
    cv_base_path: str = "./cvs"    # Per local loader
    
    # Azure Blob (per futuro)
    azure_storage_connection_string: str = ""
    azure_container_name: str = "cvs"
    
    # Playwright
    headless: bool = True
    slow_mo: int = 100  # ms tra azioni (anti-detection)
    timeout: int = 30000  # ms
    
    # Dry Run - test senza inviare
    dry_run: bool = False  # True = fa tutto ma NON clicca submit
    
    # Rate limiting
    delay_between_applications: float = 5.0  # secondi tra candidature
    max_applications_per_run: int = 50
    
    # Screenshots
    save_screenshots: bool = True
    screenshots_path: str = "./data/screenshots"
    
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
