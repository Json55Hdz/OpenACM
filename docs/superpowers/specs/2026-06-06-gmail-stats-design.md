# Gmail Classifier — Estadísticas y Exportación

**Fecha:** 2026-06-06
**Plugin:** `gmail_classifier`
**Estado:** Aprobado

---

## Resumen

Página de estadísticas para el plugin Gmail Classifier. Muestra métricas agregadas sobre el período seleccionado con charts interactivos. Permite exportar el reporte en PDF (impresión del browser) y Excel (generado server-side con openpyxl).

---

## Métricas cubiertas

| Métrica | Fuente |
|---|---|
| Volumen de correos por día | `gmail_emails.received_at` |
| Distribución por categoría (total / leídos / respondidos / IA clasificados) | `gmail_emails` JOIN `gmail_categories` |
| Tasa de respuesta global y por categoría | `is_replied / total` |
| Top 10 remitentes | `gmail_emails.sender_email`, `sender_name` |
| Auto-reply: sugerencias generadas, borradores guardados, ejemplos aprendidos, uso promedio | `gmail_emails.ai_suggestion != ''`, `gmail_reply_drafts`, `gmail_reply_examples` |

---

## Backend

### Endpoint: `GET /stats`

**Query params:** `from` (YYYY-MM-DD), `to` (YYYY-MM-DD). Ambos requeridos.

**Respuesta:**

```json
{
  "period": {
    "from": "2026-05-01",
    "to": "2026-06-06",
    "total_emails": 342
  },
  "volume_by_day": [
    {"date": "2026-05-01", "count": 12}
  ],
  "by_category": [
    {
      "id": 1,
      "name": "Trabajo",
      "color": "#ff0000",
      "total": 80,
      "read": 75,
      "replied": 40,
      "ai_classified": 78
    }
  ],
  "top_senders": [
    {"email": "jefe@co.com", "name": "Jefe", "count": 25}
  ],
  "reply_rate": {
    "total": 342,
    "replied": 180,
    "rate": 0.526
  },
  "autoreply": {
    "suggestions_generated": 45,
    "drafts_saved": 12,
    "examples_learned": 8,
    "avg_use_count": 2.3
  }
}
```

**Implementación:** Todo SQL sobre tablas existentes, sin nuevas tablas.

```sql
-- volume_by_day
SELECT date(received_at) as date, COUNT(*) as count
FROM gmail_emails
WHERE received_at >= ? AND received_at < date(?, '+1 day')
GROUP BY date(received_at) ORDER BY date;

-- by_category
SELECT c.id, c.name, c.color,
  COUNT(e.id) as total,
  SUM(e.is_read) as read,
  SUM(e.is_replied) as replied,
  SUM(e.ai_classified) as ai_classified
FROM gmail_categories c
LEFT JOIN gmail_emails e ON e.category_id = c.id
  AND e.received_at >= ? AND e.received_at < date(?, '+1 day')
GROUP BY c.id;

-- top_senders (top 10)
SELECT sender_email, sender_name, COUNT(*) as count
FROM gmail_emails
WHERE received_at >= ? AND received_at < date(?, '+1 day')
GROUP BY sender_email ORDER BY count DESC LIMIT 10;

-- autoreply: suggestions_generated
SELECT COUNT(*) FROM gmail_emails
WHERE ai_suggestion != '' AND received_at >= ? AND received_at < date(?, '+1 day');

-- autoreply: drafts_saved
SELECT COUNT(*) FROM gmail_reply_drafts
WHERE created_at >= ? AND created_at < date(?, '+1 day');

-- autoreply: examples_learned + avg_use_count
SELECT COUNT(*), AVG(use_count) FROM gmail_reply_examples
WHERE created_at >= ? AND created_at < date(?, '+1 day');
```

### Endpoint: `GET /export/excel`

**Query params:** `from`, `to` (YYYY-MM-DD).

Genera un `.xlsx` con **openpyxl** con 5 hojas:

| Hoja | Contenido |
|---|---|
| Resumen | KPIs: total emails, tasa respuesta, sugerencias IA, borradores, ejemplos |
| Volumen diario | Tabla date → count |
| Por categoría | Una fila por categoría con todas las métricas |
| Top remitentes | Top 10 con email, nombre, cantidad |
| Auto-reply | Detalle de uso del sistema de respuesta automática |

Devuelto como `StreamingResponse` con:
```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="gmail_stats_YYYY-MM-DD_YYYY-MM-DD.xlsx"
```

---

## Frontend

### Ruta

`/gmail-classifier/stats` — nueva página Next.js en `frontend/app/gmail-classifier/stats/page.tsx`.

### Navegación

Agregar link "Estadísticas" en la barra de navegación del plugin (junto al botón de settings existente).

### Layout

```
┌─────────────────────────────────────────────────────────┐
│ [Desde: __________] [Hasta: __________] [Aplicar]       │
│                               [Exportar PDF] [Excel ↓]  │
├─────────────────────────────┬───────────────────────────┤
│  Volumen diario             │  Por categoría            │
│  LineChart (Recharts)       │  BarChart agrupado        │
│  eje X: fecha, Y: emails    │  total/leídos/respondidos │
├──────────────┬──────────────┴───────────────────────────┤
│  Top 10      │  KPI cards (4 en fila)                   │
│  remitentes  │  Total │ Tasa resp │ Suger IA │ Borradores│
│  BarChart    │  342   │   52%     │   45     │   12      │
│  horizontal  │                                          │
├──────────────┴──────────────────────────────────────────┤
│  Auto-reply stats (BarChart simple)                     │
│  Sugerencias / Borradores / Ejemplos / Uso prom.        │
└─────────────────────────────────────────────────────────┘
```

### Biblioteca de charts

**Recharts** (`npm install recharts`). Si ya está instalada, no instalar de nuevo.

### Componentes

- `frontend/app/gmail-classifier/stats/page.tsx` — página principal con estado, fetch, layout
- `frontend/app/gmail-classifier/stats/components/VolumeChart.tsx` — LineChart volumen diario
- `frontend/app/gmail-classifier/stats/components/CategoryChart.tsx` — BarChart por categoría
- `frontend/app/gmail-classifier/stats/components/TopSendersChart.tsx` — BarChart horizontal top remitentes
- `frontend/app/gmail-classifier/stats/components/AutoReplyChart.tsx` — BarChart auto-reply
- `frontend/app/gmail-classifier/stats/components/KpiCards.tsx` — 4 cards de KPIs

### Comportamiento

1. Al cargar → fecha default = hoy − 30 días hasta hoy → fetch automático a `GET /stats`
2. Cambiar fechas + "Aplicar" → re-fetch → charts re-renderizan
3. Loading state: skeleton/spinner mientras carga
4. Error state: mensaje discreto si el fetch falla
5. "Exportar PDF" → `window.print()` — CSS `@media print` oculta nav, botones, header; muestra solo los charts con título y período
6. "Exportar Excel" → GET `/export/excel?from=...&to=...` → browser descarga el archivo automáticamente (usando un `<a>` con `download`)

### CSS de impresión

```css
@media print {
  nav, .no-print { display: none !important; }
  .charts-container { page-break-inside: avoid; }
}
```

---

## Manejo de errores

| Escenario | Comportamiento |
|---|---|
| `from > to` | Frontend valida antes de hacer fetch, muestra error inline |
| No hay emails en el período | Respuesta válida con counts en 0, charts vacíos con mensaje "Sin datos" |
| openpyxl no instalado | Backend retorna 500 con mensaje claro |
| Rango muy amplio (>1 año) | Sin límite — SQLite maneja bien la agregación |

---

## Archivos a crear / modificar

| Archivo | Cambio |
|---|---|
| `plugins/gmail_classifier/router.py` | 2 endpoints nuevos: `GET /stats`, `GET /export/excel` |
| `frontend/app/gmail-classifier/stats/page.tsx` | Nueva página |
| `frontend/app/gmail-classifier/stats/components/VolumeChart.tsx` | Nuevo |
| `frontend/app/gmail-classifier/stats/components/CategoryChart.tsx` | Nuevo |
| `frontend/app/gmail-classifier/stats/components/TopSendersChart.tsx` | Nuevo |
| `frontend/app/gmail-classifier/stats/components/AutoReplyChart.tsx` | Nuevo |
| `frontend/app/gmail-classifier/stats/components/KpiCards.tsx` | Nuevo |
| `frontend/app/gmail-classifier/page.tsx` | Agregar link de navegación a /stats |
