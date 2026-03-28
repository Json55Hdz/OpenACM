---
name: "video-capture"
description: "Graba un video de la pantalla usando Python (mss y opencv) por una duración específica y lo envía al usuario."
category: "custom"
created: "2026-03-28T10:07:33.231574"
---

# Video Capture

## Overview
The `video-capture` skill enables the AI assistant to record the user's screen for a specified duration using Python, specifically leveraging the `mss` (for high-speed screen grabbing) and `opencv-python` (`cv2` for video encoding) libraries. 

Use this skill when:
- The user explicitly asks to record or capture their screen/desktop.
- A video clip is required to troubleshoot, document, or demonstrate a moving process on the PC.
- The user needs to capture a short animation, video playback, or sequence of actions occurring on their primary monitor.

## Guidelines

### Execution Strategy
When a user requests a screen recording, follow these steps:
1. **Determine Duration:** Extract the requested duration from the user's prompt. If no duration is specified, default to **5 seconds**. Cap the maximum duration to **60 seconds** to prevent memory/disk space exhaustion unless explicitly overridden by system limits.
2. **Warn & Prepare:** If applicable, give the user a brief warning (e.g., "Starting recording in 3 seconds...") so they can prepare their screen.
3. **Execute Code:** Run the Python script to capture the screen.
4. **Deliver File:** Save the file locally (usually as `.mp4` or `.avi`) and provide the file path or upload the file directly to the user interface.

### Technical Implementation & Code Pattern
Use the following robust Python pattern to execute the capture. It dynamically fetches screen resolution, handles the `mss` to `OpenCV` color conversion, and ensures resources are safely released.

```python
import mss
import cv2
import numpy as np
import time
import os

def record_screen(duration_seconds=5, output_filename="screen_capture.mp4"):
    # Set up MSS for screen capture
    with mss.mss() as sct:
        # Monitor 1 is usually the primary monitor
        monitor = sct.monitors[1]
        width, height = monitor["width"], monitor["height"]
        
        # Set up OpenCV VideoWriter
        # mp4v is a standard codec for .mp4 files
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        fps = 20.0 # 20 FPS is a safe balance for Python loop performance
        out = cv2.VideoWriter(output_filename, fourcc, fps, (width, height))
        
        print(f"Recording started for {duration_seconds} seconds...")
        start_time = time.time()
        
        try:
            while (time.time() - start_time) < duration_seconds:
                # Capture screen
                img = np.array(sct.grab(monitor))
                
                # IMPORTANT: MSS captures in BGRA, OpenCV expects BGR
                frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                
                # Write frame to video
                out.write(frame)
                
                # Slight sleep to stabilize FPS (optional, but helps avoid CPU maxing)
                time.sleep(1/fps)
                
        finally:
            # Always release the VideoWriter to prevent file corruption
            out.release()
            print(f"Recording saved to {os.path.abspath(output_filename)}")
