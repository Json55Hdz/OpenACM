# Configuración de Home Assistant

Guía para instalar Home Assistant (si no lo tienes ya) y conectarlo al plugin
`home_assistant` de OpenACM, para controlar luces, enchufes, clima, cortinas,
reproductores y escenas por chat, voz, o desde el dashboard.

> **Resultado final:** le dices al agente "apaga las luces de la sala" o
> entras a `/home-assistant` en el dashboard y controlas tus dispositivos con
> un click — todo pasando por tu Home Assistant real, sin drivers propios de
> cada marca.

---

## Índice

1. [Cómo funciona](#1-cómo-funciona)
2. [Parte A — Instalar Home Assistant con Docker](#parte-a--instalar-home-assistant-con-docker)
3. [Parte B — Generar el Long-Lived Access Token](#parte-b--generar-el-long-lived-access-token)
4. [Parte C — Configurar el plugin en OpenACM](#parte-c--configurar-el-plugin-en-openacm)
5. [Parte D — Probar](#parte-d--probar)
6. [Sobre `area` — un detalle importante](#6-sobre-area--un-detalle-importante)
7. [Problemas comunes](#7-problemas-comunes)

---

## 1. Cómo funciona

OpenACM no habla directamente con tus dispositivos (bombillos Tuya, enchufes
Xiaomi, TV LG, etc.) — le habla a **Home Assistant**, y es Home Assistant
quien ya sabe hablar con cada marca por su cuenta. OpenACM solo necesita:

- La **URL** de tu Home Assistant (ej. `http://homeassistant.local:8123`).
- Un **Long-Lived Access Token** (una llave de acceso que generas una sola vez).

```
Tú (chat/voz/dashboard) ─► OpenACM ─► Home Assistant ─► tus dispositivos reales
                                     (REST + WebSocket)
```

La conexión es en dos vías: OpenACM llama a servicios de Home Assistant
(`turn_on`, `set_temperature`, etc.) y además mantiene un WebSocket abierto
para enterarse al instante cuando algo cambia (aunque lo hayas cambiado desde
la app de Home Assistant o un interruptor físico) — así el dashboard de
OpenACM siempre muestra el estado real, no uno desactualizado.

Si ya tienes Home Assistant corriendo, salta a la [Parte B](#parte-b--generar-el-long-lived-access-token).

---

## Parte A — Instalar Home Assistant con Docker

Si no tienes Home Assistant, la forma más simple de correrlo junto a OpenACM
es con Docker Compose.

**1. Crea una carpeta para sus datos** (fuera del repo de OpenACM, para que
sobreviva actualizaciones):

```bash
mkdir -p ~/homeassistant/config
```

**2. Agrega el servicio a tu `docker-compose.yml`** (puede ser el mismo
archivo donde corre OpenACM, o uno aparte):

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    restart: unless-stopped
    network_mode: host   # necesario para descubrir dispositivos en tu LAN
    volumes:
      - ~/homeassistant/config:/config
      - /etc/localtime:/etc/localtime:ro
```

> `network_mode: host` es importante: muchos protocolos de descubrimiento de
> dispositivos IoT (SSDP, mDNS, etc.) no funcionan bien detrás del NAT normal
> de Docker. Si tu NAS/servidor no soporta `network_mode: host` (algunos
> sistemas como Synology lo restringen), puedes correr sin él, pero tendrás
> que agregar tus integraciones manualmente en vez de por auto-descubrimiento.

**3. Levanta el contenedor:**

```bash
docker compose up -d homeassistant
```

**4. Entra a la configuración inicial:** abre `http://<tu-servidor>:8123` en
el navegador, crea tu usuario administrador, y sigue el asistente (Home
Assistant detecta automáticamente muchos dispositivos en tu red — luces,
TVs, etc. — y te ofrece agregarlos ahí mismo).

**5. Agrega tus dispositivos/integraciones reales** desde
**Configuración → Dispositivos y servicios → Agregar integración** — busca la
marca de tus dispositivos (Tuya, Xiaomi Miio, LG WebOS, etc.). Esto reemplaza
completamente lo que antes hacían los drivers propios de OpenACM: Home
Assistant ya tiene soporte oficial y mejor mantenido para cientos de marcas.

---

## Parte B — Generar el Long-Lived Access Token

1. En Home Assistant, entra a tu **perfil de usuario** (ícono con tu nombre,
   abajo a la izquierda del menú).
2. Baja hasta la sección **"Tokens de acceso de larga duración"** (*Long-Lived
   Access Tokens*), al final de la pestaña "Seguridad".
3. Click en **"Crear token"**, dale un nombre (ej. `openacm`), y
   **cópialo de inmediato** — Home Assistant solo te lo muestra una vez.

Guarda ese token en un lugar seguro temporalmente (lo vas a pegar en el paso
siguiente).

---

## Parte C — Configurar el plugin en OpenACM

1. Abre el dashboard de OpenACM y entra a **`/plugins`**.
2. Busca `home_assistant` en la lista y haz click en **"Configurar"**.
3. Llena los dos campos:
   - **URL de Home Assistant**: ej. `http://homeassistant.local:8123` o
     `http://<ip-de-tu-servidor>:8123`.
   - **Long-Lived Access Token**: pega el token que generaste en la Parte B.
4. Guarda. Vas a ver el banner "Reinicia para aplicar" — reinicia OpenACM
   (botón en el mismo banner, o `run.bat`/tu proceso normal).

Al reiniciar, el plugin se conecta automáticamente y trae el estado de todos
tus dispositivos.

---

## Parte D — Probar

- **Dashboard:** entra a **`/home-assistant`** — deberías ver tus
  dispositivos agrupados por tipo (luces, enchufes, clima, etc.), con su
  estado actual. Prueba el botón de encender/apagar en alguno.
- **Tiempo real:** cambia algo desde la app real de Home Assistant (o un
  interruptor físico) y confirma que la página de OpenACM se actualiza sola
  en un par de segundos, sin refrescar.
- **Chat/voz**, prueba frases como:
  - "¿qué dispositivos tengo?"
  - "enciende la luz de la sala"
  - "pon la luz de la sala al 50% de brillo"
  - "¿cuál es el estado del termostato?"
  - "activa la escena modo noche" (si tienes una escena configurada)

---

## 6. Sobre `area` — un detalle importante

Puedes decirle al agente "apaga todas las luces de la sala" para controlar
una zona completa en una sola acción, pero eso solo funciona bien si el
**área en Home Assistant** tiene el mismo identificador que usas al hablar.
Home Assistant identifica cada área por un **ID/slug** (ej. `sala`,
`living_room`), no por el nombre bonito que le pusiste — si le dices un
nombre que no coincide exactamente con ese ID, la acción "funciona" (no da
error) pero en realidad no mueve ningún dispositivo, porque no encontró esa
área.

Para evitar sorpresas: revisa el nombre exacto de tus áreas en
**Configuración → Áreas** dentro de Home Assistant, y úsalo tal cual al
hablarle al agente (o usa `entity_id`/nombres de dispositivos individuales,
que sí tienen coincidencia flexible por nombre).

---

## 7. Problemas comunes

| Problema | Causa probable / solución |
|---|---|
| El plugin queda "inactivo" después de guardar la config | Falta reiniciar OpenACM — los cambios de `/plugins` solo aplican al reiniciar. |
| "Token de Home Assistant inválido o expirado" | El token se borró o revocó desde Home Assistant (perfil → tokens). Genera uno nuevo y vuelve a guardarlo en `/plugins`. |
| El dashboard no muestra ningún dispositivo | Confirma que la URL es alcanzable desde donde corre OpenACM (mismo LAN/Docker network), y que agregaste al menos una integración/dispositivo dentro de Home Assistant mismo. |
| "apaga todas las luces de la sala" no hace nada mal | Revisa la sección [6](#6-sobre-area--un-detalle-importante) — probablemente el nombre del área no coincide con el ID real en Home Assistant. |
| Los cambios físicos (apagar desde un switch) tardan en reflejarse en OpenACM | Confirma que el WebSocket de Home Assistant sigue conectado — revisa los logs de OpenACM por mensajes de reconexión (`HA WebSocket error, reconnecting`). Si tu Home Assistant se reinició, la reconexión es automática (con espera creciente hasta 30s). |
| Quiero volver a usar los drivers viejos (Tuya/LG TV/Miio directos) | Ya no existen — fueron reemplazados por completo por este plugin. Configura esos dispositivos dentro de Home Assistant (que tiene mejor soporte oficial para cada marca) y todo vuelve a funcionar igual, vía Home Assistant. |
