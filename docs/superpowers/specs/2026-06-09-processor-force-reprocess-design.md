# Gmail Classifier — Force Re-process on Manual Trigger

**Date:** 2026-06-09  
**Status:** Approved

## Overview

Change the Gmail Classifier processor so that **manual** "Procesar" runs always re-classify all emails from the selected date (resetting any manual overrides), while **cron** runs keep the current incremental behavior (only fetch and classify new emails, leave existing ones untouched).

## Motivation

Currently both manual and cron runs skip emails already stored in the local DB. This means that after creating new categories, changing classification rules (known_senders, patterns), or deleting categories, existing emails are never re-classified. The manual trigger should act as a full refresh: re-fetch from Gmail, re-classify everything, reset manual overrides.

## Behavior

### Manual trigger (`POST /process`)
- Fetch ALL email IDs from Gmail since the selected date (no skip filter)
- For each email: fetch metadata from Gmail, classify with current categories/rules
- UPSERT into `gmail_emails`: always overwrite `category_id`, always set `manual_override = 0`
- Apply Gmail actions (mark read / apply label) according to current settings
- This is equivalent to "start fresh from the selected date"

### Cron trigger (internal scheduler)
- Fetch email IDs from Gmail since `since_date_default`
- **Skip IDs already in `gmail_emails`** — current behavior, unchanged
- Only classify and persist new (unseen) emails
- Preserve `manual_override` on any rows it does touch (via ON CONFLICT logic)

## Changes

### `processor.py` — `GmailBatchProcessor.process()`

Add `force: bool = False` parameter.

When `force=True`:
- Remove the existing-ID filter: process all IDs returned by Gmail, not just new ones
- Change the UPSERT: always update `category_id = excluded.category_id` and set `manual_override = 0` (remove the `CASE WHEN manual_override = 1` guard)

When `force=False` (default, used by cron):
- Keep current behavior: filter existing IDs, preserve `manual_override`

The two UPSERT SQL strings differ only in the `category_id` and `manual_override` lines. No other logic changes.

### `router.py` — `POST /process` endpoint

Pass `force=True` when calling `processor.process()`.

The cron scheduler calls `processor.process(since_date, force=False)` — no change needed there since `force` defaults to `False`.

### `page.tsx` — Process button warning

Add a yellow info banner directly above the "Procesar" / "Detener" button row:

> ⚠ Al procesar se reclasificarán todos los correos desde la fecha seleccionada, incluyendo los que ya tenías guardados.

The banner is always visible (not conditional on any state). It does not block the action.

## Error Handling

No new error cases. Existing error handling in `process()` (per-email try/except, `_errors` counter, rollback on fatal) applies unchanged regardless of `force`.

## Out of Scope

- Selective re-classification (only specific categories)
- UI option to choose between full vs incremental on manual trigger
- Clearing email bodies/history before re-processing
