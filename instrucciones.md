# Cotejo — instrucciones.md

**Agente de auditoría de documentos financieros.** Detección de anomalías y resumen auditable con citas a la fuente, sobre facturas en español.

> Documento dirigido a personal técnico y a agentes de código. Define visión de producto, objetivos, decisiones fijadas, datos, arquitectura y fases de construcción. Un agente debe poder ejecutar este plan de principio a fin sin re-litigar decisiones ya tomadas. *Cotejo* es nombre de trabajo; renombrable.

---

## 0. Resumen en una línea

Cotejo recibe un lote de facturas, extrae sus datos con un modelo multimodal, detecta anomalías e inconsistencias, y produce un informe de auditoría legible donde **cada hallazgo está citado a su documento y campo de origen**.

---

## 1. Visión de producto

**Problema.** Revisar facturas a mano es lento y propenso a error. Las herramientas existentes resuelven la *extracción* (OCR/parsing), que ya es commodity. Lo que sigue siendo trabajo humano es el *juicio*: detectar que un total no cuadra, que una factura está duplicada, que un consumo se sale de rango, que faltan campos obligatorios, y dejar constancia trazable de por qué.

**Usuario.** Quien revisa lotes de facturas: contabilidad de PYME, operaciones de fintech, auditoría interna. El demo se construye sobre facturas eléctricas españolas (IDSEM) por disponibilidad de datos, pero la lógica es agnóstica al emisor.

**Qué es.** Un agente que orquesta un modelo multimodal y un motor de reglas para auditar, no solo leer.

**Qué NO es.**
- No es un OCR ni un parser. La extracción es un medio, no el producto.
- No es un asesor financiero. No emite recomendaciones de inversión ni juicios regulatorios vinculantes. Señala hallazgos y los justifica; la decisión es del humano.
- No es un detector de fraude entrenado. Detecta inconsistencias y anomalías definidas, no fraude sofisticado.

**Diferenciación (dónde vive el valor).** En la capa agéntica: el motor de anomalías y el resumen auditable con citas. Si el proyecto se reduce a "llamo a un VLM y devuelvo JSON", fracasó su propósito. El criterio de calidad es: *¿un auditor humano podría confiar en el informe y verificar cada hallazgo contra la fuente sin reabrir todos los documentos?*

---

## 2. Objetivos y no-objetivos

**Objetivos medibles (definición de "listo" para v1):**
- **O1.** Extraer campos estructurados de una factura (emisor, fecha, identificadores, líneas, subtotales, impuestos, total) con exactitud medible contra el subconjunto etiquetado de IDSEM.
- **O2.** Detectar, sobre un conjunto con anomalías inyectadas de *ground truth* conocido, al menos la taxonomía de anomalías de la sección 4.3, reportando precision y recall.
- **O3.** Emitir un informe de auditoría por lote donde cada hallazgo incluye una cita verificable (documento + campo/página) a la fuente.
- **O4.** Servir todo detrás de una API en Cloud Run, con una UI mínima que permita subir documentos y ver el informe.
- **O5.** Repo público, reproducible, con README, evaluación honesta y un demo desplegado.

**No-objetivos (fuera de alcance de v1, no implementar):**
- Entrenar o afinar modelos.
- Detección de falsificación o autenticidad de documento.
- Soporte multi-idioma más allá de español (inglés queda como dato de robustez de layout, no como objetivo de producto).
- Integraciones contables reales, autenticación de usuarios, multi-tenant, persistencia a largo plazo.
- Conciliación contra sistemas externos (bancos, ERPs).

---

## 3. Decisiones fijadas (no re-litigar)

| Decisión | Valor | Razón |
|---|---|---|
| Idioma/región | Español (datos: España vía IDSEM) | Disponibilidad de datos públicos etiquetados en español |
| Flujo núcleo | Detección de anomalías + resumen auditable con citas | Elegido; es la diferenciación |
| Entrenamiento | Ninguno. Pura orquestación zero-shot | Velocidad, sin etiquetado; Gemini extrae sin entrenar |
| Modelos | Gemini vía API key. Flash para extracción, Pro para razonamiento de auditoría | Ecosistema nativo del autor; coste/latencia en extracción, profundidad en juicio |
| Despliegue | Cloud Run (GCP) | Ecosistema nativo, despliegue simple |
| Repo | Público desde el inicio | Es el vehículo de visibilidad |
| Timebox | 1-2 semanas, demo de portafolio | No es producto productivo |
| Datos sensibles | Solo sintético/público | Repo público; nada de documentos reales |

> Colab Pro y GPU de Google **no se usan en v1** porque no hay entrenamiento. Solo entran si se decide añadir, fuera de este alcance, un componente entrenado (p. ej. un clasificador de tipo de documento).

---

## 4. Datos

### 4.1 Dataset primario
- **IDSEM** — Invoices Database of the Spanish Electricity Market. 75.000 facturas en PDF con etiquetas JSON (86 campos), datos sintéticos realistas basados en regulación y estadística españolas. Publicado en *Nature Scientific Data* (2022); descargable desde el enlace de disponibilidad de datos del artículo. **Es el ancla**: español, público, etiquetado, sin privacidad comprometida.

### 4.2 Suplementos (robustez de layout y anomalías)
- **FATURA** — 10.000 facturas, 50 layouts distintos, imágenes anotadas (arXiv 2311.11856). Para variar layouts.
- **SROIE** — 1.000 recibos escaneados (626/347), inglés, ICDAR 2019, entidades: empresa, fecha, dirección, total. Robustez de recibo.
- **CORD** — 1.000 recibos (indonesios), 30 entidades jerárquicas. Robustez de líneas/ítems.
- **Mock invoices** (Kaggle, generadas con Faker) — tabulares; base limpia para inyección controlada de anomalías.
- **mychen76/invoices-and-receipts_ocr_v1** (Hugging Face) — facturas/recibos para OCR; respaldo de variedad.

> Inglés/indonesio se usan **solo** para verificar que el pipeline no se rompe con layouts no vistos. El producto es en español.

### 4.3 Anomalías: cómo se construyen
No existe dataset público de "anomalías etiquetadas en facturas". Por tanto se **inyectan** sobre datos limpios (IDSEM o mock), generando *ground truth* conocido. Taxonomía mínima de v1:
1. **Aritmética**: subtotal + impuestos ≠ total; suma de líneas ≠ subtotal.
2. **Duplicados**: misma factura (mismo identificador/emisor/fecha/monto) repetida en el lote.
3. **Fuera de rango**: consumo o monto que se desvía de la distribución esperada (outlier estadístico simple).
4. **Campos faltantes o inválidos**: falta identificador fiscal, fecha imposible, formato inválido.
5. **Inconsistencia interna**: tarifa × consumo ≠ importe de línea; fechas de periodo incoherentes.

> Nota honesta para el README: anomalías inyectadas ≠ fraude real. Demuestran que el motor detecta lo que se define; no que generaliza a fraude sofisticado.

### 4.4 Privacidad
Repo público: solo datos sintéticos o públicos. Si se usan documentos propios para el demo, deben ir redactados. Ningún documento real con datos personales entra al repo ni a logs.

---

## 5. Arquitectura

Flujo de un lote de auditoría:

```
[Documentos: PDF/imagen]
      │
      ▼
(1) Ingestión        normaliza a páginas/imágenes; agrupa por lote
      │
      ▼
(2) Extracción       Gemini Flash (multimodal) → JSON estructurado por documento
      │                con provenance: página y, donde sea posible, ubicación del campo
      ▼
(3) Validación       valida el JSON contra un esquema (Pydantic); marca campos faltantes/ inválidos
      │
      ▼
(4) Motor de         reglas determinísticas (aritmética, duplicados, rango, formato)
    anomalías        + razonamiento LLM (Gemini Pro) para inconsistencias contextuales
      │
      ▼
(5) Resumen          Gemini Pro redacta el informe; cada hallazgo lleva cita {doc, campo/página}
    auditable        las citas se generan desde la provenance, no las inventa el modelo
      │
      ▼
[Informe de auditoría: JSON + render legible]  ──►  API (FastAPI) en Cloud Run  ──►  UI mínima
```

**Principio de groundedness.** Las citas y los números del informe se construyen a partir de la salida estructurada y verificada (paso 3), no del texto libre del LLM. El LLM redacta y razona; no es la fuente de verdad de las cifras. Esto contiene la alucinación.

---

## 6. La capa agéntica (el núcleo)

Implementación con **function calling de Gemini**. Dependencias mínimas; no se requiere un framework de agentes pesado. El agente coordina herramientas; el motor de reglas es código determinístico.

**Herramientas expuestas al agente:**
- `extract_document(doc)` → JSON estructurado + provenance (vía Gemini Flash).
- `validate_schema(json)` → lista de campos faltantes/ inválidos.
- `run_rule_checks(batch)` → hallazgos determinísticos (aritmética, duplicados, rango, formato).
- `flag_contextual_inconsistencies(batch)` → razonamiento LLM sobre coherencia interna y entre documentos.
- `compose_audit_report(findings)` → informe con citas, redactado por Gemini Pro a partir de hallazgos ya estructurados.

**Bucle del agente (alto nivel):** por cada documento, extraer → validar; sobre el lote, correr reglas y chequeo contextual; consolidar hallazgos; componer informe citado. El razonamiento del agente decide qué herramienta correr y cómo agregar, pero **las cifras y citas provienen siempre de las herramientas determinísticas**.

**Provenance/citas.** Cada campo extraído conserva `{doc_id, page, field_path}`. Cada hallazgo referencia los campos que lo originaron. El informe renderiza esas referencias como citas verificables ("Factura 0312, página 1, total: 142,30 € no coincide con subtotal + IVA = 138,90 €").

---

## 7. Fases de construcción

Cada fase tiene **entregable** y **criterio de aceptación**. Un agente debe completar y verificar una fase antes de la siguiente.

**Fase 0 — Setup.** Repo público, estructura (sección 8), entorno, claves de Gemini por variable de entorno, `requirements`, esqueleto de FastAPI que arranca.
*Aceptación:* `GET /health` responde 200 local.

**Fase 1 — Ingestión + extracción.** Cargar PDF/imagen, normalizar, llamar a Gemini Flash, devolver JSON por documento con provenance.
*Aceptación:* sobre 20 facturas de IDSEM, devuelve JSON parseable con los campos núcleo poblados.

**Fase 2 — Esquema + validación.** Definir el esquema (Pydantic) de una factura. Validar la extracción; marcar faltantes/ inválidos.
*Aceptación:* validación reporta correctamente campos faltantes en casos construidos a mano.

**Fase 3 — Motor de anomalías.** Implementar las reglas determinísticas de 4.3 y el chequeo contextual LLM. Script de inyección de anomalías con ground truth.
*Aceptación:* sobre un set con anomalías inyectadas, se reportan precision y recall por tipo; las reglas aritméticas/duplicados aciertan ≈100% (son determinísticas).

**Fase 4 — Resumen auditable con citas.** Componer el informe (JSON + render legible) con cita por hallazgo, construida desde provenance.
*Aceptación:* cada hallazgo del informe es trazable a un documento y campo reales; muestreo manual de 10 hallazgos, 10/10 citas correctas.

**Fase 5 — API + UI mínima.** Endpoint de auditoría de lote; UI mínima (subir documentos, ver informe). Sin auth, sin persistencia.
*Aceptación:* subir un lote por la UI devuelve y renderiza el informe.

**Fase 6 — Despliegue + demo.** Contenerizar, desplegar en Cloud Run, `min-instances` para el demo, README con evaluación honesta y límites.
*Aceptación:* URL pública responde; un lote de ejemplo produce informe en menos de un cold start tolerable.

---

## 8. Stack y estructura del repo

**Stack:** Python, FastAPI, Pydantic, Gemini API (Flash + Pro) vía API key, contenedor en Cloud Run. UI mínima (HTML/JS simple o un framework ligero; sin sobre-ingeniería). Preprocesado de PDF con una librería estándar.

```
cotejo/
  app/
    main.py            # FastAPI: /health, /audit
    extraction.py      # Gemini Flash + provenance
    schema.py          # modelos Pydantic
    rules.py           # motor determinístico de anomalías
    contextual.py      # chequeo contextual con Gemini Pro
    report.py          # composición del informe + citas
    agent.py           # orquestación / function calling
  data/
    inject_anomalies.py
    samples/           # solo sintético/público
  ui/                  # UI mínima
  eval/
    run_eval.py        # extracción, anomalías (P/R), citas
  tests/
  Dockerfile
  requirements.txt
  README.md
```

**Variables de entorno:** `GEMINI_API_KEY`. Nunca hardcodear claves; nunca commitearlas.

---

## 9. Evaluación y criterios de éxito

Honestidad como en proyectos previos: reportar lo que no funciona.
- **Extracción.** Exactitud por campo contra el subconjunto etiquetado de IDSEM. Reportar por campo, no un promedio engañoso.
- **Anomalías.** Precision y recall por tipo, sobre anomalías inyectadas (ground truth conocido). Separar reglas determinísticas (deben acertar) de chequeo contextual LLM (donde está el riesgo).
- **Citas.** Porcentaje de hallazgos con cita verificable correcta (muestreo manual).
- **Operación.** Latencia por documento y por lote; coste estimado por lote (llamadas a Gemini).

Reportar todo en el README, incluidos los fallos.

---

## 10. Riesgos y límites honestos

- **OCR es commodity.** Si el valor percibido se queda en la extracción, el proyecto no se diferencia. Mitigación: el informe auditable con citas y el motor de anomalías son la cara visible del demo, no el JSON crudo.
- **España ≠ LatAm.** IDSEM es español de España. Para LatAm específico no hay data pública equivalente; quedaría generar sintético. Declararlo, no esconderlo.
- **Anomalías inyectadas ≠ fraude real.** Demuestran detección de lo definido, no generalización a fraude. Declararlo.
- **Alucinación del LLM en el resumen.** Mitigada por groundedness: cifras y citas vienen de las herramientas, el LLM solo redacta. Verificar con el chequeo de citas.
- **Coste y cold start.** Gemini por lote tiene coste; Cloud Run con `min-instances=0` da cold start. Para el periodo del demo, subir `min-instances` y verificar la URL en vivo.

---

## 11. Demo y narrativa (para el post)

El demo no muestra "leo una factura". Muestra: *se sube un lote, el sistema marca las facturas con problemas, y entrega un informe donde cada alerta se puede verificar contra el documento de origen.* Esa es la historia: del juicio humano repetitivo a un informe trazable. Para conexiones, publicar en español (canal subutilizado) y usarlo como gancho para contactos del sector fintech/IA, no solo para impresiones.
