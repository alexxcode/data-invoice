import os
import random
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except ImportError:
    print("Error: reportlab no está instalado. Ejecuta 'pip install reportlab'")
    exit(1)

TARGET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples")
os.makedirs(TARGET_DIR, exist_ok=True)

def generate_mock_invoice(filename, invoice_num, total):
    filepath = os.path.join(TARGET_DIR, filename)
    c = canvas.Canvas(filepath, pagesize=letter)
    
    # Encabezado
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, "Factura de Energía Eléctrica")
    
    c.setFont("Helvetica", 12)
    c.drawString(50, 720, f"Número de Factura: {invoice_num}")
    c.drawString(50, 700, "Emisor: Comercializadora Eléctrica S.A.")
    c.drawString(50, 680, "CIF Emisor: A12345678")
    
    c.drawString(50, 640, "Cliente: Cliente de Prueba")
    c.drawString(50, 620, "CUPS: ES0021000000000000AA0F")
    
    # Cálculos
    subtotal = round(total / 1.21, 2)
    iva = round(total - subtotal, 2)
    
    c.drawString(50, 580, f"Importe Energía (Subtotal): {subtotal} EUR")
    c.drawString(50, 560, f"Impuestos (IVA 21%): {iva} EUR")
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 520, f"TOTAL A PAGAR: {total} EUR")
    
    c.save()

def run():
    print(f"Generando 5 facturas sintéticas en {TARGET_DIR}...")
    for i in range(1, 6):
        total = round(random.uniform(40.0, 150.0), 2)
        generate_mock_invoice(f"mock_factura_{i:03d}.pdf", f"FAC-2023-{i:04d}", total)
    print("¡Generación local de muestras completada!")

if __name__ == "__main__":
    run()
