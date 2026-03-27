# 🔒 OpenACM Security Policy

## Modelo de Amenazas y Análisis de Seguridad

**Última Auditoría:** Marzo 2025  
**Herramienta:** skill-security-auditor (Claude Skills)  
**Veredicto:** ✅ SEGURO - Todos los hallazgos son INTENCIONALES

---

## 📊 Resumen de Auditoría

| Categoría | Hallazgos | Por Diseño | Acción Requerida |
|-----------|-----------|------------|------------------|
| NET-EXFIL | 4 | 4 (100%) | 0 |
| CRED-HARVEST | 4 | 4 (100%) | 0 |
| OBFUSCATION | 1 | 1 (100%) | 0 |
| DEPS-RUNTIME | 1 | 1 (100%) | 0* |
| **TOTAL** | **10** | **10 (100%)** | **0** |

*Recomendación opcional implementada

---

## 🎯 Componentes de Seguridad

### 1. Sandbox de Ejecución

OpenACM implementa un sandbox de seguridad en `src/openacm/security/sandbox.py` que:
- Limita comandos del sistema a un timeout configurable
- Restringe acceso a directorios sensibles
- Valida paths antes de operaciones de archivo
- Registra todas las ejecuciones para auditoría

**Archivo:** `src/openacm/security/sandbox.py`

### 2. Gestión Segura de Credenciales

Todas las API keys y tokens se manejan mediante:
- Variables de entorno (nunca hardcodeadas)
- Archivos de configuración en `config/` (excluidos de git)
- Cifrado opcional para tokens persistentes

**Archivos involucrados:**
- `src/openacm/core/config.py` - Carga de configuración
- `src/openacm/security/crypto.py` - Gestión de tokens
- `src/openacm/web/server.py` - Autenticación dashboard

### 3. Aislamiento de Canales

Cada canal de comunicación (Discord, Telegram, WhatsApp) opera en:
- Procesos/tasks independientes
- Contextos de seguridad separados
- Validación de mensajes entrantes

---

## 🔴 Hallazgos Críticos (Por Diseño)

### Comunicación HTTP Externa

**Ubicaciones:**
- `src/openacm/core/llm_router.py`
- `src/openacm/channels/whatsapp_channel.py`
- `src/openacm/tools/web_search.py`
- `src/openacm/web/server.py`

**Descripción:**
OpenACM requiere comunicación HTTP para:
- APIs de LLM (OpenAI, Anthropic, Gemini, Ollama)
- APIs de mensajería (WhatsApp Business, Telegram Bot, Discord)
- Búsqueda web (DuckDuckGo)
- Servicios externos (Google APIs)

**Mitigación:**
- Timeout en todas las solicitudes (15-30s)
- Sin reintentos automáticos sin límite
- Validación de URLs (evita localhost/private IPs)
- Registro de todas las llamadas

### Acceso a Variables de Entorno

**Ubicaciones:**
- `src/openacm/core/config.py`
- `src/openacm/security/crypto.py`
- `src/openacm/web/server.py`

**Descripción:**
Carga de API keys mediante `os.environ.get()`

**Mitigación:**
- Solo lectura, nunca escritura
- Sin valores por defecto sensibles
- Documentación clara de variables requeridas
- Ejemplo en `config/.env.example`

### Procesamiento Base64

**Ubicación:**
- `src/openacm/tools/python_kernel.py:144`

**Descripción:**
Decodificación de imágenes PNG en base64 del kernel Jupyter

**Mitigación:**
- Solo imágenes matplotlib generadas internamente
- No procesa input de usuario directamente
- Validación de formato antes de decodificación

---

## 🛡️ Políticas de Seguridad

### Ejecución de Código

- ✅ Comandos del sistema permitidos con sandbox
- ✅ Ejecución Python en kernel aislado (Jupyter)
- ❌ Sin `eval()` o `exec()` de input de usuario
- ❌ Sin carga dinámica de código no verificado

### Acceso a Archivos

- ✅ Lectura/escritura en directorio de trabajo
- ✅ Acceso a `data/` para persistencia
- ✅ Acceso a `config/` para configuración
- ❌ Sin acceso a `~/.ssh`, `~/.aws`, credenciales del sistema
- ❌ Sin modificación de archivos de sistema

### Red

- ✅ Conexiones a APIs públicas documentadas
- ✅ Webhooks para canales de mensajería
- ❌ Sin escaneo de puertos
- ❌ Sin conexiones a IPs privadas sin autorización

---

## 🔍 Auditoría Automática

Para ejecutar auditoría de seguridad:

```bash
# Auditar código fuente
python .opencode/skills/skill-security-auditor/scripts/skill_security_auditor.py src/

# Auditar con modo estricto
python .opencode/skills/skill-security-auditor/scripts/skill_security_auditor.py src/ --strict

# Salida JSON para CI/CD
python .opencode/skills/skill-security-auditor/scripts/skill_security_auditor.py src/ --json
```

---

## 🚨 Reportar Vulnerabilidades

Si descubres una vulnerabilidad de seguridad:

1. **NO abras un issue público**
2. Envía un email a: [tu-email@ejemplo.com]
3. Incluye:
   - Descripción detallada
   - Pasos para reproducir
   - Impacto potencial
   - Sugerencias de mitigación (opcional)

**Tiempo de respuesta esperado:** 48-72 horas

---

## 📋 Variables de Entorno Sensibles

| Variable | Propósito | Requerida |
|----------|-----------|-----------|
| `OPENAI_API_KEY` | API de OpenAI | Opcional |
| `ANTHROPIC_API_KEY` | API de Anthropic | Opcional |
| `GEMINI_API_KEY` | API de Google Gemini | Opcional |
| `DISCORD_TOKEN` | Bot de Discord | Opcional |
| `TELEGRAM_TOKEN` | Bot de Telegram | Opcional |
| `DASHBOARD_TOKEN` | Autenticación web | Auto-generado |
| `GOOGLE_CREDENTIALS` | OAuth2 Google | Opcional |

Todas las variables se cargan mediante `os.environ.get()` con valores por defecto vacíos.

---

## 🔐 Mejores Prácticas para Usuarios

### 1. Protección de API Keys

```bash
# ✅ Correcto - Usar archivo .env
export OPENAI_API_KEY="sk-..."
export DISCORD_TOKEN="..."

# Nunca commitear el archivo .env
# Está incluido en .gitignore
```

### 2. Sandbox de Seguridad

El modo de ejecución se configura en `config/default.yaml`:

```yaml
security:
  execution_mode: strict  # strict | normal | permissive
  max_command_timeout: 30
  allowed_paths:
    - ./data
    - ./config
```

### 3. Token de Dashboard

El token se genera automáticamente en el primer arranque:
- Se almacena cifrado en `data/openacm.db`
- Se puede rotar desde la configuración web
- TTL configurable (por defecto: sin expiración)

---

## 📅 Historial de Auditorías

| Fecha | Herramienta | Resultado | Hallazgos |
|-------|-------------|-----------|-----------|
| 2025-03-27 | skill-security-auditor | ✅ PASS | 10/10 Por Diseño |

---

## 📚 Referencias

- [skill-security-auditor Documentation](.opencode/skills/skill-security-auditor/SKILL.md)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python-security.readthedocs.io/)

---

**Nota:** Este documento se actualiza automáticamente tras cada auditoría de seguridad.

Última actualización: Marzo 2025
