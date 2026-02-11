"""
SQLModel models for K_AutoApply database

Compatible with both SQLite and Azure SQL Server.
Long text fields use sa_column=Column(Text) to avoid MSSQL's 
default VARCHAR(255) limit.
"""
from datetime import datetime
from typing import Optional
from enum import Enum
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Text


class ApplicationStatus(str, Enum):
    """Application status"""
    PENDING = "pending"          # In coda
    PROCESSING = "processing"    # In esecuzione
    SUCCESS = "success"          # Candidatura inviata
    FAILED = "failed"            # Errore
    SKIPPED = "skipped"          # Saltata (già applicato, form non trovato, ecc.)


class Application(SQLModel, table=True):
    """Application record - una candidatura"""
    __tablename__ = "applications"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Job info
    job_url: str = Field(index=True)
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    job_id: Optional[int] = Field(default=None, index=True)  # FK to jobs table (scraper)
    
    # Candidate - Anagrafica
    candidate_nome: str
    candidate_cognome: str
    candidate_email: str
    candidate_sesso: str  # M o F
    candidate_data_nascita: str  # gg/mm/aaaa
    
    # Candidate - Residenza
    candidate_comune: str
    candidate_indirizzo: Optional[str] = None
    candidate_cap: str
    
    # Candidate - Contatti
    candidate_telefono: str
    
    # Candidate - Profilo
    candidate_studi: str
    candidate_occupazione: str
    candidate_area_competenza: str
    candidate_presentazione: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    
    # CV
    cv_reference: str
    
    # Consensi
    accetto_privacy: bool = True
    accetto_marketing: bool = False
    accetto_terze_parti: bool = False
    accetto_banca_dati: bool = False
    
    # Status tracking
    status: ApplicationStatus = ApplicationStatus.PENDING
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    screenshot_path: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Retry logic
    attempts: int = 0
    max_attempts: int = 3


class ApplicationRun(SQLModel, table=True):
    """Batch run - un'esecuzione del servizio"""
    __tablename__ = "application_runs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Timing
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    
    # Results
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    
    # Status
    status: str = "running"  # running, completed, failed
