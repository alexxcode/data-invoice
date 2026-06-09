import os
import json
import random
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

def generate_invoice(filename: str, anomaly_type: str = "none", layout: str = "standard") -> dict:
    """
    Genera facturas sintéticas variando layout e inyectando anomalías.
    Devuelve un diccionario con el Ground Truth (lo que el Agente DEBERÍA encontrar).
    """
    
    # Configuración de layout
    if layout == "ticket":
        pagesize = (3*inch, 10*inch) # Formato ticket de supermercado
    else:
        pagesize = A4
        
    c = canvas.Canvas(filename, pagesize=pagesize)
    
    # Datos base aleatorios
    factura_id = f"FRA-{random.randint(1000, 9999)}"
    emisor = "Energía Falsa S.A."
    cif = "A99887766"
    cups = "ES0021000000000000BAD"
    subtotal = round(random.uniform(50, 150), 2)
    impuestos = round(subtotal * 0.21, 2)
    total_real = round(subtotal + impuestos, 2)
    total_impreso = total_real
    
    ground_truth = {
        "is_invoice": True,
        "math_error": False,
        "missing_cups": False,
        "missing_cif": False,
        "layout": layout
    }
    
    # Inyección de Anomalías
    if anomaly_type == "math_error":
        total_impreso = round(total_real * 1.3, 2)
        ground_truth["math_error"] = True
    elif anomaly_type == "missing_cups":
        cups = ""
        ground_truth["missing_cups"] = True
    elif anomaly_type == "missing_cif":
        cif = ""
        ground_truth["missing_cif"] = True
    elif anomaly_type == "not_an_invoice":
        ground_truth["is_invoice"] = False

    if ground_truth["is_invoice"] == False:
        # Generar una simple carta
        c.setFont("Helvetica", 12)
        c.drawString(1*inch, 10*inch, "Estimado cliente, esto es un aviso de corte de servicio, no una factura.")
        c.save()
        return ground_truth

    # --- Renderizado según Layout ---
    if layout == "rotated":
        # Rotar la página entera para probar la robustez visual del LLM
        c.translate(pagesize[0], 0)
        c.rotate(90)

    if layout == "ticket":
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.2*inch, 9*inch, "TICKET DE LUZ")
        c.setFont("Helvetica", 8)
        c.drawString(0.2*inch, 8.5*inch, f"Fac: {factura_id}")
        if cif: c.drawString(0.2*inch, 8.2*inch, f"CIF: {cif}")
        if cups: c.drawString(0.2*inch, 7.9*inch, f"CUPS: {cups}")
        c.drawString(0.2*inch, 7.0*inch, f"Sub: {subtotal}")
        c.drawString(0.2*inch, 6.8*inch, f"IVA: {impuestos}")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.2*inch, 6.0*inch, f"TOTAL: {total_impreso}")
    else:
        # Standard o Rotated usan las mismas coordenadas
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1 * inch, 10.5 * inch, "FACTURA DE ELECTRICIDAD")
        c.setFont("Helvetica", 12)
        c.drawString(1 * inch, 10 * inch, f"Nº Factura: {factura_id}")
        
        if cif:
            c.drawString(1 * inch, 9.5 * inch, f"Emisor: {emisor} - CIF: {cif}")
        else:
            c.drawString(1 * inch, 9.5 * inch, f"Emisor: {emisor}")
            
        c.drawString(1 * inch, 9 * inch, f"Cliente: Usuario Prueba")
        if cups:
            c.drawString(1 * inch, 8.5 * inch, f"CUPS: {cups}")
        
        c.drawString(1 * inch, 7.5 * inch, "CONCEPTOS:")
        c.drawString(1.5 * inch, 7 * inch, f"Importe Energía: {subtotal} EUR")
        c.drawString(1.5 * inch, 6.5 * inch, f"Impuestos aplicados: {impuestos} EUR")
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1 * inch, 5.5 * inch, f"TOTAL FINAL A PAGAR: {total_impreso} EUR")
        
    c.save()
    return ground_truth

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "samples", "eval_dataset")
    os.makedirs(out_dir, exist_ok=True)
    
    dataset_truth = {}
    
    # 1. Facturas Limpias (Standard)
    for i in range(3):
        fname = f"clean_std_{i}.pdf"
        dataset_truth[fname] = generate_invoice(os.path.join(out_dir, fname), "none", "standard")
        
    # 2. Facturas Limpias (Layouts Variados)
    for i in range(2):
        fname = f"clean_ticket_{i}.pdf"
        dataset_truth[fname] = generate_invoice(os.path.join(out_dir, fname), "none", "ticket")
        fname = f"clean_rotated_{i}.pdf"
        dataset_truth[fname] = generate_invoice(os.path.join(out_dir, fname), "none", "rotated")
        
    # 3. Anomalías Matemáticas
    for i in range(2):
        fname = f"anom_math_{i}.pdf"
        dataset_truth[fname] = generate_invoice(os.path.join(out_dir, fname), "math_error", "standard")
        
    # 4. Campos Faltantes (CIF/CUPS)
    dataset_truth["anom_cups.pdf"] = generate_invoice(os.path.join(out_dir, "anom_cups.pdf"), "missing_cups", "standard")
    dataset_truth["anom_cif_ticket.pdf"] = generate_invoice(os.path.join(out_dir, "anom_cif_ticket.pdf"), "missing_cif", "ticket")
    
    # 5. Documentos Inválidos
    dataset_truth["invalid_doc.pdf"] = generate_invoice(os.path.join(out_dir, "invalid_doc.pdf"), "not_an_invoice", "standard")
    
    # Guardar Ground Truth
    with open(os.path.join(out_dir, "ground_truth.json"), "w") as f:
        json.dump(dataset_truth, f, indent=4)
        
    print(f"Dataset de Evaluación generado en {out_dir}")
    print(f"Total documentos: {len(dataset_truth)}")
