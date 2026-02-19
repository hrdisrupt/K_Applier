"""
K_AutoApply Worker - Azure Service Bus Consumer

Entry point for the queue consumer process.
Listens for application messages on Azure Service Bus and processes them.

Usage:
    python -m app.worker
"""
import asyncio
import sys
import os

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.queue_consumer import QueueConsumer


def main():
    print("[WORKER] K_AutoApply Worker starting...", flush=True)
    print("[WORKER] Mode: Azure Service Bus Consumer", flush=True)
    
    consumer = QueueConsumer()
    asyncio.run(consumer.start())


if __name__ == "__main__":
    main()
