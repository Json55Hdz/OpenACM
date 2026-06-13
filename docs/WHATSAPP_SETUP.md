# Configuración de WhatsApp (Cloud API oficial de Meta)

Guía completa para conectar OpenACM a WhatsApp usando la **API oficial de Meta**
(WhatsApp Cloud API). Es la vía recomendada: **sin riesgo de que te baneen el
número**, a diferencia de whatsapp-web.js.

> **Resultado final:** los vecinos del conjunto le escriben a tu número de
> WhatsApp Business y el bot les responde de forma individual y automática.

---

## Índice

1. [Cómo funciona (en 1 minuto)](#1-cómo-funciona)
2. [Costos](#2-costos)
3. [Parte A — Meta / WhatsApp](#parte-a--meta--whatsapp)
4. [Parte B — URL pública con Cloudflare Tunnel](#parte-b--url-pública-con-cloudflare-tunnel)
5. [Parte C — Configurar OpenACM](#parte-c--configurar-openacm)
6. [Parte D — Conectar el webhook en Meta](#parte-d--conectar-el-webhook-en-meta)
7. [Parte E — Probar](#parte-e--probar)
8. [Parte F — Pasar a producción](#parte-f--pasar-a-producción)
9. [Reglas que NO debes romper](#9-reglas-que-no-debes-romper)
10. [Problemas comunes](#10-problemas-comunes)

---

## 1. Cómo funciona

- **Enviar** (bot → persona): OpenACM llama directo a la API de Meta por HTTPS. No
  necesita nada público.
- **Recibir** (persona → bot): Meta **empuja** cada mensaje a una **URL pública
  tuya** (un *webhook*). Por eso necesitas exponer OpenACM con una URL HTTPS fija
  → eso lo resuelve **Cloudflare Tunnel** (gratis y permanente).

```
Vecino  ─►  WhatsApp/Meta  ─►  https://tudominio/webhooks/whatsapp  ─►  OpenACM (tu PC)
OpenACM ─►  Graph API de Meta  ─►  WhatsApp  ─►  Vecino
```

---

## 2. Costos

| Concepto | Costo |
|---|---|
| Cuenta Meta for Developers | **Gratis** |
| WhatsApp Cloud API (la API en sí) | **Gratis** |
| Número de prueba de Meta | **Gratis** (limitado a 5 destinatarios) |
| **Conversaciones de servicio** (un usuario te escribe y respondes dentro de 24 h) | **Gratis e ilimitadas** (desde jul-2025) |
| Mensajes con **plantilla** que TÚ inicias (marketing / utilidad / autenticación) | **Se cobran por mensaje** (varía por país; en Colombia son centavos de USD) |
| Cloudflare Tunnel | **Gratis** |
| Dominio propio (para URL fija del túnel) | **~10 USD/año** (opcional pero recomendado) |
| Cuenta de WhatsApp Business | **Gratis** |

**Para tu caso (vecinos te escriben y el bot responde):** son **conversaciones de
servicio → gratis**. Solo pagarías si TÚ inicias conversaciones masivas con
plantillas (anuncios fuera de la ventana de 24 h).

> Nota: los precios de plantillas cambian y dependen del país. Revisa el precio
> actual en la [tabla oficial de Meta](https://developers.facebook.com/docs/whatsapp/pricing).

---

## Parte A — Meta / WhatsApp

### A.1 Crear la app

1. Entra a **https://developers.facebook.com/** e inicia sesión con tu Facebook.
2. Acepta registrarte como desarrollador si te lo pide.
3. **My Apps → Create App**.
4. Caso de uso: elige **"Other"** → tipo **"Business"**.
5. Ponle un nombre (ej. `OpenACM Conjunto`) y créala.

### A.2 Agregar el producto WhatsApp

1. Dentro de la app, en **Add products**, busca **WhatsApp → Set up**.
2. Te pedirá asociar un **Meta Business Account** (créalo si no tienes uno; es gratis).
3. Al entrar a WhatsApp → **API Setup**, Meta te da automáticamente:
   - Un **número de prueba** (test number).
   - Un **Phone number ID**  ← lo necesitas.
   - Un **WhatsApp Business Account ID**.
   - Un **token temporal** (dura 24 h) ← sirve para probar ya mismo.

### A.3 Anotar los datos

De la pantalla **API Setup**, copia y guarda:

| Dato | Dónde va en OpenACM |
|---|---|
| **Temporary access token** | `WHATSAPP_ACCESS_TOKEN` |
| **Phone number ID** | `WHATSAPP_PHONE_NUMBER_ID` |

> El token temporal vence en 24 h. Para algo permanente, ver [Parte F](#parte-f--pasar-a-producción).

### A.4 Agregar tu número de prueba como destinatario

En **API Setup → "To"**, agrega tu número personal de WhatsApp para poder probar
(en modo prueba solo puedes mandar/recibir con hasta 5 números que registres).

### A.5 Obtener el App Secret

1. Ve a **App settings → Basic** (configuración de la app).
2. Copia el **App Secret** (dale "Show"). ← `WHATSAPP_APP_SECRET`
   - Sirve para que OpenACM verifique que los webhooks vienen de verdad de Meta.

### A.6 Inventar un Verify Token

Inventa una cadena cualquiera, por ejemplo `openacm-conjunto-2026`.  ← `WHATSAPP_VERIFY_TOKEN`
La usarás en OpenACM **y** en la config del webhook de Meta (deben coincidir).

---

## Parte B — URL pública con Cloudflare Tunnel

Necesitas una URL HTTPS fija que apunte a tu PC. Cloudflare Tunnel es gratis,
permanente y se instala como servicio de Windows.

> **Requisito para URL fija:** un dominio en Cloudflare. Si no tienes, compra uno
> barato (~10 USD/año) y agrégalo al plan **Free** de Cloudflare. (Existe un túnel
> rápido sin dominio que da una URL `trycloudflare.com`, pero **cambia cada vez que
> reinicias** → no sirve para un webhook permanente.)

### B.1 Instalar cloudflared

1. Descarga `cloudflared` para Windows: https://github.com/cloudflare/cloudflared/releases
   (archivo `cloudflared-windows-amd64.exe`, renómbralo a `cloudflared.exe`).
2. Abre PowerShell y autentícate:
   ```powershell
   cloudflared tunnel login
   ```
   Se abre el navegador → elige tu dominio.

### B.2 Crear el túnel

```powershell
cloudflared tunnel create openacm
cloudflared tunnel route dns openacm wa.tudominio.com
```
Esto crea el túnel y apunta `wa.tudominio.com` hacia él.

### B.3 Configurar qué expone

Crea el archivo `C:\Users\TU_USUARIO\.cloudflared\config.yml`:

```yaml
tunnel: openacm
credentials-file: C:\Users\TU_USUARIO\.cloudflared\<ID-DEL-TUNEL>.json

ingress:
  - hostname: wa.tudominio.com
    service: http://localhost:8000   # puerto del servidor web de OpenACM
  - service: http_status:404
```

> Ajusta `8000` al puerto real de OpenACM (revisa `config/default.yaml → web.port`).

### B.4 Correrlo como servicio (siempre encendido)

```powershell
cloudflared service install
```
Listo: tu webhook quedará en **`https://wa.tudominio.com/webhooks/whatsapp`**.

---

## Parte C — Configurar OpenACM

Edita (o crea) `config/.env` en la carpeta de OpenACM y agrega:

```env
WHATSAPP_ACCESS_TOKEN=EAAG...tu_token
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_VERIFY_TOKEN=openacm-conjunto-2026
WHATSAPP_APP_SECRET=abcd1234...tu_app_secret
```

> `config/.env` está en `.gitignore` — tus credenciales **nunca** se suben a git.
> Cada persona que instale OpenACM pone las suyas; el código es el mismo para todos.

En `config/default.yaml`, asegúrate de tener:

```yaml
channels:
  whatsapp:
    enabled: true
    mode: cloud_api
```

> Con las variables de entorno puestas, OpenACM **auto-activa** el canal aunque
> `enabled` esté en `false`.

Reinicia OpenACM. En el log deberías ver `WhatsApp Cloud API connected`.

---

## Parte D — Conectar el webhook en Meta

1. En tu app de Meta → **WhatsApp → Configuration → Webhooks → Edit**.
2. **Callback URL:** `https://wa.tudominio.com/webhooks/whatsapp`
3. **Verify token:** el mismo que pusiste en `WHATSAPP_VERIFY_TOKEN`.
4. Clic en **Verify and save**. Meta llamará a tu URL; si todo está bien, queda en verde.
5. En **Webhook fields**, suscríbete a **`messages`** (clic en *Subscribe*).

---

## Parte E — Probar

1. Desde tu WhatsApp personal (el que registraste en A.4), escríbele al número de
   prueba de Meta.
2. El bot debería responder en segundos.
3. Si no responde, revisa [Problemas comunes](#10-problemas-comunes) y los logs de OpenACM.

---

## Parte F — Pasar a producción

El número de prueba sirve para validar, pero para el conjunto necesitas tu número real:

1. **Token permanente:** en *Business Settings → Users → System Users*, crea un
   System User, asígnale la app y genera un token permanente con permisos
   `whatsapp_business_messaging` y `whatsapp_business_management`. Reemplaza
   `WHATSAPP_ACCESS_TOKEN`.
2. **Número propio:** en **WhatsApp → API Setup → Add phone number**. Ese número
   **no puede estar registrado en WhatsApp normal** (si lo está, primero bórralo de
   la app de WhatsApp). Lo verificas por SMS/llamada.
3. **Verificación del negocio (Business Verification):** Meta la pide para subir los
   límites de envío. Necesitas datos del negocio/persona. Puedes empezar sin ella en
   un nivel básico (hasta ~250–1.000 conversaciones/día) y verificar después.
4. **Plantillas:** si quieres mandar anuncios a todos (fuera de la ventana de 24 h),
   crea y envía a aprobación **Message Templates** en el Business Manager.

---

## 9. Reglas que NO debes romper

- **Ventana de 24 horas:** puedes responder libre **dentro de las 24 h** desde el
  último mensaje del usuario. Fuera de eso, solo con plantillas aprobadas.
- **Opt-in:** la gente debe haber aceptado que le escribas.
- **Calidad:** si te reportan/bloquean mucho, Meta baja tu *quality rating* y limita
  tus envíos. Uso legítimo = sin problema.
- **Nada de spam.** Con esto **no te banean el número** (esa es la ventaja de la vía
  oficial), pero sí pueden restringir el envío si abusas.

---

## 10. Problemas comunes

| Síntoma | Causa probable / solución |
|---|---|
| Webhook no verifica (no se pone verde) | El `verify_token` no coincide, o la URL no es accesible. Prueba abrir `https://wa.tudominio.com/webhooks/whatsapp` en el navegador. |
| El bot no recibe mensajes | ¿Te suscribiste al campo **messages**? ¿El túnel está corriendo? ¿Apunta al puerto correcto de OpenACM? |
| `signature invalid` en los logs | El `WHATSAPP_APP_SECRET` está mal o vacío. |
| `WhatsApp Cloud API credential check failed` | Token vencido (el temporal dura 24 h) o `phone_number_id` incorrecto. |
| Envía pero no recibe | El webhook (recibir) no está conectado; enviar funciona sin túnel, recibir no. |
| Solo responde a 5 personas | Sigues en modo prueba. Pasa a producción (Parte F). |

---

**Resumen de credenciales que necesitas:**

```env
WHATSAPP_ACCESS_TOKEN=      # A.3 (temporal) o F.1 (permanente)
WHATSAPP_PHONE_NUMBER_ID=   # A.3
WHATSAPP_VERIFY_TOKEN=      # A.6 (lo inventas tú)
WHATSAPP_APP_SECRET=        # A.5
```

Webhook: `https://TU-DOMINIO/webhooks/whatsapp`
