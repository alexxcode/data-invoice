from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

app = FastAPI(title="Cotejo", description="Agente de auditoría de documentos financieros")

# Montar carpeta estática para la UI si existe
ui_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
if os.path.exists(ui_dir):
    app.mount("/ui", StaticFiles(directory=ui_dir), name="ui")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Cotejo API"}

@app.get("/", response_class=HTMLResponse)
def root():
    # Redirigir o mostrar html base
    return "<h1>Cotejo API Funcional</h1><p>Visita <a href='/docs'>/docs</a> para ver la API o <a href='/ui/index.html'>/ui/index.html</a> para la interfaz.</p>"

@app.post("/audit")
async def audit_batch(files: list[UploadFile] = File(...)):
    """
    Recibe un lote de facturas (PDF/Imágenes), orquesta la extracción,
    valida reglas e inconsistencias, y retorna un reporte auditable.
    """
    from app.agent import process_batch
    import shutil
    
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples", "temp_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    saved_paths = []
    for file in files:
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_paths.append(file_path)
        
    try:
        reportes = process_batch(saved_paths)
        return {"status": "success", "reports": [r.model_dump() for r in reportes]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
