# 🔧 Guía de Solución de Problemas - OpenACM

## Problema: "Se queda pegado después de un comando"

Si OpenACM ejecuta un comando o tool y luego se congela (no responde), prueba estas soluciones:

### Solución 1: Verificar Python del entorno virtual

El problema más común es que Windows use Python del sistema en lugar del .venv.

**Verificar cuál Python está usando:**
```batch
.venv\Scripts\python.exe --version
python --version
```

Si el segundo comando muestra una versión diferente, tu PATH está mal configurado.

**Arreglar (temporal):**
```batch
set PATH=%CD%\.venv\Scripts;%PATH%
python -m openacm
```

**Arreglar (permanente):**
1. Busca "Variables de entorno" en el menú inicio
2. Edita la variable "Path" del usuario
3. Elimina o mueve al final cualquier ruta de Python que NO sea .venv

### Solución 2: Desactivar antivirus temporalmente

Algunos antivirus (Windows Defender, McAfee, etc.) bloquean:
- La ejecución de subprocessos
- Playwright/Chromium
- Conexiones WebSocket

**Prueba:** Desactiva el antivirus temporalmente y ejecuta OpenACM.

### Solución 3: Ejecutar como Administrador

1. Click derecho en `run.bat`
2. "Ejecutar como administrador"
3. Verifica si funciona mejor

### Solución 4: Limpiar instalación corrupta

```batch
:: 1. Detener OpenACM si está corriendo
:: 2. Borrar carpetas temporales
rmdir /s /q .venv
rmdir /s /q data\media
rmdir /s /q data\vectordb

:: 3. Reinstalar
call setup.bat
```

### Solución 5: Verificar versiones de Python instaladas

```batch
:: Ver todas las instalaciones de Python
where python
where python3
where uv

:: Si hay múltiples versiones, forzar la del proyecto
.venv\Scripts\python.exe -m openacm
```

---

## Problema: Errores de timeout en Browser

```
Page.goto: Timeout 30000ms exceeded
```

### Causas:
1. Conexión a internet lenta
2. El sitio web está bloqueado por firewall
3. Playwright no está bien instalado

### Soluciones:

**Reinstalar Playwright:**
```batch
.venv\Scripts\uv run playwright install chromium
```

**Verificar conexión:**
```batch
ping google.com
```

**Desactivar proxy/firewall:**
Algunas redes corporativas bloquean playwright.

---

## Problema: Error 500 en LLM (opencode.ai)

```
Server error '500 Internal Server Error'
```

### Esto NO es problema de tu instalación

El error 500 significa que el servidor de OpenCode.ai tuvo un problema interno. Esto puede deberse a:
- Mantenimiento del servidor
- Sobrecarga temporal
- Problemas con el modelo específico

### Soluciones:

1. **Esperar unos minutos** e intentar de nuevo
2. **Cambiar de modelo** en `config/default.yaml`:
   ```yaml
   llm:
     default_model: "openai/gpt-4o"  # Probar otro modelo
   ```
3. **Verificar API key** en `config/.env`

---

## Problema: Warning de duckduckgo_search

```
RuntimeWarning: This package has been renamed to `ddgs`!
```

**Solución:** Ya está corregido en la última versión. Si persiste:

```batch
.venv\Scripts\uv pip install ddgs>=7.0
```

---

## Problema: "ModuleNotFoundError" al ejecutar

### Causa: El entorno virtual no se activó correctamente

### Solución rápida:
```batch
:: En lugar de solo run.bat, ejecuta:
call .venv\Scripts\activate.bat
python -m openacm
```

### Solución definitiva:
Editar `run.bat` y asegurar que use rutas absolutas:
```batch
set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" -m openacm
```

---

## Checklist de Verificación

Antes de reportar un problema, verifica:

- [ ] Ejecutaste `setup.bat` completo sin errores
- [ ] Tienes Python 3.12+ instalado (verificar con `python --version`)
- [ ] El archivo `config/.env` existe y tiene las API keys
- [ ] Playwright está instalado: `.venv\Scripts\playwright --version`
- [ ] No hay antivirus bloqueando procesos
- [ ] Tienes conexión a internet estable
- [ ] Ejecutaste como administrador (solo para probar)

---

## Cómo Reportar Problemas

Si nada funciona, ejecuta esto y comparte el output:

```batch
echo === INFO DEL SISTEMA === > debug.txt
echo. >> debug.txt
echo Python en PATH: >> debug.txt
where python >> debug.txt 2>&1
echo. >> debug.txt
echo Version de Python: >> debug.txt
python --version >> debug.txt 2>&1
echo. >> debug.txt
echo Version en .venv: >> debug.txt
.venv\Scripts\python.exe --version >> debug.txt 2>&1
echo. >> debug.txt
echo Variables de entorno: >> debug.txt
echo PATH=%PATH% >> debug.txt
echo. >> debug.txt
echo === CONTENIDO DE .ENV === >> debug.txt
type config\.env >> debug.txt 2>&1
```

Comparte el archivo `debug.txt` (¡elimina las API keys primero!).
