# Threat Model — Cotejo

> Qué fraude documental intenta detectar Cotejo, contra qué adversario, bajo qué supuestos, y
> qué queda explícitamente fuera de alcance. Esta sección es deliberadamente de primera clase:
> sin un modelo de amenaza explícito, las métricas de detección no son interpretables (¿100%
> de qué, contra quién?). Todas las afirmaciones de cobertura del README deben leerse contra
> esta taxonomía.

---

## 1. Activo protegido

La decisión financiera: **aprobar (pagar) o no una factura**. El daño no es "una imagen
editada" en abstracto, sino un pago indebido autorizado a partir de un documento alterado o
fabricado. Por eso la unidad de evaluación es el **documento → decisión**, no el píxel.

Corolario de diseño (modelo de autoridad): **solo el motor determinista puede RECHAZAR**. Las
capas forense y VLM nunca rechazan por sí solas; solo derivan a revisión humana
(`MANUAL_REVIEW`). Una detección fallida no produce un pago automático indebido salvo que el
documento además pase el ruteo de auto-aprobación — y ese conjunto está acotado por la garantía
conformal (ver README §5.3).

---

## 2. Taxonomía de adversarios (por capacidad)

| Adversario | Capacidad | Traza que deja | Quién lo cubre en Cotejo |
|---|---|---|---|
| **A1 — Casual** | Edita un dígito/monto con un editor de imagen o app de móvil y reenvía | Inconsistencia de píxel/estructura **si el archivo no se recomprime**; a menudo rompe la aritmética | Determinista (si rompe la suma) + forense de píxel (si sobrevive la transmisión) + VLM (inconsistencia visible) |
| **A2 — Competente** | Edita y **reimprime+reescanea** o regenera el PDF con aritmética consistente | Las trazas de píxel/estructura desaparecen; la aritmética cuadra | VLM (razonamiento sobre incoherencia residual) + tipografía (parcial); el forense clásico **falla aquí** (demostrado, Fase 1) |
| **A3 — Fabricador** | Genera una factura **falsa desde cero**, internamente consistente, con datos plausibles | Ninguna: el archivo es forensemente impecable y la aritmética es correcta | **Fuera de alcance del análisis intrínseco**; requiere reconciliación contra fuente externa (§4) |

El proyecto **no** asume un adversario adaptativo que conozca los detectores y los evada a
propósito (ataques adaptativos / caja blanca). El benchmark v1 modela A1 y A2 sobre documentos
reales; A3 es el límite declarado.

---

## 3. Canal de transmisión (dimensión de degradación)

Una factura no llega "limpia": atraviesa un canal que destruye evidencia. El benchmark evalúa
cada ataque bajo cuatro canales, y el canal es parte del modelo de amenaza, no un detalle:

- **original** — sin recompresión (límite optimista, poco realista en producción).
- **recompress** — reenvío por email/gestor documental (JPEG q≈60–85).
- **whatsapp** — redimensionado a ≤1280px + q≈70 (el canal real más común en PYME/LatAm).
- **print_scan** — impresión y reescaneo (rotación, blur, ruido de sensor).

Hallazgo central (Fase 1): el canal **decide** la viabilidad de cada detector. El forense de
píxel clásico que "funciona" en `original` es ruido bajo `whatsapp`/`print_scan`. Reportar
detección sin declarar el canal es engañoso.

---

## 4. Vectores explícitamente fuera de alcance

1. **Fabricación de contenido (A3)** con datos internamente consistentes y sin referencia
   externa: forensemente indetectable. Requiere reconciliación multi-documento o contra
   sistemas externos (ERP, registro mercantil, padrón de proveedores) — *roadmap*, no v1.
2. **Adversario adaptativo** que optimiza contra los detectores conocidos.
3. **Fraude no documental** (colusión, factura legítima por servicio no prestado): el documento
   es auténtico; el fraude es de negocio, fuera del alcance de un analizador de documentos.
4. **Localización a nivel píxel** del área manipulada: Fase 1–2 muestran que ni el stack clásico
   ni un VLM de propósito general localizan la región en facturas reales transmitidas. Cotejo
   v1 opera a **nivel documento** (detectar + derivar), no a nivel píxel. La localización queda
   como problema abierto (candidatos: detectores aprendidos tipo TruFor/CAT-Net — Fase 2 #12).

---

## 5. Qué cubre cada capa (mapa defensa → amenaza)

| Capa | Vector que ataca | Autoridad | Evidencia |
|---|---|---|---|
| **Motor determinista** (`app/rules.py`) | Aritmética rota, duplicados, campos faltantes/ inválidos | **RECHAZA** | Cita {doc, campo/página} |
| **Forense clásico** (`app/forensics/`) | Manipulación de archivo/píxel (A1 sin transmisión) | Solo deriva | Overlay + bbox |
| **VLM-judge** (`eval/vlm_judge.py`) | Incoherencia visible/semántica (A1, parte de A2) | Solo deriva | Región + razón en NL |
| **Ruteo conformal** (`eval/fusion_routing.py`) | Decide automatización con cota de fuga | Auto-aprueba bajo garantía | Curva riesgo-cobertura |

**Principio de groundedness:** las cifras y citas del informe provienen de las herramientas
deterministas y de la procedencia estructurada, no del texto libre del LLM. El LLM razona y
redacta; no es la fuente de verdad de los números.

---

## 6. Supuestos de confianza

- El **pipeline de ejecución** y los modelos no están comprometidos (no se modela un atacante en
  la cadena de suministro del software).
- El **ground truth de evaluación** es sintético-pero-realista (manipulaciones inyectadas sobre
  facturas reales). Anomalías inyectadas ≠ fraude de campo: demuestran detección de lo definido,
  no generalización a fraude sofisticado real. Declarado, no escondido.
- La **prevalencia de manipulación** en producción es baja (típicamente <5%). El benchmark está
  saturado de ataques a propósito; los titulares de automatización/fuga se reproyectan a la
  prevalencia real (Fase 3), y la garantía conformal se fija sobre la clase de fraude para ser
  independiente de esa mezcla.
