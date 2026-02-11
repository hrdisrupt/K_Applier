"""
Application Service - Database operations per candidature
"""
from datetime import datetime, timedelta
from typing import Optional, List
from sqlmodel import Session, select, func
from sqlalchemy import desc

from ..models.application import Application, ApplicationRun, ApplicationStatus


def _get_now_sql(session) -> str:
    """Return SQL function for current datetime based on DB dialect"""
    dialect = session.bind.dialect.name
    if dialect == "mssql":
        return "GETDATE()"
    else:
        return "datetime('now')"


class ApplicationService:
    """Service per gestione candidature nel database"""
    
    def __init__(self, session: Session):
        self.session = session
    
    # =========================================================================
    # APPLICATION CRUD
    # =========================================================================
    
    def create_application(
        self,
        job_url: str,
        candidate_nome: str,
        candidate_cognome: str,
        candidate_email: str,
        candidate_sesso: str,
        candidate_data_nascita: str,
        candidate_comune: str,
        candidate_cap: str,
        candidate_telefono: str,
        candidate_studi: str,
        candidate_occupazione: str,
        candidate_area_competenza: str,
        cv_reference: str,
        candidate_indirizzo: Optional[str] = None,
        candidate_presentazione: Optional[str] = None,
        accetto_privacy: bool = True,
        accetto_marketing: bool = False,
        accetto_terze_parti: bool = False,
        accetto_banca_dati: bool = False,
        job_title: Optional[str] = None,
        company_name: Optional[str] = None
    ) -> Application:
        """Crea una nuova candidatura in coda"""
        
        # Verifica se già esiste una candidatura per stesso job+email
        existing = self.get_by_job_and_email(job_url, candidate_email)
        if existing:
            raise ValueError(f"Application already exists for {job_url} with email {candidate_email}")
        
        application = Application(
            job_url=job_url,
            job_title=job_title,
            company_name=company_name,
            candidate_nome=candidate_nome,
            candidate_cognome=candidate_cognome,
            candidate_email=candidate_email,
            candidate_sesso=candidate_sesso,
            candidate_data_nascita=candidate_data_nascita,
            candidate_comune=candidate_comune,
            candidate_indirizzo=candidate_indirizzo,
            candidate_cap=candidate_cap,
            candidate_telefono=candidate_telefono,
            candidate_studi=candidate_studi,
            candidate_occupazione=candidate_occupazione,
            candidate_area_competenza=candidate_area_competenza,
            candidate_presentazione=candidate_presentazione,
            cv_reference=cv_reference,
            accetto_privacy=accetto_privacy,
            accetto_marketing=accetto_marketing,
            accetto_terze_parti=accetto_terze_parti,
            accetto_banca_dati=accetto_banca_dati,
            status=ApplicationStatus.PENDING
        )
        
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        
        return application
    
    def get_by_id(self, application_id: int) -> Optional[Application]:
        """Recupera candidatura per ID"""
        return self.session.get(Application, application_id)
    
    def get_by_job_and_email(self, job_url: str, email: str) -> Optional[Application]:
        """Recupera candidatura per job URL ed email"""
        query = select(Application).where(
            Application.job_url == job_url,
            Application.candidate_email == email
        )
        return self.session.exec(query).first()
    
    def get_pending(self, limit: int = 50) -> List[Application]:
        """Recupera candidature in attesa"""
        query = select(Application).where(
            Application.status == ApplicationStatus.PENDING,
            Application.attempts < Application.max_attempts
        ).order_by(Application.created_at).limit(limit)
        
        return list(self.session.exec(query).all())
    
    def get_failed_retryable(self, limit: int = 20) -> List[Application]:
        """Recupera candidature fallite che possono essere ritentate"""
        query = select(Application).where(
            Application.status == ApplicationStatus.FAILED,
            Application.attempts < Application.max_attempts
        ).order_by(Application.created_at).limit(limit)
        
        return list(self.session.exec(query).all())
    
    def get_all(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[ApplicationStatus] = None,
        email: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> tuple[List[Application], int]:
        """Recupera candidature con filtri e paginazione"""
        
        query = select(Application)
        
        if status:
            query = query.where(Application.status == status)
        
        if email:
            query = query.where(Application.candidate_email == email)
        
        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = self.session.exec(count_query).one()
        
        # Sort
        sort_column = getattr(Application, sort_by, Application.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)
        
        # Paginate
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        return list(self.session.exec(query).all()), total
    
    def update_status(
        self,
        application: Application,
        status: ApplicationStatus,
        error_message: Optional[str] = None,
        screenshot_path: Optional[str] = None
    ) -> Application:
        """Aggiorna lo stato di una candidatura"""
        application.status = status
        application.error_message = error_message
        application.screenshot_path = screenshot_path
        application.completed_at = datetime.now()
        
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        
        return application
    
    def mark_processing(self, application: Application) -> Application:
        """Marca candidatura come in elaborazione"""
        application.status = ApplicationStatus.PROCESSING
        application.started_at = datetime.now()
        application.attempts += 1
        
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        
        return application
    
    def save(self, application: Application) -> Application:
        """Salva candidatura"""
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return application
    
    def mark_job_as_applied(self, application: Application) -> None:
        """
        Update the jobs table (from K_Scraper) to mark the job as applied.
        Only works when sharing the same database as the scraper.
        Fails silently if jobs table doesn't exist.
        """
        try:
            from sqlalchemy import text
            
            now_sql = _get_now_sql(self.session)
            
            # Try to update by job_id FK first
            if application.job_id:
                self.session.execute(
                    text(f"UPDATE jobs SET applied = 1, applied_at = {now_sql} WHERE id = :job_id"),
                    {"job_id": application.job_id}
                )
                self.session.commit()
                print(f"[AUTOAPPLY] Updated jobs.applied for job_id={application.job_id}", flush=True)
                return
            
            # Fallback: try to find job by URL match
            if application.job_url:
                base_url = application.job_url.split("?")[0]
                self.session.execute(
                    text(f"UPDATE jobs SET applied = 1, applied_at = {now_sql} WHERE url LIKE :url_pattern"),
                    {"url_pattern": f"%{base_url}%"}
                )
                self.session.commit()
                print(f"[AUTOAPPLY] Updated jobs.applied by URL match: {base_url}", flush=True)
        except Exception as e:
            # Silently fail - jobs table may not exist (e.g. using separate SQLite DB)
            print(f"[AUTOAPPLY] Could not update jobs table (non-critical): {e}", flush=True)
    
    # =========================================================================
    # APPLICATION RUNS
    # =========================================================================
    
    def create_run(self) -> ApplicationRun:
        """Crea un nuovo run di candidature"""
        run = ApplicationRun()
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run
    
    def finish_run(
        self,
        run: ApplicationRun,
        successful: int,
        failed: int,
        skipped: int,
        status: str = "completed"
    ) -> ApplicationRun:
        """Completa un run"""
        run.finished_at = datetime.now()
        run.total_processed = successful + failed + skipped
        run.successful = successful
        run.failed = failed
        run.skipped = skipped
        run.status = status
        
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        
        return run
    
    def get_runs(self, limit: int = 20) -> List[ApplicationRun]:
        """Recupera ultimi run"""
        query = select(ApplicationRun).order_by(desc(ApplicationRun.started_at)).limit(limit)
        return list(self.session.exec(query).all())
    
    # =========================================================================
    # STATS
    # =========================================================================
    
    def get_stats(self) -> dict:
        """Statistiche generali"""
        total = self.session.exec(select(func.count(Application.id))).one()
        
        pending = self.session.exec(
            select(func.count(Application.id)).where(Application.status == ApplicationStatus.PENDING)
        ).one()
        
        processing = self.session.exec(
            select(func.count(Application.id)).where(Application.status == ApplicationStatus.PROCESSING)
        ).one()
        
        successful = self.session.exec(
            select(func.count(Application.id)).where(Application.status == ApplicationStatus.SUCCESS)
        ).one()
        
        failed = self.session.exec(
            select(func.count(Application.id)).where(Application.status == ApplicationStatus.FAILED)
        ).one()
        
        skipped = self.session.exec(
            select(func.count(Application.id)).where(Application.status == ApplicationStatus.SKIPPED)
        ).one()
        
        # Oggi
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_successful = self.session.exec(
            select(func.count(Application.id)).where(
                Application.status == ApplicationStatus.SUCCESS,
                Application.completed_at >= today
            )
        ).one()
        
        # Ultimi 7 giorni
        week_ago = datetime.now() - timedelta(days=7)
        week_successful = self.session.exec(
            select(func.count(Application.id)).where(
                Application.status == ApplicationStatus.SUCCESS,
                Application.completed_at >= week_ago
            )
        ).one()
        
        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "today_successful": today_successful,
            "week_successful": week_successful
        }
