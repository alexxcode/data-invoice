import os
import requests
import zipfile
from io import BytesIO

# Zenodo IDSEM DOI record: 6373179
ZENODO_API_URL = "https://zenodo.org/api/records/6373179"
TARGET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples")

def download_sample():
    print("Obteniendo información del registro de Zenodo...")
    response = requests.get(ZENODO_API_URL)
    if response.status_code != 200:
        print(f"Error al conectar con Zenodo: {response.status_code}")
        return

    data = response.json()
    files = data.get("files", [])
    
    # En IDSEM, los PDFs suelen estar en archivos zip (ej. train_pdfs_*.zip o test_pdfs.zip)
    # Buscaremos un zip pequeño o simplemente uno de los archivos para extraer solo unos pocos PDFs
    target_file = None
    for f in files:
        if f["key"].endswith(".zip") and "test" in f["key"].lower():
            target_file = f
            break
            
    if not target_file and files:
        target_file = files[0] # Tomamos el primero si no hay "test"

    if not target_file:
        print("No se encontraron archivos descargables.")
        return

    print(f"Descargando archivo {target_file['key']} (tamaño aprox: {target_file['size'] / 1024 / 1024:.2f} MB)...")
    
    # IMPORTANTE: Como el internet local es malo, podríamos abortar si es demasiado grande, 
    # pero para el script asumimos que es el test set (que debería ser más pequeño que el de entrenamiento).
    # Como el archivo puede ser pesado, usaremos un flujo iterativo y solo extraeremos los primeros 5 archivos
    
    download_url = target_file["links"]["self"]
    
    os.makedirs(TARGET_DIR, exist_ok=True)
    
    print(f"Descargando {download_url}...")
    r = requests.get(download_url, stream=True)
    if r.status_code == 200:
        z = zipfile.ZipFile(BytesIO(r.content))
        pdf_files = [n for n in z.namelist() if n.endswith('.pdf')]
        
        # Extraer solo 5
        sample_pdfs = pdf_files[:5]
        for pdf_name in sample_pdfs:
            print(f"Extrayendo: {pdf_name}")
            z.extract(pdf_name, TARGET_DIR)
            
        print(f"\n¡Éxito! Se han guardado {len(sample_pdfs)} facturas de muestra en {TARGET_DIR}")
    else:
        print(f"Error en la descarga: {r.status_code}")

if __name__ == "__main__":
    download_sample()
