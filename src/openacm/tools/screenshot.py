"""
Screenshot Tool — capture screen and save it.
"""

import os
import time
import secrets
from pathlib import Path

from openacm.tools.base import tool
from openacm.security.crypto import save_encrypted, get_media_dir

@tool(
    name="take_screenshot",
    description=(
        "Captures a screenshot of the computer monitor/desktop and saves it as a media file. "
        "Use this whenever the user asks to 'take a screenshot' or 'show me your screen'. "
        "Returns the path to the saved screenshot."
    ),
    parameters={
        "type": "object",
        "properties": {
            "monitor": {
                "type": "integer",
                "description": "The monitor number to capture. 0 for all monitors (default), 1 for primary, etc.",
                "default": 0,
            },
        },
        "required": [],
    },
    risk_level="medium",
    category="media",
)
async def take_screenshot(monitor: int = 0, **kwargs) -> str:
    """Takes a screenshot of the system."""
    import mss
    from PIL import Image
    import io

    media_dir = get_media_dir()
    file_id = f"screenshot_{int(time.time())}_{secrets.token_hex(4)}.png"
    dest_path = media_dir / file_id
    
    try:
        with mss.mss() as sct:
            if monitor == 0:
                # Capture all monitors (the first monitor in the list is a combined view)
                monitor_dict = sct.monitors[0]
            else:
                if monitor < len(sct.monitors):
                    monitor_dict = sct.monitors[monitor]
                else:
                    return f"Error: Monitor {monitor} not found."
            
            # Grab screenshot
            sct_img = sct.grab(monitor_dict)
            
            # Convert to PIL Image to easily get bytes or manipulate
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            # Save to bytes io
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG', optimize=True, quality=85)
            img_bytes = img_byte_arr.getvalue()
            
            # Save encrypted file
            save_encrypted(img_bytes, dest_path)
            
            # Also invoke the event bus to optionally broadcast the image URL back to the user
            _event_bus = kwargs.get("_event_bus")
            if _event_bus:
                # Tell we got a screenshot file id
                pass
            
            return f"Screenshot successfully taken! Tell the user they can view the screenshot by returning this exact URL in your message: /api/media/{file_id}"
            
    except Exception as e:
        return f"Failed to take screenshot: {str(e)}"
