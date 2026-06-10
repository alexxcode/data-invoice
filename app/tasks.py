import os
from celery import Celery
from app.extraction import extract_invoice_data
from app.forensics.scorer import run_forensics

broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6380/0')
result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6380/0')

celery_app = Celery('cotejo_tasks', broker=broker_url, backend=result_backend)

@celery_app.task
def extract_task(pdf_path: str):
    factura = extract_invoice_data(pdf_path)
    return factura.model_dump()

@celery_app.task
def forensics_task(pdf_path: str):
    report = run_forensics(pdf_path)
    return report.model_dump()
