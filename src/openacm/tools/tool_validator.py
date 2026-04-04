"""
Tool Validator — Automated testing for dynamically created tools.

Runs a series of checks on generated tool code before it is saved to disk:
  1. Syntax validation
  2. Import availability
  3. Security scan (dangerous patterns)
  4. Async function presence
  5. Dry-run module load

Emits EVENT_TOOL_VALIDATION events after each step so the UI can show
a live progress panel while validation runs.
"""

import ast
import importlib.util
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from openacm.core.events import EventBus

log = structlog.get_logger()

# Patterns that flag a security warning (not hard-blocked, just reported)
_DANGEROUS_PATTERNS = [
    ("eval(", "uso de eval()"),
    ("exec(", "uso de exec()"),
    ("__import__", "importación dinámica con __import__"),
    ("os.system(", "ejecución de shell con os.system()"),
    ("subprocess.call(", "subprocess.call()"),
    ("subprocess.Popen(", "subprocess.Popen()"),
    ("open(", "acceso a archivos con open()"),
    ("pickle.loads(", "deserialización con pickle"),
    ("shutil.rmtree(", "eliminación recursiva shutil.rmtree()"),
]

# Step names (used as stable IDs in the frontend)
STEP_SYNTAX   = "Sintaxis"
STEP_IMPORTS  = "Imports"
STEP_SECURITY = "Seguridad"
STEP_FUNCTION = "Función async"
STEP_DRYRUN   = "Dry-run"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    warning: bool = False


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.warning for c in self.checks)

    def format(self) -> str:
        lines = []
        for c in self.checks:
            icon = "✅" if (c.passed and not c.warning) else "⚠️" if c.warning else "❌"
            lines.append(f"{icon} **{c.name}**: {c.detail}")
        return "\n".join(lines)


# ── Pure (sync) check functions ──────────────────────────────────────────────

def _check_syntax(code: str) -> CheckResult:
    try:
        compile(code, "<tool>", "exec")
        return CheckResult(STEP_SYNTAX, True, "código Python válido")
    except SyntaxError as e:
        return CheckResult(STEP_SYNTAX, False, f"línea {e.lineno}: {e.msg}")


def _check_imports(code: str) -> CheckResult:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return CheckResult(STEP_IMPORTS, False, "no se puede analizar (sintaxis inválida)")

    missing, available = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                (available if importlib.util.find_spec(mod) else missing).append(mod)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module.split(".")[0]
            (available if importlib.util.find_spec(mod) else missing).append(mod)

    if missing:
        return CheckResult(STEP_IMPORTS, False, f"módulos no encontrados: {', '.join(set(missing))}")
    detail = f"disponibles: {', '.join(set(available))}" if available else "sin imports externos"
    return CheckResult(STEP_IMPORTS, True, detail)


def _check_security(code: str) -> CheckResult:
    warnings = [msg for pat, msg in _DANGEROUS_PATTERNS if pat in code]
    if warnings:
        return CheckResult(STEP_SECURITY, True, "; ".join(warnings), warning=True)
    return CheckResult(STEP_SECURITY, True, "sin patrones peligrosos detectados")


def _check_async_function(code: str, func_name: str) -> CheckResult:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return CheckResult(STEP_FUNCTION, False, "no se puede analizar")

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            return CheckResult(STEP_FUNCTION, True, f"async def {func_name}() encontrada")

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            return CheckResult(STEP_FUNCTION, True,
                f"async def {node.name}() encontrada (nombre difiere de '{func_name}')", warning=True)

    return CheckResult(STEP_FUNCTION, False, f"no se encontró ninguna función async def")


def _check_dry_run(full_module_code: str, func_name: str) -> CheckResult:
    namespace: dict = {}
    try:
        compiled = compile(full_module_code, "<dry_run>", "exec")
        exec(compiled, namespace)  # noqa: S102
    except ImportError as e:
        return CheckResult(STEP_DRYRUN, False, f"error de import: {e}")
    except Exception as e:
        return CheckResult(STEP_DRYRUN, False, f"error al cargar módulo: {type(e).__name__}: {e}")

    if func_name in namespace and callable(namespace[func_name]):
        return CheckResult(STEP_DRYRUN, True, "módulo cargado y función encontrada")
    return CheckResult(STEP_DRYRUN, True, "módulo cargado (función no inspeccionable en este contexto)", warning=True)


# ── Async runner with live event emission ─────────────────────────────────────

async def run_tool_validation(
    name: str,
    code: str,
    full_module_code: str,
    event_bus: "EventBus | None" = None,
    channel_id: str | None = None,
) -> ValidationReport:
    """
    Run all checks and emit EVENT_TOOL_VALIDATION events for each step.

    Each event payload:
      { tool, channel_id, step, status: "running"|"passed"|"failed"|"warning", detail }
    """
    from openacm.core.events import EVENT_TOOL_VALIDATION

    async def emit(step: str, status: str, detail: str = ""):
        if event_bus and channel_id:
            await event_bus.emit(EVENT_TOOL_VALIDATION, {
                "tool": name,
                "channel_id": channel_id,
                "step": step,
                "status": status,
                "detail": detail,
            })

    report = ValidationReport()

    steps = [
        (STEP_SYNTAX,   lambda: _check_syntax(code)),
        (STEP_IMPORTS,  lambda: _check_imports(code)),
        (STEP_SECURITY, lambda: _check_security(code)),
        (STEP_FUNCTION, lambda: _check_async_function(code, name)),
    ]

    for step_name, check_fn in steps:
        await emit(step_name, "running")
        result = check_fn()
        status = "passed" if result.passed and not result.warning else \
                 "warning" if result.warning else "failed"
        await emit(step_name, status, result.detail)
        report.checks.append(result)

    # Dry-run only if no failures so far
    if report.passed:
        await emit(STEP_DRYRUN, "running")
        result = _check_dry_run(full_module_code, name)
        status = "passed" if result.passed and not result.warning else \
                 "warning" if result.warning else "failed"
        await emit(STEP_DRYRUN, status, result.detail)
        report.checks.append(result)

    # Final summary event
    final = "passed" if report.passed else "failed"
    await emit("__done__", final, "")

    return report
