# 🔒 OpenACM Skills - Security Auditor

Este directorio contiene skills auditadas y seguras para OpenACM.

## Uso del Security Auditor

```bash
# Auditar una skill antes de instalar
python skills/skill_security_auditor.py /ruta/a/la/skill/

# Auditar desde un repo git
python skills/skill_security_auditor.py https://github.com/usuario/repo --skill nombre-skill

# Modo estricto (WARN = FAIL)
python skills/skill_security_auditor.py /ruta/a/la/skill/ --strict

# Salida JSON
python skills/skill_security_auditor.py /ruta/a/la/skill/ --json
```

## Skills Disponibles

- **skill-security-auditor**: Audita skills en busca de código malicioso, inyección de prompts, y riesgos de dependencias

## Instalación de Nuevas Skills

1. Coloca la skill en este directorio
2. Ejecuta el auditor: `python skills/skill_security_auditor.py skills/nueva-skill/`
3. Si pasa la auditoría (PASS), está lista para usar
4. Si falla (FAIL), revisa los hallazgos y corrige antes de usar

## Integración con OpenACM

Puedes usar el auditor desde OpenACM como una herramienta:

```python
from skills.skill_security_auditor import scan_skill
from pathlib import Path

report = scan_skill(Path("skills/nueva-skill"))
if report.verdict == "PASS":
    print("✅ Skill segura para instalar")
else:
    print(f"❌ Skill rechazada: {report.critical_count} hallazgos críticos")
```
