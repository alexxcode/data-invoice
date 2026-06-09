# Cotejo: Motor Dual de Auditoría Documental y Ruteo Heurístico

Cotejo es un sistema de extracción y validación de facturas diseñado bajo una premisa central: **los Modelos de Lenguaje (LLMs) alucinan**. 

En lugar de confiar el proceso completo a una IA generativa, el sistema aísla el proceso de lectura (delegado al LLM) del proceso de validación final (delegado a un código determinista tradicional). Esto permite rutar los documentos de forma segura sin depender de que un LLM tome la decisión de rechazo.

---

## 1. Arquitectura del Sistema

El pipeline de procesamiento se divide en tres capas con responsabilidades estrictamente separadas:

### Fase 1: Extracción Visual (VLM)
Convierte documentos PDF en mapas de bits (imágenes a 150 DPI) usando `PyMuPDF`. Estas imágenes se envían a Gemini 2.5 Flash operando a Temperatura 0.0 para forzar la máxima predictibilidad en la estructura JSON devuelta.
*   **Confidence Score:** El modelo de lenguaje emite un valor numérico estimado libremente por él mismo (0.0 a 1.0) sobre la legibilidad visual del documento. No es un valor estadísticamente calibrado.

### Fase 2: Motor Determinista (Matemático)
Script en Python puro (`app/rules.py`) que audita los datos que el LLM extrajo en la Fase 1.
*   **Regla principal:** Verifica que `Subtotal + Impuestos = Total Declarado`.
*   **Identificadores:** Revisa si existen las cadenas de texto del CIF y el CUPS.
*   **Autoridad:** Es el **único** componente del sistema autorizado para emitir un fallo de Rechazo (`REJECT`). Como el código no alucina, garantiza que no habrá Falsos Positivos causados por un error lógico de la máquina.

### Fase 3: Análisis Semántico Contextual
Se ejecuta un segundo prompt al LLM buscando inconsistencias en la lógica de negocio (ej. IVA del 50%, tarifas incongruentes).
*   **Limitación de Autoridad:** Como las inferencias del LLM en texto son ruidosas y propensas a Falsos Positivos, cualquier hallazgo en esta capa solo emite una advertencia (`Warning`). **Jamás** causa un rechazo automático; solo fuerza una revisión manual.

---

## 2. Políticas de Ruteo

El Orquestador (`app/agent.py`) decide a dónde enviar la factura usando umbrales fijos sobre el Score de Confianza del LLM y las reglas deterministas:

*   **🟢 AUTO_APPROVE:** `Score > 0.90` y cero errores matemáticos. La factura se procesa sin intervención humana.
*   **🟡 MANUAL_REVIEW:** `0.60 ≤ Score ≤ 0.90` o si el LLM detectó anomalías semánticas. Un operador humano debe revisar el documento.
*   **🔴 REJECT:** `Score < 0.60` o fraude matemático (`Subtotal + Impuestos != Total`).

---

## 3. Metodología de Evaluación y Limitaciones (n=84)

Resultados de la muestra ampliada ejecutada contra un inyector de anomalías sintéticas (*Baseline* vs *Ground Truth*):

| Métrica | Motor Determinista (Python) | Motor Contextual (LLM) |
|---|---|---|
| **Precisión (Precision)** | 1.00 (100%) | N/A (Solo emite Warnings) |
| **Recall (Tasa de Captura)** | 1.00 (100%) | No calibrado |
| **Falsos Positivos (FP)** | 0 | 21 (Ruido del modelo) |
| **Falsos Negativos (FN)** | 0 | 0 |

> ***Nota sobre las Limitaciones del Sistema en Producción:** Los ceros absolutos en el motor determinista son un artefacto de hacer pruebas sobre PDFs sintéticos (nativos digitales). En el mundo real (al escalar a un dataset de 75,000 facturas escaneadas), los documentos estarán borrosos, arrugados o mal iluminados. Esto causará que el LLM se equivoque al leer los números (ej. confundir un 8 con un 3). Cuando el LLM extrae un número mal, la suma determinista en Python fallará, lo que levantará un **Falso Positivo**. Es decir: en producción, los fallos de lectura del LLM se transformarán invariablemente en alertas matemáticas. El ruteo mitiga esto mandando dichos casos a Revisión Manual.*

---

## 4. Interfaz de Usuario y Ruteo

La interfaz web rutea los resultados demostrando el origen del dato (Página del PDF) y aplicando los colores de la política de decisión:

<div align="center">
  <img src="imagenes_repo/Screenshot%202026-06-08%20225846.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20225900.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232503.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232704.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20234921.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20235349.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-09%20000218.png" width="45%" />
</div>

---

## 5. Tecnologías y Despliegue Local

- **API:** Python 3.12, FastAPI, Pydantic v2.
- **Modelos:** Google GenAI SDK (Gemini 2.5 Flash / Pro).
- **Procesamiento de PDF:** PyMuPDF.

**Ejecución:**
```bash
pip install -r requirements.txt
# Configurar GEMINI_API_KEY en archivo .env
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```
