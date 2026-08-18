# Estrategia de deploy para clientes específicos — Design

**Fecha:** 2026-08-18
**Estado:** Aprobado, pendiente de plan de implementación

## Contexto

`OpenACM` (este repo) es un proyecto público, MIT, pensado para desarrolladores.
Vamos a deployar variantes de OpenACM para clientes específicos — cada uno con su
propio server, su propia configuración/branding, y potencialmente integraciones
propias (su ERP, su CRM, etc.). Va a haber varios clientes (patrón repetible, no
un caso único).

Objetivo del diseño: definir cómo se relaciona "lo general" (este repo) con "lo
específico de cada cliente" sin que:
- el código diverja en forks imposibles de mantener,
- actualizar el core sea un dolor manual por cliente,
- el código fuente del core (o de un cliente) quede expuesto en el server de
  producción de un cliente.

## Decisiones

### 1. Política de fork: último recurso

Nunca la estrategia por defecto. Un fork por cliente reproduce exactamente el
problema que se quiere evitar: cada fix en el core hay que reconciliarlo a mano
en cada fork, y cada fork que tocó el core en un lugar distinto genera conflictos
que crecen con el número de clientes.

Criterio para permitir un fork puntual: la pieza es **verdaderamente única** de
ese cliente y no tiene sentido generalizarla. Ante la duda, se trata como
reusable (se construye como punto de extensión, no como fork). Un fork puntual
implica aceptar que esa zona del código de ese cliente queda parcialmente
aislada de updates automáticos del core.

### 2. Jerarquía de extensión

Cuando un cliente pide algo distinto al comportamiento default, la pregunta en
orden (del más barato al más caro):

1. **Config flag** — ¿es prender/apagar algo? Ya existe el mecanismo de layering
   de config: `env vars > .env > config/local.yaml (gitignored) > config/default.yaml
   > defaults` (`core/config.py`). Los channels (Discord/Telegram/WhatsApp) ya
   usan `enabled: true/false` con este patrón. Ya existe también `client_profile`
   en `config/local.yaml` para restringir qué páginas del dashboard ve un cliente
   — es precedente directo de "config-driven client customization" ya probado en
   este repo.
   - **Gap identificado:** Voice daemon y `browser_agent` (Playwright) no tienen
     este toggle todavía — se instancian siempre (con degradación si faltan
     deps). Se les agrega `enabled` siguiendo el mismo patrón que channels,
     bajo demanda (no hace falta auditar/tocar todo el repo de una — se agrega
     el toggle a un subsistema cuando un cliente real necesita apagarlo).

2. **Plugin package** — ¿es una integración nueva (su ERP, su CRM)? Ya existe el
   sistema de plugins (`src/openacm/plugins/`, clase `Plugin` + `PluginManager`),
   con auto-discovery vía Python entry points (`group = "openacm.plugins"`). Un
   plugin de cliente es un paquete Python separado, en su propio repo, que se
   `pip install -e` en el mismo venv del core — sin tocar una sola línea de
   `OpenACM`. Puede aportar tools, skills, rutas API, contexto de sistema para el
   LLM, keywords de intent routing, nav del frontend, y tiene enable/disable
   per-plugin en DB. Este mecanismo ya está completo, no requiere cambios.

3. **Nuevo punto de extensión en el core** — ¿el comportamiento mismo de una
   pieza del core debe cambiar (no solo on/off)? Ej: un cliente necesita su
   propio flujo de auth, o una política de memory distinta. Se diseña como
   interfaz + implementación inyectable (el core define el contrato, el plugin
   del cliente inyecta su implementación). No existe un mecanismo genérico para
   esto todavía — se construye caso por caso, cuando un cliente real lo pide, y
   el punto de extensión resultante queda disponible para todos los clientes
   futuros.

4. **Fork puntual** — último recurso, ver política arriba.

### 3. Versionado y distribución del core

El repo general nunca se clona ni se hace `git pull` directamente en un server
de cliente (código público expuesto en infra de producción de un cliente pagado
= mal look, además de acoplar el update de un cliente al HEAD de `main`).

En su lugar:

- El repo se etiqueta con tags semver (`vX.Y.Z`) + changelog por release.
- Un workflow de GitHub Actions, disparado por push de tag `v*`, hace build de
  la imagen Docker (usando el `docker/Dockerfile` ya existente, con las
  correcciones ya identificadas en `docs/DEPLOY_VPS.md` — quitar `xdotool` para
  headless, etc.) y la sube a un **registry privado** (GitHub Container
  Registry, visibilidad privada — ya integrado con GH Actions, sin costo
  adicional).
- Los clientes nunca siguen `main`. Siempre fijan una versión concreta.

### 4. Repos de cliente

Privados, separados del repo general (nunca fork, nunca submodule). Un solo
monorepo `openacm-clients/` (repo nuevo, fuera de `OpenACM`) con una carpeta por
cliente (`clients/acme/`, `clients/foo/`, ...) en vez de un repo por cliente —
da visibilidad para notar cuándo 2+ clientes piden lo mismo (señal de que eso
debe graduar de "plugin de cliente" a "punto de extensión en el core", ver
sección 2.3).

Es un repo **privado hosteado** (ej. GitHub privado), no algo que viva solo en
la máquina local — se clona local para trabajar en él día a día (igual que
`OpenACM`), pero el remoto es la fuente de verdad. Un repo solo-local no
sobrevive a la pérdida del disco, y el CI que construye/sube las imágenes de
cada cliente necesita disparar desde un push al remoto.

Cada carpeta de cliente contiene:
- Su plugin package (integraciones propias, si aplica).
- Su `config/` (incluye su `client_profile` si aplica) + `.env.example`.
- Un `Dockerfile` que hace `FROM openacm-core:vX.Y.Z`, copia su plugin package
  e instala (`pip install -e`), copia su config → build de imagen
  `openacm-client-<nombre>:vX.Y.Z` → push al mismo registry privado.

### 5. Deploy y update en el server del cliente

El server de cada cliente **solo** hace `docker pull openacm-client-<nombre>:vX.Y.Z`
+ `docker run` / `docker compose up`. Nunca hay `.git` ni código fuente (ni del
core ni del cliente) en esa máquina — solo un contenedor corriendo.

Secrets (API keys, tokens) se inyectan en runtime vía variables de entorno /
secrets store del server — nunca quedan horneados en la imagen ni en el repo de
cliente.

Update = decisión deliberada: subir el tag base que usa el `Dockerfile` del
cliente → rebuild de la imagen del cliente → push → el server del cliente hace
`docker pull` del tag nuevo → restart. Nunca automático, nunca sigue `main`.

## Fuera de alcance de este spec

- El hardening de seguridad pendiente (tokens en plaintext en SQLite, token del
  dashboard en logs de arranque, auth de WebSocket por query param — ya
  listados en `docs/DEPLOY_VPS.md`) es un spec/track separado.
- La estructura interna del repo `openacm-clients/` (plantilla exacta,
  convenciones de nombres, CI de ese repo) se define en su propio plan de
  implementación cuando se cree ese repo — este spec solo fija el contrato
  (qué contiene cada carpeta de cliente y cómo se relaciona con el core).

## Alcance del cambio en este repo (`OpenACM`)

Aditivo, no reescritura. Ya existe: sistema de plugins completo, layering de
config (`default.yaml` → `local.yaml` → `.env` → env vars), precedente de
`client_profile`, `Dockerfile`/`docker-compose.yml` base.

Falta:
1. Agregar `enabled` a Voice daemon y `browser_agent` (Playwright), mismo patrón
   que los channels — bajo demanda, no todo de una vez.
2. Workflow de GitHub Actions: build + push de imagen Docker a GHCR privado en
   cada tag `v*`.
3. Documentar la convención de versionado semver + changelog.
4. Aplicar las correcciones ya identificadas en `docs/DEPLOY_VPS.md` para el
   `Dockerfile` (quitar `xdotool`, etc.) si no se han aplicado.
