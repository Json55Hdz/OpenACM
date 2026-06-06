# Gmail Classifier — Estadísticas y Exportación — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una página de estadísticas al plugin Gmail Classifier con charts por rango de fechas y exportación a PDF y Excel.

**Architecture:** Backend — dos endpoints nuevos en `router.py` que delegan la computación a `stats.py` (agregaciones SQL) y `excel_export.py` (generación XLSX con openpyxl). Frontend — página `/gmail-classifier/stats` con `react-chartjs-2` (ya instalado), date picker, y descarga de Excel via fetch+blob.

**Tech Stack:** Python/FastAPI, aiosqlite, openpyxl, Next.js 14, react-chartjs-2, chart.js, Tailwind CSS.

---

## Estructura de archivos

| Archivo | Acción |
|---|---|
| `src/openacm/plugins/gmail_classifier/stats.py` | Crear — función `compute_stats(db, from_date, to_date)` |
| `src/openacm/plugins/gmail_classifier/excel_export.py` | Crear — función `generate_excel(stats, from_date, to_date)` |
| `src/openacm/plugins/gmail_classifier/router.py` | Modificar — agregar `GET /stats` y `GET /export/excel` |
| `tests/unit/test_gmail_stats.py` | Crear — tests para `compute_stats` |
| `tests/unit/test_gmail_excel.py` | Crear — tests para `generate_excel` |
| `frontend/app/gmail-classifier/stats/page.tsx` | Crear — página principal |
| `frontend/app/gmail-classifier/stats/components/KpiCards.tsx` | Crear |
| `frontend/app/gmail-classifier/stats/components/VolumeChart.tsx` | Crear |
| `frontend/app/gmail-classifier/stats/components/CategoryChart.tsx` | Crear |
| `frontend/app/gmail-classifier/stats/components/TopSendersChart.tsx` | Crear |
| `frontend/app/gmail-classifier/stats/components/AutoReplyChart.tsx` | Crear |
| `frontend/app/gmail-classifier/page.tsx` | Modificar — link de navegación a /stats |
| `pyproject.toml` | Modificar — agregar `openpyxl` como dependencia |

---

### Task 1: Backend — `stats.py` + `GET /stats` endpoint

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/stats.py`
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Create: `tests/unit/test_gmail_stats.py`

- [ ] **Step 1: Agregar `openpyxl` a pyproject.toml**

Busca la sección `[project] dependencies` en `pyproject.toml` y agrega `"openpyxl>=3.1"`.

- [ ] **Step 2: Instalar dependencia**

```bash
uv pip install -e ".[dev]"
```

- [ ] **Step 3: Crear `stats.py`**

```python
# src/openacm/plugins/gmail_classifier/stats.py
"""Async SQL aggregations for the Gmail Classifier stats endpoint."""
from __future__ import annotations
from typing import Any


async def compute_stats(db: Any, from_date: str, to_date: str) -> dict:
    """Return aggregated email stats for the inclusive date range [from_date, to_date]."""
    p = (from_date, to_date)

    # Total emails in period
    cur = await db._db.execute(
        "SELECT COUNT(*) FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day')", p
    )
    total = (await cur.fetchone())[0]

    # Volume by day
    cur = await db._db.execute(
        "SELECT date(received_at) as d, COUNT(*) as c FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day') "
        "GROUP BY d ORDER BY d", p
    )
    volume_by_day = [{"date": r[0], "count": r[1]} for r in await cur.fetchall()]

    # By category
    cur = await db._db.execute(
        "SELECT c.id, c.name, c.color, "
        "COUNT(e.id) as total, "
        "SUM(CASE WHEN e.is_read=1 THEN 1 ELSE 0 END) as read_count, "
        "SUM(CASE WHEN e.is_replied=1 THEN 1 ELSE 0 END) as replied, "
        "SUM(CASE WHEN e.ai_classified=1 THEN 1 ELSE 0 END) as ai_classified "
        "FROM gmail_categories c "
        "LEFT JOIN gmail_emails e ON e.category_id = c.id "
        "  AND e.received_at >= ? AND e.received_at < date(?, '+1 day') "
        "GROUP BY c.id ORDER BY total DESC",
        p,
    )
    by_category = [
        {
            "id": r[0], "name": r[1], "color": r[2],
            "total": r[3] or 0, "read": r[4] or 0,
            "replied": r[5] or 0, "ai_classified": r[6] or 0,
        }
        for r in await cur.fetchall()
    ]

    # Top 10 senders
    cur = await db._db.execute(
        "SELECT sender_email, sender_name, COUNT(*) as c FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day') "
        "GROUP BY sender_email ORDER BY c DESC LIMIT 10", p
    )
    top_senders = [{"email": r[0], "name": r[1] or "", "count": r[2]} for r in await cur.fetchall()]

    # Reply rate
    cur = await db._db.execute(
        "SELECT COUNT(*), SUM(is_replied) FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day')", p
    )
    rr = await cur.fetchone()
    replied_count = rr[1] or 0
    reply_rate = round(replied_count / total, 3) if total else 0.0

    # Autoreply: suggestions generated
    cur = await db._db.execute(
        "SELECT COUNT(*) FROM gmail_emails "
        "WHERE ai_suggestion != '' AND received_at >= ? AND received_at < date(?, '+1 day')", p
    )
    suggestions = (await cur.fetchone())[0]

    # Autoreply: drafts saved
    cur = await db._db.execute(
        "SELECT COUNT(*) FROM gmail_reply_drafts "
        "WHERE created_at >= ? AND created_at < date(?, '+1 day')", p
    )
    drafts = (await cur.fetchone())[0]

    # Autoreply: examples learned + avg use_count
    cur = await db._db.execute(
        "SELECT COUNT(*), COALESCE(AVG(use_count), 0.0) FROM gmail_reply_examples "
        "WHERE created_at >= ? AND created_at < date(?, '+1 day')", p
    )
    ex = await cur.fetchone()

    return {
        "period": {"from": from_date, "to": to_date, "total_emails": total},
        "volume_by_day": volume_by_day,
        "by_category": by_category,
        "top_senders": top_senders,
        "reply_rate": {"total": total, "replied": replied_count, "rate": reply_rate},
        "autoreply": {
            "suggestions_generated": suggestions,
            "drafts_saved": drafts,
            "examples_learned": ex[0],
            "avg_use_count": round(ex[1], 2),
        },
    }
```

- [ ] **Step 4: Escribir tests que fallan**

```python
# tests/unit/test_gmail_stats.py
"""Unit tests for gmail_classifier stats aggregation."""
import pytest
from openacm.plugins.gmail_classifier.stats import compute_stats
from openacm.storage.database import Database


@pytest.fixture
async def db():
    d = Database(path=":memory:")
    await d.connect()
    yield d
    await d.close()


async def _seed(db, emails):
    """Insert minimal email rows. emails = list of dicts."""
    for e in emails:
        await db._db.execute(
            "INSERT INTO gmail_emails "
            "(gmail_id, subject, sender_email, sender_name, body_text, category_id, "
            "is_read, is_replied, ai_classified, received_at, ai_suggestion) "
            "VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)",
            (
                e["gmail_id"], e.get("subject", "S"), e.get("sender_email", "a@b.com"),
                e.get("sender_name", "A"), e.get("category_id", 1),
                e.get("is_read", 0), e.get("is_replied", 0), e.get("ai_classified", 0),
                e.get("received_at", "2026-06-05 10:00:00"),
                e.get("ai_suggestion", ""),
            ),
        )
    await db._db.commit()


async def test_total_emails_in_range(db):
    """Only emails within the date range are counted."""
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('X', '#fff')")
    await _seed(db, [
        {"gmail_id": "m1", "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m2", "received_at": "2026-06-10 10:00:00"},
        {"gmail_id": "m3", "received_at": "2026-05-01 10:00:00"},  # outside range
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert result["period"]["total_emails"] == 2


async def test_volume_by_day_groups_correctly(db):
    """Emails on the same day are grouped into one entry."""
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('X', '#fff')")
    await _seed(db, [
        {"gmail_id": "m1", "received_at": "2026-06-05 08:00:00"},
        {"gmail_id": "m2", "received_at": "2026-06-05 17:00:00"},
        {"gmail_id": "m3", "received_at": "2026-06-06 10:00:00"},
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert len(result["volume_by_day"]) == 2
    assert result["volume_by_day"][0] == {"date": "2026-06-05", "count": 2}
    assert result["volume_by_day"][1] == {"date": "2026-06-06", "count": 1}


async def test_reply_rate(db):
    """reply_rate.rate = replied / total."""
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('X', '#fff')")
    await _seed(db, [
        {"gmail_id": "m1", "is_replied": 1, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m2", "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m3", "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m4", "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert result["reply_rate"]["replied"] == 1
    assert result["reply_rate"]["total"] == 4
    assert result["reply_rate"]["rate"] == 0.25


async def test_by_category_counts(db):
    """by_category totals match seeded emails per category."""
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('Trabajo', '#f00')")
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('Spam', '#0f0')")
    await _seed(db, [
        {"gmail_id": "m1", "category_id": 1, "is_read": 1, "is_replied": 1, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m2", "category_id": 1, "is_read": 0, "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m3", "category_id": 2, "is_read": 1, "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    trabajo = next(c for c in result["by_category"] if c["name"] == "Trabajo")
    spam = next(c for c in result["by_category"] if c["name"] == "Spam")
    assert trabajo["total"] == 2
    assert trabajo["read"] == 1
    assert trabajo["replied"] == 1
    assert spam["total"] == 1
    assert spam["replied"] == 0


async def test_top_senders_limited_to_10(db):
    """top_senders never returns more than 10 entries."""
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('X', '#fff')")
    for i in range(15):
        await _seed(db, [{"gmail_id": f"m{i}", "sender_email": f"sender{i}@x.com", "received_at": "2026-06-05 10:00:00"}])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert len(result["top_senders"]) == 10


async def test_empty_period_returns_zeros(db):
    """Period with no emails returns zeros, not errors."""
    await db._db.execute("INSERT INTO gmail_categories (name, color) VALUES ('X', '#fff')")
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert result["period"]["total_emails"] == 0
    assert result["reply_rate"]["rate"] == 0.0
    assert result["volume_by_day"] == []
    assert result["autoreply"]["suggestions_generated"] == 0
```

- [ ] **Step 5: Verificar que los tests fallan**

```bash
uv run pytest tests/unit/test_gmail_stats.py -v
```

Expected: todos FAIL con `ModuleNotFoundError` o `ImportError`.

- [ ] **Step 6: Agregar endpoint `GET /stats` en `router.py`**

Busca la sección de endpoints en `router.py` (después del último endpoint existente, antes del cierre del archivo) y agrega:

```python
# ─── Stats ───────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(from_date: str, to_date: str):
    """Return aggregated email stats for the given inclusive date range."""
    db = _require_db()
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")
    from openacm.plugins.gmail_classifier.stats import compute_stats
    return await compute_stats(db, from_date, to_date)
```

- [ ] **Step 7: Verificar que los tests pasan**

```bash
uv run pytest tests/unit/test_gmail_stats.py -v
```

Expected: todos PASS.

- [ ] **Step 8: Suite completa**

```bash
uv run pytest tests/ --tb=short -q
```

Expected: todos PASS.

- [ ] **Step 9: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/stats.py \
        src/openacm/plugins/gmail_classifier/router.py \
        tests/unit/test_gmail_stats.py \
        pyproject.toml
git commit -m "feat: GET /stats endpoint with SQL aggregations"
```

---

### Task 2: Backend — `excel_export.py` + `GET /export/excel`

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/excel_export.py`
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Create: `tests/unit/test_gmail_excel.py`

- [ ] **Step 1: Crear `excel_export.py`**

```python
# src/openacm/plugins/gmail_classifier/excel_export.py
"""Generate Excel report for Gmail Classifier stats."""
from __future__ import annotations
from io import BytesIO
from typing import Any

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment


def _header_style(ws, row: int, cols: int) -> None:
    """Bold + light-gray fill for header row."""
    fill = PatternFill("solid", fgColor="D9D9D9")
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")


def generate_excel(stats: dict[str, Any], from_date: str, to_date: str) -> BytesIO:
    """Return a BytesIO containing the .xlsx report."""
    wb = openpyxl.Workbook()

    # ── Sheet 1: Resumen ──────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Resumen"
    ws1.column_dimensions["A"].width = 32
    ws1.column_dimensions["B"].width = 18
    ws1.append([f"Reporte Gmail Classifier — {from_date} → {to_date}"])
    ws1.cell(1, 1).font = Font(bold=True, size=13)
    ws1.append([])
    ws1.append(["Métrica", "Valor"])
    _header_style(ws1, 3, 2)
    rows = [
        ("Total emails recibidos",           stats["period"]["total_emails"]),
        ("Total respondidos",                stats["reply_rate"]["replied"]),
        ("Tasa de respuesta",                f"{stats['reply_rate']['rate'] * 100:.1f}%"),
        ("Sugerencias IA generadas",         stats["autoreply"]["suggestions_generated"]),
        ("Borradores guardados",             stats["autoreply"]["drafts_saved"]),
        ("Ejemplos aprendidos",              stats["autoreply"]["examples_learned"]),
        ("Uso promedio por ejemplo",         stats["autoreply"]["avg_use_count"]),
    ]
    for r in rows:
        ws1.append(list(r))

    # ── Sheet 2: Volumen diario ───────────────────────────────────────────
    ws2 = wb.create_sheet("Volumen diario")
    ws2.column_dimensions["A"].width = 14
    ws2.column_dimensions["B"].width = 20
    ws2.append(["Fecha", "Emails recibidos"])
    _header_style(ws2, 1, 2)
    for row in stats["volume_by_day"]:
        ws2.append([row["date"], row["count"]])

    # ── Sheet 3: Por categoría ────────────────────────────────────────────
    ws3 = wb.create_sheet("Por categoría")
    for col, width in zip("ABCDE", [20, 10, 12, 16, 20]):
        ws3.column_dimensions[col].width = width
    ws3.append(["Categoría", "Total", "Leídos", "Respondidos", "Clasificados por IA"])
    _header_style(ws3, 1, 5)
    for cat in stats["by_category"]:
        ws3.append([cat["name"], cat["total"], cat["read"], cat["replied"], cat["ai_classified"]])

    # ── Sheet 4: Top remitentes ───────────────────────────────────────────
    ws4 = wb.create_sheet("Top remitentes")
    ws4.column_dimensions["A"].width = 30
    ws4.column_dimensions["B"].width = 20
    ws4.column_dimensions["C"].width = 18
    ws4.append(["Email", "Nombre", "Emails enviados"])
    _header_style(ws4, 1, 3)
    for s in stats["top_senders"]:
        ws4.append([s["email"], s["name"], s["count"]])

    # ── Sheet 5: Auto-reply ───────────────────────────────────────────────
    ws5 = wb.create_sheet("Auto-reply")
    ws5.column_dimensions["A"].width = 32
    ws5.column_dimensions["B"].width = 18
    ws5.append(["Métrica", "Valor"])
    _header_style(ws5, 1, 2)
    ar = stats["autoreply"]
    ws5.append(["Sugerencias generadas",    ar["suggestions_generated"]])
    ws5.append(["Borradores guardados",      ar["drafts_saved"]])
    ws5.append(["Ejemplos aprendidos",       ar["examples_learned"]])
    ws5.append(["Uso promedio por ejemplo",  ar["avg_use_count"]])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
```

- [ ] **Step 2: Escribir tests**

```python
# tests/unit/test_gmail_excel.py
"""Unit tests for Excel report generation."""
import openpyxl
import pytest
from openacm.plugins.gmail_classifier.excel_export import generate_excel

SAMPLE_STATS = {
    "period": {"from": "2026-06-01", "to": "2026-06-30", "total_emails": 10},
    "volume_by_day": [
        {"date": "2026-06-01", "count": 4},
        {"date": "2026-06-02", "count": 6},
    ],
    "by_category": [
        {"id": 1, "name": "Trabajo", "color": "#f00",
         "total": 7, "read": 6, "replied": 3, "ai_classified": 7},
        {"id": 2, "name": "Spam", "color": "#0f0",
         "total": 3, "read": 3, "replied": 0, "ai_classified": 3},
    ],
    "top_senders": [
        {"email": "boss@co.com", "name": "Jefe", "count": 5},
        {"email": "other@co.com", "name": "Otro", "count": 3},
    ],
    "reply_rate": {"total": 10, "replied": 3, "rate": 0.3},
    "autoreply": {
        "suggestions_generated": 8,
        "drafts_saved": 2,
        "examples_learned": 3,
        "avg_use_count": 1.5,
    },
}


def test_workbook_has_five_sheets():
    buf = generate_excel(SAMPLE_STATS, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(buf)
    assert set(wb.sheetnames) == {"Resumen", "Volumen diario", "Por categoría", "Top remitentes", "Auto-reply"}


def test_resumen_sheet_contains_total_emails():
    buf = generate_excel(SAMPLE_STATS, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(buf)
    ws = wb["Resumen"]
    values = [ws.cell(r, 2).value for r in range(1, ws.max_row + 1)]
    assert 10 in values  # total_emails


def test_volumen_diario_has_correct_rows():
    buf = generate_excel(SAMPLE_STATS, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(buf)
    ws = wb["Volumen diario"]
    assert ws.cell(2, 1).value == "2026-06-01"
    assert ws.cell(2, 2).value == 4
    assert ws.cell(3, 1).value == "2026-06-02"
    assert ws.cell(3, 2).value == 6


def test_por_categoria_has_correct_rows():
    buf = generate_excel(SAMPLE_STATS, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(buf)
    ws = wb["Por categoría"]
    assert ws.cell(2, 1).value == "Trabajo"
    assert ws.cell(2, 2).value == 7
    assert ws.cell(3, 1).value == "Spam"


def test_top_remitentes_has_correct_rows():
    buf = generate_excel(SAMPLE_STATS, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(buf)
    ws = wb["Top remitentes"]
    assert ws.cell(2, 1).value == "boss@co.com"
    assert ws.cell(2, 3).value == 5


def test_autoreply_sheet_values():
    buf = generate_excel(SAMPLE_STATS, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(buf)
    ws = wb["Auto-reply"]
    values = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(2, ws.max_row + 1)}
    assert values["Sugerencias generadas"] == 8
    assert values["Borradores guardados"] == 2
    assert values["Ejemplos aprendidos"] == 3
```

- [ ] **Step 3: Verificar que los tests fallan**

```bash
uv run pytest tests/unit/test_gmail_excel.py -v
```

Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 4: Agregar endpoint `GET /export/excel` en `router.py`**

Agrega después de `GET /stats`:

```python
@router.get("/export/excel")
async def export_excel(from_date: str, to_date: str):
    """Generate and return an Excel report for the given date range."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    db = _require_db()
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")
    try:
        from openacm.plugins.gmail_classifier.stats import compute_stats
        from openacm.plugins.gmail_classifier.excel_export import generate_excel
        stats = await compute_stats(db, from_date, to_date)
        buf = generate_excel(stats, from_date, to_date)
        filename = f"gmail_stats_{from_date}_{to_date}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed — run: uv pip install openpyxl")
```

- [ ] **Step 5: Verificar tests**

```bash
uv run pytest tests/unit/test_gmail_excel.py tests/unit/test_gmail_stats.py -v
```

Expected: todos PASS.

- [ ] **Step 6: Suite completa**

```bash
uv run pytest tests/ --tb=short -q
```

Expected: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/excel_export.py \
        src/openacm/plugins/gmail_classifier/router.py \
        tests/unit/test_gmail_excel.py
git commit -m "feat: GET /export/excel — XLSX con 5 hojas via openpyxl"
```

---

### Task 3: Frontend — Stats page skeleton + navegación

**Files:**
- Create: `frontend/app/gmail-classifier/stats/page.tsx`
- Modify: `frontend/app/gmail-classifier/page.tsx`

- [ ] **Step 1: Agregar link de navegación en `page.tsx`**

Lee `frontend/app/gmail-classifier/page.tsx`. Busca el botón de Settings (tiene `<Settings size={13} />`). Agrega un botón "Estadísticas" justo antes de él. Necesita importar `BarChart3` de lucide-react y `Link` de next/link.

Agrega a los imports:
```typescript
import Link from 'next/link';
// Agrega BarChart3 a los imports de lucide-react existentes
import { ..., BarChart3 } from 'lucide-react';
```

El botón nuevo (antes del botón Settings):
```tsx
<Link
  href="/gmail-classifier/stats"
  className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
  title="Estadísticas"
>
  <BarChart3 size={13} />
</Link>
```

- [ ] **Step 2: Definir el tipo `StatsData`**

Crea `frontend/app/gmail-classifier/stats/page.tsx` con el tipo y el esqueleto de la página:

```typescript
'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { ArrowLeft, Download, Printer } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { AppLayout } from '@/components/layout/app-layout';

const API = '/api/gmail-classifier';

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export type StatsData = {
  period: { from: string; to: string; total_emails: number };
  volume_by_day: { date: string; count: number }[];
  by_category: {
    id: number; name: string; color: string;
    total: number; read: number; replied: number; ai_classified: number;
  }[];
  top_senders: { email: string; name: string; count: number }[];
  reply_rate: { total: number; replied: number; rate: number };
  autoreply: {
    suggestions_generated: number;
    drafts_saved: number;
    examples_learned: number;
    avg_use_count: number;
  };
};

export default function StatsPage() {
  const token = useAuthStore(s => s.token);

  const today = new Date();
  const [fromDate, setFromDate] = useState(
    toDateStr(new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000))
  );
  const [toDate, setToDate] = useState(toDateStr(today));
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    if (fromDate > toDate) {
      setError('La fecha de inicio debe ser anterior o igual a la de fin');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/stats?from_date=${fromDate}&to_date=${toDate}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Error del servidor');
      setStats(await res.json());
    } catch {
      setError('No se pudieron cargar las estadísticas. Intenta de nuevo.');
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, token]);

  useEffect(() => { fetchStats(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleExcelDownload = async () => {
    try {
      const res = await fetch(
        `${API}/export/excel?from_date=${fromDate}&to_date=${toDate}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `gmail_stats_${fromDate}_${toDate}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      alert('Error al generar el Excel. Intenta de nuevo.');
    }
  };

  return (
    <AppLayout>
      <div className="p-6 max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 no-print">
          <div className="flex items-center gap-3">
            <Link href="/gmail-classifier" className="text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)]">
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-lg font-semibold">Estadísticas Gmail</h1>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="text-sm border border-[var(--acm-border)] rounded px-2 py-1 bg-[var(--acm-bg)] text-[var(--acm-fg)]"
            />
            <span className="text-[var(--acm-fg-3)] text-sm">→</span>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              className="text-sm border border-[var(--acm-border)] rounded px-2 py-1 bg-[var(--acm-bg)] text-[var(--acm-fg)]"
            />
            <button onClick={fetchStats} className="btn-secondary text-[12px] py-[7px] px-3">
              Aplicar
            </button>
            <button
              onClick={() => window.print()}
              className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
            >
              <Printer size={13} /> PDF
            </button>
            <button
              onClick={handleExcelDownload}
              className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
            >
              <Download size={13} /> Excel
            </button>
          </div>
        </div>

        {/* States */}
        {error && (
          <div className="text-sm text-red-500 mb-4">{error}</div>
        )}
        {loading && (
          <div className="flex items-center justify-center py-20 text-[var(--acm-fg-3)]">
            <div className="h-5 w-5 rounded-full border-2 border-current border-t-transparent animate-spin mr-3" />
            Cargando estadísticas...
          </div>
        )}
        {!loading && !stats && !error && (
          <div className="text-center py-20 text-[var(--acm-fg-3)] text-sm">
            Selecciona un rango y haz clic en Aplicar.
          </div>
        )}

        {/* Charts — placeholder until Task 4 */}
        {!loading && stats && (
          <div className="charts-container space-y-6">
            <p className="text-sm text-[var(--acm-fg-3)]">
              {stats.period.total_emails} emails del {stats.period.from} al {stats.period.to}
            </p>
            {/* Chart components go here in Task 4 */}
          </div>
        )}
      </div>

      <style jsx global>{`
        @media print {
          .no-print { display: none !important; }
          .charts-container { page-break-inside: avoid; }
          body { background: white !important; }
        }
      `}</style>
    </AppLayout>
  );
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: sin errores.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/gmail-classifier/stats/page.tsx \
        frontend/app/gmail-classifier/page.tsx
git commit -m "feat: stats page skeleton + navigation link"
```

---

### Task 4: Frontend — Componentes de charts

**Files:**
- Create: `frontend/app/gmail-classifier/stats/components/KpiCards.tsx`
- Create: `frontend/app/gmail-classifier/stats/components/VolumeChart.tsx`
- Create: `frontend/app/gmail-classifier/stats/components/CategoryChart.tsx`
- Create: `frontend/app/gmail-classifier/stats/components/TopSendersChart.tsx`
- Create: `frontend/app/gmail-classifier/stats/components/AutoReplyChart.tsx`
- Modify: `frontend/app/gmail-classifier/stats/page.tsx`

**Nota:** `react-chartjs-2` y `chart.js` ya están en `package.json`. No instalar nada.

- [ ] **Step 1: Crear `KpiCards.tsx`**

```typescript
// frontend/app/gmail-classifier/stats/components/KpiCards.tsx
'use client';
import type { StatsData } from '../page';

export function KpiCards({ stats }: { stats: StatsData }) {
  const cards = [
    { label: 'Total emails', value: stats.period.total_emails },
    { label: 'Tasa de respuesta', value: `${(stats.reply_rate.rate * 100).toFixed(1)}%` },
    { label: 'Sugerencias IA', value: stats.autoreply.suggestions_generated },
    { label: 'Borradores', value: stats.autoreply.drafts_saved },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map(c => (
        <div key={c.label} className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 text-center">
          <div className="text-2xl font-bold text-[var(--acm-fg)]">{c.value}</div>
          <div className="text-xs text-[var(--acm-fg-3)] mt-1">{c.label}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Crear `VolumeChart.tsx`**

```typescript
// frontend/app/gmail-classifier/stats/components/VolumeChart.tsx
'use client';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  PointElement, LineElement, Title, Tooltip, Legend, Filler,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export function VolumeChart({ data }: { data: StatsData['volume_by_day'] }) {
  const chartData = {
    labels: data.map(d => d.date),
    datasets: [{
      label: 'Emails recibidos',
      data: data.map(d => d.count),
      borderColor: 'rgb(99, 102, 241)',
      backgroundColor: 'rgba(99, 102, 241, 0.1)',
      fill: true,
      tension: 0.3,
    }],
  };
  const options = {
    responsive: true,
    plugins: { legend: { display: false }, title: { display: true, text: 'Volumen diario' } },
    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  if (data.length === 0) return <EmptyChart title="Volumen diario" />;
  return <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4"><Line data={chartData} options={options} /></div>;
}

function EmptyChart({ title }: { title: string }) {
  return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center h-40 text-[var(--acm-fg-3)] text-sm">
      {title} — sin datos
    </div>
  );
}
```

- [ ] **Step 3: Crear `CategoryChart.tsx`**

```typescript
// frontend/app/gmail-classifier/stats/components/CategoryChart.tsx
'use client';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  BarElement, Title, Tooltip, Legend,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export function CategoryChart({ data }: { data: StatsData['by_category'] }) {
  const filtered = data.filter(c => c.total > 0);
  if (filtered.length === 0) return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center h-40 text-[var(--acm-fg-3)] text-sm">
      Por categoría — sin datos
    </div>
  );
  const chartData = {
    labels: filtered.map(c => c.name),
    datasets: [
      { label: 'Total', data: filtered.map(c => c.total), backgroundColor: 'rgba(99,102,241,0.7)' },
      { label: 'Leídos', data: filtered.map(c => c.read), backgroundColor: 'rgba(34,197,94,0.7)' },
      { label: 'Respondidos', data: filtered.map(c => c.replied), backgroundColor: 'rgba(251,191,36,0.7)' },
    ],
  };
  const options = {
    responsive: true,
    plugins: { title: { display: true, text: 'Por categoría' } },
    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4"><Bar data={chartData} options={options} /></div>;
}
```

- [ ] **Step 4: Crear `TopSendersChart.tsx`**

```typescript
// frontend/app/gmail-classifier/stats/components/TopSendersChart.tsx
'use client';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  BarElement, Title, Tooltip, Legend,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export function TopSendersChart({ data }: { data: StatsData['top_senders'] }) {
  if (data.length === 0) return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center h-40 text-[var(--acm-fg-3)] text-sm">
      Top remitentes — sin datos
    </div>
  );
  const chartData = {
    labels: data.map(s => s.name || s.email),
    datasets: [{
      label: 'Emails enviados',
      data: data.map(s => s.count),
      backgroundColor: 'rgba(168,85,247,0.7)',
    }],
  };
  const options = {
    indexAxis: 'y' as const,
    responsive: true,
    plugins: { legend: { display: false }, title: { display: true, text: 'Top 10 remitentes' } },
    scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4"><Bar data={chartData} options={options} /></div>;
}
```

- [ ] **Step 5: Crear `AutoReplyChart.tsx`**

```typescript
// frontend/app/gmail-classifier/stats/components/AutoReplyChart.tsx
'use client';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  BarElement, Title, Tooltip, Legend,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export function AutoReplyChart({ data }: { data: StatsData['autoreply'] }) {
  const chartData = {
    labels: ['Sugerencias IA', 'Borradores', 'Ejemplos aprendidos'],
    datasets: [{
      label: 'Cantidad',
      data: [data.suggestions_generated, data.drafts_saved, data.examples_learned],
      backgroundColor: [
        'rgba(99,102,241,0.7)',
        'rgba(34,197,94,0.7)',
        'rgba(251,191,36,0.7)',
      ],
    }],
  };
  const options = {
    responsive: true,
    plugins: { legend: { display: false }, title: { display: true, text: 'Sistema Auto-reply' } },
    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4"><Bar data={chartData} options={options} /></div>;
}
```

- [ ] **Step 6: Actualizar `page.tsx` — importar y usar los componentes**

Agrega los imports en `stats/page.tsx`:

```typescript
import { KpiCards } from './components/KpiCards';
import { VolumeChart } from './components/VolumeChart';
import { CategoryChart } from './components/CategoryChart';
import { TopSendersChart } from './components/TopSendersChart';
import { AutoReplyChart } from './components/AutoReplyChart';
```

Reemplaza el bloque `{/* Charts — placeholder until Task 4 */}` con:

```tsx
{!loading && stats && (
  <div className="charts-container space-y-6">
    <KpiCards stats={stats} />
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <VolumeChart data={stats.volume_by_day} />
      <CategoryChart data={stats.by_category} />
    </div>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <TopSendersChart data={stats.top_senders} />
      <AutoReplyChart data={stats.autoreply} />
    </div>
  </div>
)}
```

- [ ] **Step 7: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: sin errores.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/gmail-classifier/stats/
git commit -m "feat: stats charts — KpiCards, VolumeChart, CategoryChart, TopSenders, AutoReply"
```

---

### Task 5: Verificación final y tests de integración backend

**Files:**
- `tests/` — verificar suite completa
- `frontend/` — TypeScript final

- [ ] **Step 1: Suite backend completa**

```bash
uv run pytest tests/ --tb=short -q
```

Expected: todos PASS (al menos 211 — 206 anteriores + 5 stats + 5 excel).

- [ ] **Step 2: TypeScript frontend**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sin errores.

- [ ] **Step 3: Verificar query params**

El frontend usa `?from_date=...&to_date=...` y el backend recibe `from_date: str, to_date: str`. Verificar que los nombres coinciden en `router.py` (`GET /stats` y `GET /export/excel`).

Si el endpoint usa `from_date` como nombre de parámetro FastAPI, el query string debe ser `?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`. Si hay discrepancia, corregir en el frontend.

- [ ] **Step 4: Commit final**

```bash
git add .
git commit -m "chore: verify stats + excel integration — all tests passing"
```
