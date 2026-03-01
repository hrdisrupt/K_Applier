"""
Pydantic schemas for API request/response
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr

from ..models.application import ApplicationStatus


# ============================================================================
# APPLICATION SCHEMAS
# ============================================================================

class CandidateInfo(BaseModel):
    """Dati del candidato per HelpLavoro"""
    # Anagrafica
    nome: str = Field(..., min_length=2, max_length=100)
    cognome: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    sesso: str = Field(..., pattern="^(M|F)$", description="M = Maschio, F = Femmina")
    data_nascita: str = Field(..., pattern=r"^\d{2}/\d{2}/\d{4}$", description="Formato: gg/mm/aaaa")
    
    # Residenza
    comune: str = Field(..., min_length=2, max_length=100)
    indirizzo: Optional[str] = Field(None, max_length=200)
    cap: str = Field(..., pattern=r"^\d{5}$", description="CAP 5 cifre")
    
    # Contatti
    telefono: str = Field(..., min_length=6, max_length=20)
    
    # Profilo professionale
    studi: str = Field(..., description="Livello studi: es. 'Laurea', 'Diploma', 'Licenza media'")
    occupazione_attuale: str = Field(..., description="es. 'Occupato', 'Disoccupato', 'Studente'")
    area_competenza: str = Field(..., description="es. 'Informatica', 'Commerciale', 'Amministrazione'")
    
    # Presentazione e CV
    presentazione: Optional[str] = Field(None, max_length=2000, description="Lettera di presentazione")
    cv_reference: str = Field(..., description="Path locale o URL del CV")
    
    # Consensi (opzionali - default a non accettare per marketing)
    accetto_privacy: bool = Field(default=True, description="Accettazione privacy obbligatoria")
    accetto_marketing: bool = Field(default=False, description="Comunicazioni da HelpLavoro")
    accetto_terze_parti: bool = Field(default=False, description="Comunicazioni da aziende terze")
    accetto_banca_dati: bool = Field(default=False, description="Deposito CV in banca dati")


class ApplicationCreate(BaseModel):
    """Schema per creare una nuova candidatura"""
    job_url: str = Field(..., min_length=5, max_length=900, description="URL dell'offerta di lavoro")
    job_title: Optional[str] = Field(None, max_length=200)
    job_id: Optional[str] = Field(None, max_length=32, description="fingerprint del lavoro (FK a tabella jobs)")
    company_name: Optional[str] = Field(None, max_length=200)
    candidate: CandidateInfo


class ApplicationResponse(BaseModel):
    """Schema risposta candidatura"""
    id: int
    job_url: str
    job_title: Optional[str]
    company_name: Optional[str]
    job_id: Optional[str]
    
    # Candidate
    candidate_nome: str
    candidate_cognome: str
    candidate_email: str
    candidate_sesso: str
    candidate_data_nascita: str
    candidate_comune: str
    candidate_indirizzo: Optional[str]
    candidate_cap: str
    candidate_telefono: str
    candidate_studi: str
    candidate_occupazione: str
    candidate_area_competenza: str
    candidate_presentazione: Optional[str]
    cv_reference: str
    
    # Status
    status: ApplicationStatus
    error_message: Optional[str]
    screenshot_path: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    attempts: int
    
    class Config:
        from_attributes = True


class ApplicationListResponse(BaseModel):
    """Lista paginata di candidature"""
    applications: List[ApplicationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# BATCH SCHEMAS
# ============================================================================

class BatchApplicationCreate(BaseModel):
    """Schema per creare più candidature in batch"""
    applications: List[ApplicationCreate] = Field(..., min_length=1, max_length=100)


class BatchApplicationResponse(BaseModel):
    """Risposta creazione batch"""
    created: int
    errors: List[dict]


# ============================================================================
# RUN SCHEMAS
# ============================================================================

class ApplicationRunResponse(BaseModel):
    """Schema risposta run"""
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    total_processed: int
    successful: int
    failed: int
    skipped: int
    status: str
    
    class Config:
        from_attributes = True


class ProcessResponse(BaseModel):
    """Risposta processo candidature"""
    run_id: int
    processed: int
    successful: int
    failed: int
    skipped: int
    status: str


# ============================================================================
# STATS SCHEMAS
# ============================================================================

class StatsResponse(BaseModel):
    """Statistiche"""
    total: int
    pending: int
    processing: int
    successful: int
    failed: int
    skipped: int
    today_successful: int
    week_successful: int
