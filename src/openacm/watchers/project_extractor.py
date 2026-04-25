"""
Extract project/workspace name from app window titles.

Supports: VS Code, Unity, Blender, Unreal Engine, JetBrains IDEs,
          Visual Studio, Android Studio, Xcode, Godot, Eclipse, Sublime Text.
Returns '' for unrecognized apps or when no project is open.
"""
from __future__ import annotations

import re

_SEP = r'\s*[-–—]\s*'  # -, –, —


def _parts(title: str) -> list[str]:
    return [p.strip() for p in re.split(r'\s*[-–—]\s*', title) if p.strip()]


def _vscode(title: str) -> str:
    # "file.py — project — Visual Studio Code"
    # "project — Visual Studio Code"
    # "● file.py — project — Visual Studio Code" (unsaved)
    t = re.sub(r'^[●•]\s*', '', title)
    parts = _parts(t)
    if len(parts) >= 2 and 'visual studio code' in parts[-1].lower():
        # Strip remote prefix "[Remote SSH: server] project"
        project = re.sub(r'^\[[^\]]+\]\s*', '', parts[-2])
        return project.strip()
    return ''


def _unity(title: str) -> str:
    # "ProjectName - Unity 2022.3.15f1 - Windows, Mac, Linux <DX11>"
    m = re.match(r'^(.+?)' + _SEP + r'Unity\s+\d', title)
    return m.group(1).strip() if m else ''


def _blender(title: str) -> str:
    # "*scene.blend - Blender 4.1.0"  (unsaved = *)
    # "scene.blend - Blender 4.1.0"
    # "Blender 4.1.0"  → no file open
    m = re.match(r'^\*?(.+?)' + _SEP + r'Blender\s+\d', title)
    if m:
        name = m.group(1).strip()
        return name if name.lower() not in ('blender', '') else ''
    return ''


def _unreal(title: str) -> str:
    # "MyGame - Unreal Editor"
    result = re.sub(r'' + _SEP + r'Unreal\s+(Editor|Engine).*$', '', title).strip()
    return result if result and result != title.strip() else ''


def _jetbrains(title: str) -> str:
    # "file.py – MyProject – PyCharm 2024.1.4"
    # "MyProject – IntelliJ IDEA 2024.1"
    # Strip trailing " – AppName Year.minor[.patch]"
    cleaned = re.sub(r'' + _SEP + r'[A-Z][\w ]+\s+\d{4}\.\d[\d.]*\s*$', '', title).strip()
    if not cleaned or cleaned == title.strip():
        return ''
    parts = _parts(cleaned)
    return parts[-1] if parts else ''


def _visual_studio(title: str) -> str:
    # "MyProject - Microsoft Visual Studio 2022"
    # "MyProject (Running) - Microsoft Visual Studio"
    t = re.sub(r'\s*\([^)]*\)', '', title)  # strip parentheticals like "(Running)"
    result = re.sub(r'' + _SEP + r'Microsoft Visual Studio.*$', '', t).strip()
    return result if result and result != t.strip() else ''


def _android_studio(title: str) -> str:
    # "MyProject - Android Studio Hedgehog"
    result = re.sub(r'' + _SEP + r'Android Studio.*$', '', title).strip()
    return result if result and result != title.strip() else ''


def _xcode(title: str) -> str:
    # "MyApp - Xcode" or "MyApp – Xcode"
    result = re.sub(r'' + _SEP + r'Xcode$', '', title).strip()
    return result if result != title.strip() else ''


def _godot(title: str) -> str:
    # "ProjectName - Godot Engine" or "Godot Engine - ProjectName - scene.tscn"
    result = re.sub(r'' + _SEP + r'Godot(\s+Engine)?$', '', title).strip()
    if result and result != title.strip():
        return result
    # "Godot Engine - ProjectName"
    m = re.match(r'^Godot(\s+Engine)?' + _SEP + r'(.+?)(?:' + _SEP + r'|$)', title)
    return m.group(2).strip() if m else ''


def _eclipse(title: str) -> str:
    # "com.example - Eclipse IDE" or "ProjectName - Eclipse"
    result = re.sub(r'' + _SEP + r'Eclipse.*$', '', title).strip()
    return result if result and result != title.strip() else ''


def _sublime(title: str) -> str:
    # "file.py (folder) - Sublime Text 4"
    cleaned = re.sub(r'' + _SEP + r'Sublime Text.*$', '', title).strip()
    if not cleaned or cleaned == title.strip():
        return ''
    folder = re.search(r'\(([^)]+)\)\s*$', cleaned)
    return folder.group(1).strip() if folder else cleaned


# (process_name_substrings, extractor)
# Checked in order — stops at first match.
_RULES: list[tuple[list[str], object]] = [
    (["code"],                                                       _vscode),
    (["unity"],                                                      _unity),
    (["blender"],                                                    _blender),
    (["unrealengine", "unrealed", "ue4editor", "ue5editor"],        _unreal),
    (["studio64", "androidstudio", "android-studio"],               _android_studio),
    (["pycharm", "idea", "webstorm", "rider", "goland",
      "clion", "datagrip", "rubymine", "phpstorm"],                 _jetbrains),
    (["devenv"],                                                     _visual_studio),
    (["xcode"],                                                      _xcode),
    (["godot"],                                                      _godot),
    (["eclipse"],                                                    _eclipse),
    (["subl", "sublime_text"],                                       _sublime),
]


def extract_project(process_name: str, window_title: str) -> str:
    """
    Return project/workspace name visible in window title for known dev apps.
    Returns '' for unrecognized apps or when no project is open.
    """
    if not window_title or not process_name:
        return ''
    proc = process_name.lower().replace('.exe', '').replace(' ', '')
    for substrings, extractor in _RULES:
        if any(s in proc for s in substrings):
            try:
                result = extractor(window_title)  # type: ignore[operator]
                if result and len(result.strip()) > 1:
                    return result.strip()[:100]
            except Exception:
                pass
            break  # matched app but title had no project — don't try other rules
    return ''
