---
name: "file-generator"
description: "Generate and deliver files (PDFs, documents, images) to users"
category: "custom"
---

# File Generator Skill

## When to Use This Skill
When the user asks you to generate ANY file (PDF, Word, Excel, image, ZIP, etc.)

## CRITICAL WORKFLOW - FOLLOW EXACTLY:

### Step 1: Generate the File
Use `run_python` to create the file. Save it to a known location like:
- `data/media/your_file.pdf`
- `./output/report.xlsx`

### Step 2: ATTACH THE FILE (MANDATORY)
**IMMEDIATELY after generating the file, you MUST call `send_file_to_chat` tool with the file path.**

Example:
```
User: "Generate a PDF report"

Your actions:
1. [run_python] Code that creates data/media/report.pdf
2. [send_file_to_chat] Path: data/media/report.pdf  ← THIS IS REQUIRED!
3. [Response] "Here's your PDF: /api/media/report.pdf"
```

### Step 3: Write the Link CORRECTLY
After calling send_file_to_chat, write the download link in your response following these CRITICAL rules:

**✅ CORRECT format (PLAIN TEXT):**
```
Your PDF is ready: /api/media/upload_abc123.pdf
```

**❌ WRONG formats (NEVER do this):**
```
Your PDF: `/api/media/upload_abc123.pdf`  ← Backticks prevent download!
Your PDF: ```/api/media/upload_abc123.pdf``` ← Code blocks prevent download!
Your PDF: [download](/api/media/upload_abc123.pdf) ← Markdown links don't work!
```

**IMPORTANT:** The system only detects plain text /api/media/ links. Any formatting (backticks, code blocks, markdown) will break the download button!

## ⚠️ COMMON MISTAKES TO AVOID:
❌ WRONG: Just writing "Download: /api/media/file.pdf" WITHOUT calling send_file_to_chat first
❌ WRONG: Putting the link in backticks: `/api/media/file.pdf`
❌ WRONG: Using markdown format: [file](/api/media/file.pdf)
✅ CORRECT: Call send_file_to_chat tool FIRST, then write the link as PLAIN TEXT

## Examples:

**PDF Generation:**
- Use run_python with reportlab/fpdf
- Save to data/media/
- Call send_file_to_chat
- Message with link

**Excel Generation:**
- Use run_python with openpyxl/pandas
- Save to data/media/
- Call send_file_to_chat
- Message with link

**Image Generation:**
- Use run_python with matplotlib/PIL
- Save to data/media/
- Call send_file_to_chat
- Message with link

## Remember:
The user CANNOT download the file unless you use send_file_to_chat!
Text links alone don't work - the file must be attached via the tool.
