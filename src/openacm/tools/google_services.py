"""
Google Services Tools — Gmail, Calendar, Drive, YouTube.

Uses Google OAuth2 + REST APIs for secure access to Google services.
Requires a Google Cloud project with APIs enabled and OAuth2 credentials.

Setup:
1. Go to https://console.cloud.google.com/
2. Create a project (or use existing)
3. Enable APIs: Gmail, Calendar, Drive, YouTube Data API v3
4. Create OAuth2 credentials (Desktop application)
5. Download credentials.json to config/google_credentials.json
6. On first use, a browser will open for authorization
"""

import os
import json
from pathlib import Path
from typing import Any

from openacm.tools.base import tool

# Scopes needed for each service
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.readonly",
]

_credentials_cache = None


async def _get_google_service(service_name: str, version: str):
    """
    Get an authenticated Google API service client.
    Uses OAuth2 with token caching.
    """
    global _credentials_cache

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Google API libraries not installed. "
            "These dependencies are already listed in pyproject.toml. "
            "To install them, run: pip install -e .\n\n"
            "Or manually: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    creds = _credentials_cache
    token_path = Path("config/google_token.json")
    creds_path = Path("config/google_credentials.json")

    # Load saved token
    if not creds and token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Refresh or re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    "Google credentials not found.\n"
                    "Download your OAuth2 credentials from Google Cloud Console\n"
                    "and save them as: config/google_credentials.json\n\n"
                    "Steps:\n"
                    "1. Go to https://console.cloud.google.com/apis/credentials\n"
                    "2. Create OAuth 2.0 Client ID (Desktop application)\n"
                    "3. Download JSON and save as config/google_credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    _credentials_cache = creds
    return build(service_name, version, credentials=creds)


# ═══════════════════════════════════════════════════════
#  GMAIL TOOLS
# ═══════════════════════════════════════════════════════


@tool(
    name="gmail_read",
    description=(
        "Read emails from Gmail. Can list recent emails, search by query, "
        "or read a specific email. Returns subject, sender, date, and snippet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Gmail search query (e.g., 'from:john@example.com', "
                    "'is:unread', 'subject:invoice', 'newer_than:1d'). "
                    "Leave empty for recent emails."
                ),
                "default": "",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of emails to return (default: 10)",
                "default": 10,
            },
        },
        "required": [],
    },
    risk_level="medium",
)
async def gmail_read(query: str = "", max_results: int = 10, **kwargs) -> str:
    """Read emails from Gmail."""
    try:
        service = await _get_google_service("gmail", "v1")

        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query or "is:inbox",
                maxResults=max_results,
            )
            .execute()
        )

        messages = results.get("messages", [])
        if not messages:
            return "No se encontraron emails" + (f" para: {query}" if query else ".")

        output = []
        for msg_ref in messages:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                )
                .execute()
            )

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(sin asunto)")
            sender = headers.get("From", "?")
            date = headers.get("Date", "?")
            snippet = msg.get("snippet", "")
            unread = "UNREAD" in msg.get("labelIds", [])

            status = "📩" if unread else "📧"
            output.append(
                f"{status} **{subject}**\n   De: {sender}\n   Fecha: {date}\n   {snippet[:100]}..."
            )

        return f"📬 {len(messages)} emails encontrados:\n\n" + "\n\n".join(output)

    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Error leyendo Gmail: {str(e)}"


@tool(
    name="gmail_send",
    description=("Send an email via Gmail. Specify recipient, subject, and body."),
    parameters={
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address",
            },
            "subject": {
                "type": "string",
                "description": "Email subject",
            },
            "body": {
                "type": "string",
                "description": "Email body text",
            },
        },
        "required": ["to", "subject", "body"],
    },
    risk_level="high",
)
async def gmail_send(to: str, subject: str, body: str, **kwargs) -> str:
    """Send an email via Gmail."""
    try:
        import base64
        from email.mime.text import MIMEText

        service = await _get_google_service("gmail", "v1")

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        return f'✅ Email enviado a {to}: "{subject}"'

    except Exception as e:
        return f"Error enviando email: {str(e)}"


# ═══════════════════════════════════════════════════════
#  GOOGLE CALENDAR TOOLS
# ═══════════════════════════════════════════════════════


@tool(
    name="calendar_list",
    description=(
        "List upcoming events from Google Calendar. "
        "Shows event title, date/time, location, and description."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events (default: 10)",
                "default": 10,
            },
            "days_ahead": {
                "type": "integer",
                "description": "How many days ahead to look (default: 7)",
                "default": 7,
            },
        },
        "required": [],
    },
    risk_level="low",
)
async def calendar_list(max_results: int = 10, days_ahead: int = 7, **kwargs) -> str:
    """List upcoming calendar events."""
    try:
        from datetime import datetime, timezone, timedelta

        service = await _get_google_service("calendar", "v3")

        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        if not events:
            return f"📅 No hay eventos en los próximos {days_ahead} días."

        output = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            summary = event.get("summary", "(sin título)")
            location = event.get("location", "")

            line = f"📅 **{summary}**\n   📆 {start}"
            if location:
                line += f"\n   📍 {location}"
            output.append(line)

        return f"📅 {len(events)} eventos próximos:\n\n" + "\n\n".join(output)

    except Exception as e:
        return f"Error leyendo calendario: {str(e)}"


@tool(
    name="calendar_create",
    description=("Create a new event in Google Calendar."),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Event title",
            },
            "start_time": {
                "type": "string",
                "description": "Start time in ISO format (e.g., '2025-03-27T10:00:00')",
            },
            "end_time": {
                "type": "string",
                "description": "End time in ISO format (e.g., '2025-03-27T11:00:00')",
            },
            "description": {
                "type": "string",
                "description": "Event description (optional)",
                "default": "",
            },
            "location": {
                "type": "string",
                "description": "Event location (optional)",
                "default": "",
            },
        },
        "required": ["summary", "start_time", "end_time"],
    },
    risk_level="medium",
)
async def calendar_create(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    **kwargs,
) -> str:
    """Create a calendar event."""
    try:
        service = await _get_google_service("calendar", "v3")

        event = {
            "summary": summary,
            "start": {"dateTime": start_time, "timeZone": "America/Bogota"},
            "end": {"dateTime": end_time, "timeZone": "America/Bogota"},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location

        created = service.events().insert(calendarId="primary", body=event).execute()

        return (
            f'✅ Evento creado: "{summary}" ({start_time})\n   Link: {created.get("htmlLink", "")}'
        )

    except Exception as e:
        return f"Error creando evento: {str(e)}"


# ═══════════════════════════════════════════════════════
#  GOOGLE DRIVE TOOLS
# ═══════════════════════════════════════════════════════


@tool(
    name="drive_list",
    description=("List files in Google Drive. Can search by name or type."),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query. Examples: 'name contains \"report\"', "
                    "'mimeType=\"application/pdf\"', "
                    "'modifiedTime > \"2024-01-01\"'"
                ),
                "default": "",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results (default: 20)",
                "default": 20,
            },
        },
        "required": [],
    },
    risk_level="low",
)
async def drive_list(query: str = "", max_results: int = 20, **kwargs) -> str:
    """List files in Google Drive."""
    try:
        service = await _get_google_service("drive", "v3")

        params = {
            "pageSize": max_results,
            "fields": "files(id, name, mimeType, size, modifiedTime, webViewLink)",
            "orderBy": "modifiedTime desc",
        }
        if query:
            params["q"] = query

        results = service.files().list(**params).execute()
        files = results.get("files", [])

        if not files:
            return "📁 No se encontraron archivos" + (f" para: {query}" if query else ".")

        output = []
        for f in files:
            name = f.get("name", "?")
            mime = f.get("mimeType", "?").split("/")[-1]
            size = _format_drive_size(int(f.get("size", 0))) if f.get("size") else "-"
            modified = f.get("modifiedTime", "?")[:10]

            output.append(f"  📄 {name} ({mime}, {size}) — {modified}")

        return f"📁 {len(files)} archivos en Drive:\n" + "\n".join(output)

    except Exception as e:
        return f"Error listando Drive: {str(e)}"


@tool(
    name="drive_search",
    description=("Search for files in Google Drive by name."),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "File name to search for",
            },
        },
        "required": ["name"],
    },
    risk_level="low",
)
async def drive_search(name: str, **kwargs) -> str:
    """Search files by name."""
    return await drive_list(query=f'name contains "{name}"')


# ═══════════════════════════════════════════════════════
#  YOUTUBE TOOLS
# ═══════════════════════════════════════════════════════


@tool(
    name="youtube_search",
    description=("Search for videos on YouTube. Returns titles, channels, view counts, and URLs."),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for YouTube",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    risk_level="low",
)
async def youtube_search(query: str, max_results: int = 5, **kwargs) -> str:
    """Search YouTube videos."""
    try:
        service = await _get_google_service("youtube", "v3")

        results = (
            service.search()
            .list(
                q=query,
                part="snippet",
                maxResults=max_results,
                type="video",
            )
            .execute()
        )

        items = results.get("items", [])
        if not items:
            return f"🎥 No se encontraron videos para: {query}"

        output = []
        for item in items:
            snippet = item["snippet"]
            video_id = item["id"]["videoId"]
            title = snippet.get("title", "?")
            channel = snippet.get("channelTitle", "?")
            published = snippet.get("publishedAt", "?")[:10]
            url = f"https://youtube.com/watch?v={video_id}"

            output.append(f"🎥 **{title}**\n   📺 {channel} — {published}\n   🔗 {url}")

        return f"🎥 {len(items)} videos encontrados:\n\n" + "\n\n".join(output)

    except Exception as e:
        return f"Error buscando en YouTube: {str(e)}"


def _format_drive_size(size: int) -> str:
    """Format file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
