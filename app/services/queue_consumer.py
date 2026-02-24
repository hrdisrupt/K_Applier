"""
Azure Service Bus Queue Consumer for K_AutoApply

Listens to an Azure Service Bus queue for application messages.
When a message arrives, it creates/retrieves an Application record
and runs the Playwright auto-apply flow.

Message format (JSON):
{
    "job_url": "https://www.helplavoro.it/offerta-di-lavoro-a-.../1234.html",
    "job_id": 123,              // optional - FK to scraper jobs table
    "job_title": "Developer",   // optional
    "company_name": "Acme",     // optional
    "candidate": {
        "nome": "Mario",
        "cognome": "Rossi",
        "email": "mario@example.com",
        "sesso": "M",
        "data_nascita": "15/06/1990",
        "comune": "Milano",
        "indirizzo": "Via Roma 1",   // optional
        "cap": "20100",
        "telefono": "3331234567",
        "studi": "Laurea Breve (3 anni)",
        "occupazione_attuale": "Non occupato",
        "area_competenza": "IT/Informatica/Internet",
        "presentazione": "...",      // optional
        "cv_reference": "cv_mario.pdf",
        "accetto_privacy": true,
        "accetto_marketing": false,
        "accetto_terze_parti": false,
        "accetto_banca_dati": false
    }
}
"""
import json
import asyncio
import signal
from datetime import datetime
from typing import Optional

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusError
from sqlmodel import Session

from ..core.config import get_settings
from ..core.database import engine, create_db_and_tables
from ..models.application import Application, ApplicationStatus
from ..services.application_service import ApplicationService
from ..services.auto_apply import AutoApplyService


settings = get_settings()


class QueueConsumer:
    """
    Azure Service Bus consumer that processes job applications.
    
    Runs as a long-lived process, receiving messages one at a time
    (Playwright is single-browser, so no parallelism).
    """
    
    def __init__(self):
        self.running = False
        self.servicebus_client: Optional[ServiceBusClient] = None
        self.auto_apply: Optional[AutoApplyService] = None
    
    async def start(self):
        """Start the consumer loop"""
        if not settings.servicebus_connection_string:
            print("[WORKER] ERROR: SERVICEBUS_CONNECTION_STRING not set", flush=True)
            return
        
        if not settings.servicebus_queue_name:
            print("[WORKER] ERROR: SERVICEBUS_QUEUE_NAME not set", flush=True)
            return
        
        # Initialize DB
        create_db_and_tables()
        print("[WORKER] Database initialized", flush=True)
        
        # Connect to Service Bus
        self.servicebus_client = ServiceBusClient.from_connection_string(
            settings.servicebus_connection_string
        )
        print(f"[WORKER] Connected to Azure Service Bus", flush=True)
        print(f"[WORKER] Listening on queue: {settings.servicebus_queue_name}", flush=True)
        
        self.running = True
        
        # Handle graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown)
        
        # Main consumer loop
        while self.running:
            print("[WORKER] Waiting for messages...", flush=True)
            try:
                await self._receive_and_process()
            except ServiceBusError as e:
                print(f"[WORKER] Service Bus error: {e}", flush=True)
                await asyncio.sleep(5)  # Wait before reconnecting
            except Exception as e:
                print(f"[WORKER] Unexpected error: {e}", flush=True)
                await asyncio.sleep(5)
        
        # Cleanup
        await self._cleanup()
        print("[WORKER] Stopped", flush=True)
    
    async def _receive_and_process(self):
        """Receive one message and process it"""
        async with self.servicebus_client.get_queue_receiver(
            queue_name=settings.servicebus_queue_name,
            max_wait_time=30  # Long poll: wait up to 30s for a message
        ) as receiver:
            messages = await receiver.receive_messages(max_message_count=1, max_wait_time=30)
            
            if not messages:
                return  # No message, loop back
            
            msg = messages[0]
            
            try:
                # Parse message
                body = str(msg)
                data = json.loads(body)
                
                print(f"[WORKER] Received message: job_url={data.get('job_url', 'N/A')}", flush=True)
                
                # Process the application
                success = await self._process_application(data)
                
                if success:
                    # Complete (remove from queue)
                    receiver.complete_message(msg)
                    print(f"[WORKER] Message completed", flush=True)
                else:
                    # Abandon (return to queue for retry, up to max delivery count)
                    receiver.abandon_message(msg)
                    print(f"[WORKER] Message abandoned (will retry)", flush=True)
                    
            except json.JSONDecodeError as e:
                print(f"[WORKER] Invalid JSON message: {e}", flush=True)
                # Dead letter bad messages
                receiver.dead_letter_message(msg, reason="InvalidJSON", error_description=str(e))
            except Exception as e:
                print(f"[WORKER] Processing error: {e}", flush=True)
                receiver.abandon_message(msg)
    
    async def _process_application(self, data: dict) -> bool:
        """
        Process a single application from queue message.
        Returns True on success, False on failure.
        """
        with Session(engine) as session:
            service = ApplicationService(session)
            
            try:
                candidate = data.get("candidate", {})
                
                # Create or retrieve application record
                application = self._create_application(service, data, candidate)
                
                if application.status == ApplicationStatus.SUCCESS:
                    print(f"[WORKER] Already applied to {data.get('job_url')}, skipping", flush=True)
                    return True
                
                # Mark as processing
                service.mark_processing(application)
                
                # Start browser and apply
                auto_apply = AutoApplyService()
                await auto_apply.start_browser()
                
                try:
                    result = await auto_apply.apply_to_job(application)
                    service.save(result)
                    
                    if result.status == ApplicationStatus.SUCCESS:
                        service.mark_job_as_applied(result)
                        print(f"[WORKER] ✅ Application successful: {data.get('job_url')}", flush=True)
                        return True
                    else:
                        print(f"[WORKER] ❌ Application failed: {result.error_message}", flush=True)
                        return False
                        
                finally:
                    await auto_apply.stop_browser()
                    
            except ValueError as e:
                # Duplicate application - treat as success (already exists)
                print(f"[WORKER] Application already exists: {e}", flush=True)
                return True
            except Exception as e:
                print(f"[WORKER] Error processing application: {e}", flush=True)
                # Try to update status in DB
                try:
                    if 'application' in locals() and application:
                        service.update_status(
                            application,
                            ApplicationStatus.FAILED,
                            error_message=str(e)
                        )
                except:
                    pass
                return False
    
    def _create_application(
        self, service: ApplicationService, data: dict, candidate: dict
    ) -> Application:
        """Create application record from queue message data"""
        
        # Check if already exists
        existing = service.get_by_job_and_email(
            data.get("job_url", ""),
            candidate.get("email", "")
        )
        if existing:
            return existing
        
        return service.create_application(
            job_url=data.get("job_url", ""),
            job_title=data.get("job_title"),
            company_name=data.get("company_name"),
            candidate_nome=candidate.get("nome", ""),
            candidate_cognome=candidate.get("cognome", ""),
            candidate_email=candidate.get("email", ""),
            candidate_sesso=candidate.get("sesso", "M"),
            candidate_data_nascita=candidate.get("data_nascita", ""),
            candidate_comune=candidate.get("comune", ""),
            candidate_indirizzo=candidate.get("indirizzo"),
            candidate_cap=candidate.get("cap", ""),
            candidate_telefono=candidate.get("telefono", ""),
            candidate_studi=candidate.get("studi", ""),
            candidate_occupazione=candidate.get("occupazione_attuale", ""),
            candidate_area_competenza=candidate.get("area_competenza", ""),
            candidate_presentazione=candidate.get("presentazione"),
            cv_reference=candidate.get("cv_reference", ""),
            accetto_privacy=candidate.get("accetto_privacy", True),
            accetto_marketing=candidate.get("accetto_marketing", False),
            accetto_terze_parti=candidate.get("accetto_terze_parti", False),
            accetto_banca_dati=candidate.get("accetto_banca_dati", False),
        )
    
    def _shutdown(self):
        """Signal handler for graceful shutdown"""
        print("[WORKER] Shutdown signal received...", flush=True)
        self.running = False
    
    async def _cleanup(self):
        """Cleanup resources"""
        if self.servicebus_client:
            self.servicebus_client.close()
            print("[WORKER] Service Bus connection closed", flush=True)
