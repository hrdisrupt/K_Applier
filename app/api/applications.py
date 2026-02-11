"""
Application API endpoints
"""
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlmodel import Session

from ..core.database import get_session
from ..core.config import get_settings
from ..models.application import ApplicationStatus
from ..services.application_service import ApplicationService
from ..services.auto_apply import AutoApplyService
from ..schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationListResponse,
    BatchApplicationCreate,
    BatchApplicationResponse,
    ApplicationRunResponse,
    ProcessResponse,
    StatsResponse
)

router = APIRouter(prefix="/applications", tags=["Applications"])
settings = get_settings()

# Track se un processo è in corso
_processing = False


def get_application_service(session: Session = Depends(get_session)) -> ApplicationService:
    return ApplicationService(session)


# ============================================================================
# CREATE APPLICATIONS
# ============================================================================

@router.post("", response_model=ApplicationResponse, status_code=201)
def create_application(
    data: ApplicationCreate,
    service: ApplicationService = Depends(get_application_service)
):
    """
    Crea una nuova candidatura in coda.
    
    La candidatura verrà processata quando si chiama POST /applications/process
    """
    try:
        application = service.create_application(
            job_url=data.job_url,
            job_title=data.job_title,
            company_name=data.company_name,
            candidate_nome=data.candidate.nome,
            candidate_cognome=data.candidate.cognome,
            candidate_email=data.candidate.email,
            candidate_sesso=data.candidate.sesso,
            candidate_data_nascita=data.candidate.data_nascita,
            candidate_comune=data.candidate.comune,
            candidate_indirizzo=data.candidate.indirizzo,
            candidate_cap=data.candidate.cap,
            candidate_telefono=data.candidate.telefono,
            candidate_studi=data.candidate.studi,
            candidate_occupazione=data.candidate.occupazione_attuale,
            candidate_area_competenza=data.candidate.area_competenza,
            candidate_presentazione=data.candidate.presentazione,
            cv_reference=data.candidate.cv_reference,
            accetto_privacy=data.candidate.accetto_privacy,
            accetto_marketing=data.candidate.accetto_marketing,
            accetto_terze_parti=data.candidate.accetto_terze_parti,
            accetto_banca_dati=data.candidate.accetto_banca_dati
        )
        return ApplicationResponse.model_validate(application)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/batch", response_model=BatchApplicationResponse, status_code=201)
def create_batch_applications(
    data: BatchApplicationCreate,
    service: ApplicationService = Depends(get_application_service)
):
    """Crea più candidature in batch"""
    created = 0
    errors = []
    
    for i, app_data in enumerate(data.applications):
        try:
            service.create_application(
                job_url=app_data.job_url,
                job_title=app_data.job_title,
                company_name=app_data.company_name,
                candidate_nome=app_data.candidate.nome,
                candidate_cognome=app_data.candidate.cognome,
                candidate_email=app_data.candidate.email,
                candidate_sesso=app_data.candidate.sesso,
                candidate_data_nascita=app_data.candidate.data_nascita,
                candidate_comune=app_data.candidate.comune,
                candidate_indirizzo=app_data.candidate.indirizzo,
                candidate_cap=app_data.candidate.cap,
                candidate_telefono=app_data.candidate.telefono,
                candidate_studi=app_data.candidate.studi,
                candidate_occupazione=app_data.candidate.occupazione_attuale,
                candidate_area_competenza=app_data.candidate.area_competenza,
                candidate_presentazione=app_data.candidate.presentazione,
                cv_reference=app_data.candidate.cv_reference,
                accetto_privacy=app_data.candidate.accetto_privacy,
                accetto_marketing=app_data.candidate.accetto_marketing,
                accetto_terze_parti=app_data.candidate.accetto_terze_parti,
                accetto_banca_dati=app_data.candidate.accetto_banca_dati
            )
            created += 1
        except Exception as e:
            errors.append({
                "index": i,
                "job_url": app_data.job_url,
                "error": str(e)
            })
    
    return BatchApplicationResponse(created=created, errors=errors)


# ============================================================================
# LIST & GET APPLICATIONS
# ============================================================================

@router.get("", response_model=ApplicationListResponse)
def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[ApplicationStatus] = None,
    email: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    service: ApplicationService = Depends(get_application_service)
):
    """Lista candidature con filtri e paginazione"""
    applications, total = service.get_all(
        page=page,
        page_size=page_size,
        status=status,
        email=email,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    total_pages = (total + page_size - 1) // page_size
    
    return ApplicationListResponse(
        applications=[ApplicationResponse.model_validate(a) for a in applications],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/stats", response_model=StatsResponse)
def get_stats(service: ApplicationService = Depends(get_application_service)):
    """Statistiche candidature"""
    return service.get_stats()


@router.get("/runs", response_model=List[ApplicationRunResponse])
def get_runs(
    limit: int = 20,
    service: ApplicationService = Depends(get_application_service)
):
    """Lista ultimi run di elaborazione"""
    runs = service.get_runs(limit)
    return [ApplicationRunResponse.model_validate(r) for r in runs]


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: int,
    service: ApplicationService = Depends(get_application_service)
):
    """Recupera singola candidatura"""
    application = service.get_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return ApplicationResponse.model_validate(application)


# ============================================================================
# PROCESS APPLICATIONS
# ============================================================================

@router.post("/process", response_model=ProcessResponse)
async def process_applications(
    limit: int = Query(default=10, ge=1, le=50, description="Numero massimo di candidature da processare"),
    service: ApplicationService = Depends(get_application_service)
):
    """
    Processa le candidature in coda.
    
    Avvia il browser Playwright e invia le candidature pending.
    """
    global _processing
    
    if _processing:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    _processing = True
    
    try:
        # Recupera candidature pending
        pending = service.get_pending(limit=limit)
        
        if not pending:
            return ProcessResponse(
                run_id=0,
                processed=0,
                successful=0,
                failed=0,
                skipped=0,
                status="no_pending"
            )
        
        # Crea run
        run = service.create_run()
        
        # Processa
        auto_apply = AutoApplyService()
        await auto_apply.start_browser()
        
        successful = 0
        failed = 0
        skipped = 0
        
        try:
            for application in pending:
                # Processa candidatura
                result = await auto_apply.apply_to_job(application)
                service.save(result)
                
                if result.status == ApplicationStatus.SUCCESS:
                    successful += 1
                    # Update jobs table if using shared DB with scraper
                    service.mark_job_as_applied(result)
                elif result.status == ApplicationStatus.FAILED:
                    failed += 1
                elif result.status == ApplicationStatus.SKIPPED:
                    skipped += 1
                
                # Delay tra candidature
                if settings.delay_between_applications > 0:
                    await asyncio.sleep(settings.delay_between_applications)
        
        finally:
            await auto_apply.stop_browser()
        
        # Completa run
        service.finish_run(run, successful, failed, skipped)
        
        return ProcessResponse(
            run_id=run.id,
            processed=successful + failed + skipped,
            successful=successful,
            failed=failed,
            skipped=skipped,
            status="completed"
        )
    
    finally:
        _processing = False


@router.get("/process/status")
def get_process_status():
    """Verifica se un processo è in corso"""
    return {"processing": _processing}


# ============================================================================
# RETRY FAILED
# ============================================================================

@router.post("/{application_id}/retry", response_model=ApplicationResponse)
async def retry_application(
    application_id: int,
    service: ApplicationService = Depends(get_application_service)
):
    """Ritenta una singola candidatura fallita"""
    global _processing
    
    application = service.get_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    
    if application.status not in [ApplicationStatus.FAILED, ApplicationStatus.SKIPPED]:
        raise HTTPException(status_code=400, detail="Can only retry failed or skipped applications")
    
    if application.attempts >= application.max_attempts:
        raise HTTPException(status_code=400, detail="Max attempts reached")
    
    if _processing:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    _processing = True
    
    try:
        # Reset status
        application.status = ApplicationStatus.PENDING
        service.save(application)
        
        # Processa
        auto_apply = AutoApplyService()
        await auto_apply.start_browser()
        
        try:
            result = await auto_apply.apply_to_job(application)
            service.save(result)
            
            # Update jobs table if using shared DB with scraper
            if result.status == ApplicationStatus.SUCCESS:
                service.mark_job_as_applied(result)
        finally:
            await auto_apply.stop_browser()
        
        return ApplicationResponse.model_validate(result)
    
    finally:
        _processing = False
