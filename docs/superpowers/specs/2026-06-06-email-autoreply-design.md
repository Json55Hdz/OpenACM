# Email Auto-Reply con Aprendizaje Semántico — Spec de Diseño

**Fecha:** 2026-06-06  
**Plugin:** `gmail_classifier`  
**Estado:** Aprobado

---

## Resumen

Sistema de sugerencia automática de respuestas para el clasificador de Gmail. Cuando el usuario abre un correo elegible, el LLM genera una respuesta sugerida pre-cargada en el composer. El sistema aprende de cada correo que el usuario envía o guarda como borrador, usando RAG semántico (embeddings + cosine similarity) para mejorar las sugerencias futuras de correos similares dentro de la misma categoría.

---

## Reglas de elegibilidad

Un correo solo recibe sugerencia automática si cumple **todas** las condiciones:

| Condición | Resultado si no cumple |
|---|---|
| La categoría del correo tiene auto-reply activo | No sugerir |
| `is_replied = 0` | No sugerir |
| `thread_last_sender_email` ≠ email autenticado del usuario | No sugerir (el usuario ya respondió en el hilo) |
| `sender_email` no coincide con patrón noreply (case-insensitive) | No sugerir |
| No existe entrada en `gmail_reply_drafts` para este correo | Cargar borrador existente, no regenerar |

**Patrones noreply detectados:** `noreply@`, `no-reply@`, `donotreply@`, `notifications@`, `mailer-daemon@`, `bounce@`

---

## Modelo de datos

### Tabla nueva: `gmail_reply_drafts`

Rastrea el borrador de Gmail guardado por correo.

```sql
CREATE TABLE gmail_reply_drafts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id       INTEGER NOT NULL UNIQUE REFERENCES gmail_emails(id),
    gmail_draft_id TEXT    NOT NULL DEFAULT '',
    draft_body     TEXT    NOT NULL DEFAULT '',
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Tabla nueva: `gmail_reply_examples`

Almacena los ejemplos aprendidos con embedding para búsqueda semántica.

```sql
CREATE TABLE gmail_reply_examples (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id         INTEGER NOT NULL REFERENCES gmail_categories(id),
    subtype_label       TEXT    NOT NULL DEFAULT '',
    email_context       TEXT    NOT NULL DEFAULT '',
    original_suggestion TEXT    NOT NULL DEFAULT '',
    final_response      TEXT    NOT NULL DEFAULT '',
    embedding           BLOB,
    use_count           INTEGER NOT NULL DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reply_examples_category ON gmail_reply_examples(category_id);
```

### Columnas nuevas en `gmail_emails`

```sql
ALTER TABLE gmail_emails ADD COLUMN thread_last_sender_email TEXT NOT NULL DEFAULT '';
ALTER TABLE gmail_emails ADD COLUMN ai_suggestion            TEXT NOT NULL DEFAULT '';
```

- `thread_last_sender_email`: el processor la actualiza en cada sync con el email del remitente del último mensaje del hilo.
- `ai_suggestion`: `AutoReplyGenerator` la persiste cuando genera una sugerencia. `ReplyLearningManager` la lee para comparar con `final_body` sin depender del frontend.

### Settings nuevas (`gmail_classifier_settings`)

| Key | Tipo | Default | Descripción |
|---|---|---|---|
| `autoreply_enabled_categories` | JSON array | `[]` | IDs de categorías con auto-reply activo |
| `autoreply_model` | string | `''` | Modelo LLM para sugerencias (vacío = usar el del sistema) |

---

## Arquitectura backend

### Módulo nuevo: `auto_reply.py` — `AutoReplyGenerator`

Responsabilidad única: generar una sugerencia de respuesta para un correo dado.

**Flujo:**
1. Evaluar reglas de elegibilidad — retornar `None` si no aplica
2. Si existe borrador en `gmail_reply_drafts` → retornar `draft_body` directamente (sin LLM)
3. Generar embedding del `body_text` del correo entrante
4. Buscar top-3 ejemplos más similares en `gmail_reply_examples` para la misma `category_id` (cosine similarity sobre embeddings)
5. Construir prompt: descripción de categoría + subtipo detectado + ejemplos few-shot + correo completo
6. Llamar al LLM → retornar texto plano de la sugerencia

### Módulo nuevo: `reply_learning.py` — `ReplyLearningManager`

Responsabilidad única: aprender de la acción del usuario al enviar o guardar borrador.

**Flujo:**
1. Recibe `email_id`, `final_body`, `suggestion_body` (puede ser vacío si no hubo sugerencia)
2. Si `suggestion_body` no es vacío: comparar con `final_body` (diff básico de similitud)
   - Si el usuario **modificó**: llamar al LLM para extraer `subtype_label`, generar embedding del `email_context`, guardar nuevo ejemplo en `gmail_reply_examples`
   - Si el usuario **no modificó**: incrementar `use_count` en los ejemplos que se usaron como few-shot
3. Si no hubo sugerencia (categoría sin toggle aún): guardar igual como aprendizaje pasivo para el futuro
4. Guardar idempotente por `email_id` — si ya fue procesado, no duplicar

### Endpoints nuevos en `router.py`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/emails/{id}/suggest-reply` | Genera sugerencia respetando reglas de elegibilidad |
| `POST` | `/emails/{id}/draft` | Guarda borrador en Gmail + dispara aprendizaje |
| `DELETE` | `/emails/{id}/draft` | Elimina borrador de Gmail |
| `GET` | `/reply-examples` | Lista ejemplos (`?category_id=` opcional) |
| `PUT` | `/reply-examples/{id}` | Edita un ejemplo (final_response, subtype_label) |
| `DELETE` | `/reply-examples/{id}` | Elimina un ejemplo |

El endpoint existente `POST /emails/{id}/reply` se extiende para también disparar `ReplyLearningManager` al enviar.

---

## Frontend

### `EmailDetail.tsx` — comportamiento al abrir un correo

1. Si la categoría tiene auto-reply activo: mostrar spinner **"Generando respuesta..."** en el área del composer (timeout: 30s)
2. Al recibir sugerencia: pre-llenar textarea con badge **"Sugerencia IA ✦"**, mostrar dos botones:
   - **Guardar como borrador** → `POST /emails/{id}/draft`
   - **Enviar** → `POST /emails/{id}/reply` (ya existe)
3. Si ya existe un borrador: mostrar indicador **"Borrador guardado"**, cargar `draft_body` sin llamar al LLM
4. Si el correo no es elegible: composer aparece vacío normal, sin spinner ni badge
5. Si falla la generación (timeout 30s o error): composer vacío con mensaje discreto "No se pudo generar sugerencia"

### `PluginSettings.tsx` — nueva pestaña "Auto-respuesta"

**Subsección 1 — Activación por categoría:**
- Lista todas las categorías con toggle (off por defecto)
- Al activar: actualiza `autoreply_enabled_categories` en settings

**Subsección 2 — Ejemplos aprendidos:**
- Tabla: categoría | subtipo | fragmento del correo | respuesta final | usos | acciones
- Filtrable por categoría
- Acciones por fila: editar (inline) / eliminar
- Al editar: permite corregir `final_response` y `subtype_label`

---

## Manejo de errores

| Escenario | Comportamiento |
|---|---|
| LLM tarda más de 30s o falla | Composer vacío, toast discreto "No se pudo generar sugerencia" |
| Gmail Drafts API falla | Toast de error, NO fallback local (evita estado divergente) |
| `body_text` insuficiente para embedding | Se omite búsqueda de ejemplos, LLM genera con solo contexto de categoría |
| Aprendizaje duplicado (borrador + envío) | `ReplyLearningManager` es idempotente por `email_id` |
| Embedding corrupto en un ejemplo | Se ignora silenciosamente en la búsqueda semántica |
| Usuario respondió desde Gmail directamente | Próximo sync actualiza `thread_last_sender_email` correctamente |

---

## Testing

### Unit tests

- `AutoReplyGenerator`: mock LLM + embeddings, verificar que cada regla de elegibilidad bloquea correctamente
- `ReplyLearningManager`: guarda ejemplo con diff, incrementa use_count sin diff, idempotente por email_id
- Detección noreply: `noreply@x.com`, `no-reply@x.com`, `NOREPLY@X.COM`, `notifications@github.com`

### Integration tests

- Flujo completo: email entra → suggest-reply → usuario edita → draft → ejemplo en DB con embedding
- Flujo "ya tiene borrador": segundo llamado retorna draft sin llamar al LLM

---

## Archivos a crear / modificar

| Archivo | Cambio |
|---|---|
| `plugins/gmail_classifier/auto_reply.py` | Nuevo — `AutoReplyGenerator` |
| `plugins/gmail_classifier/reply_learning.py` | Nuevo — `ReplyLearningManager` |
| `plugins/gmail_classifier/router.py` | 6 endpoints nuevos, extensión de `/reply` |
| `plugins/gmail_classifier/__init__.py` | Migración DB (2 tablas + 1 columna), registro de módulos |
| `storage/database.py` | Migraciones 24, 25 |
| `frontend/app/gmail-classifier/components/EmailDetail.tsx` | Spinner, badge IA, botón borrador, lógica de elegibilidad |
| `frontend/app/gmail-classifier/components/PluginSettings.tsx` | Pestaña Auto-respuesta con toggles y tabla de ejemplos |
| `tests/unit/test_auto_reply.py` | Nuevo |
| `tests/unit/test_reply_learning.py` | Nuevo |
| `tests/integration/test_autoreply_flow.py` | Nuevo |
