# Configuración de Gmail API para OpenACM

## ¿Tiene costo?

**No. El Gmail API es completamente gratuito.**

| Operación | Cuota gratuita |
|---|---|
| Leer emails (`messages.list`, `messages.get`) | 1,000,000,000 unidades/día |
| Enviar emails (`messages.send`) | 500 emails/día (cuenta personal) |
| Modificar labels (marcar leído, aplicar etiquetas) | Incluido en la cuota |

Solo pagarías si activas otros servicios de pago en Google Cloud (VMs, BigQuery, etc.). Para Gmail API únicamente: **$0**.

---

## Pasos de configuración

### 1. Crear proyecto en Google Cloud

1. Ve a [console.cloud.google.com](https://console.cloud.google.com)
2. Haz clic en el selector de proyecto (arriba a la izquierda)
3. Selecciona **"Nuevo proyecto"**
4. Ponle un nombre (ej: `OpenACM`) → **Crear**

---

### 2. Activar la Gmail API

1. En el menú lateral: **APIs y servicios** → **Biblioteca**
2. Busca `Gmail API`
3. Haz clic en ella → **Habilitar**

---

### 3. Configurar la pantalla de consentimiento OAuth

1. **APIs y servicios** → **Pantalla de consentimiento de OAuth**
2. Tipo de usuario: **Externo** (aunque sea solo para ti)
3. Llena:
   - Nombre de la app: `OpenACM`
   - Email de soporte: tu Gmail
4. En la sección **"Usuarios de prueba"**: agrega tu propio Gmail
   > Esto es crítico — si no te agregas aquí, no podrás autorizar la app
5. Guarda y continúa (los demás campos son opcionales)

---

### 4. Crear las credenciales OAuth 2.0

1. **APIs y servicios** → **Credenciales**
2. **+ Crear credenciales** → **ID de cliente OAuth**
3. Tipo de aplicación: **Aplicación de escritorio**
4. Nombre: `OpenACM Local` → **Crear**
5. En la ventana que aparece, haz clic en **Descargar JSON**

---

### 5. Guardar el archivo en el proyecto

Renombra el archivo descargado y colócalo aquí (relativo a la raíz del proyecto):

```
config/google_credentials.json
```

---

### 6. Primera autorización

La primera vez que uses cualquier herramienta de Gmail desde el chat (ej: *"lee mis emails"*), el sistema abrirá el navegador automáticamente con el flujo OAuth:

1. Selecciona tu cuenta de Gmail
2. Acepta los permisos solicitados
3. Cierra la ventana del navegador

El token se guarda en `config/google_token.json` y no necesitas repetir este paso.

---

## Permisos (scopes) que solicita el sistema

| Scope | Para qué se usa |
|---|---|
| `gmail.modify` | Leer emails, marcar leído/no leído, aplicar etiquetas |
| `calendar` | Crear y leer eventos del calendario |
| `drive` | Listar y subir archivos en Drive |
| `youtube.readonly` | Buscar videos en YouTube |

> Todos estos scopes son gratuitos y ya están configurados en `src/openacm/tools/google_services.py`.

---

## Archivos resultantes

```
config/
├── google_credentials.json   ← descargas de Google Cloud (paso 4)
└── google_token.json         ← se genera automáticamente en el primer login
```

Una vez que `google_token.json` existe, el plugin Gmail Classifier mostrará la interfaz completa en lugar de la pantalla de configuración.

---

## Solución de problemas

| Problema | Causa probable | Solución |
|---|---|---|
| "Access blocked" al autorizar | No te agregaste como usuario de prueba | Agrega tu Gmail en el paso 3 |
| "File not found: google_credentials.json" | Archivo en ruta incorrecta | Verifica que esté en `config/google_credentials.json` |
| El token expira | Token vencido | Elimina `config/google_token.json` y vuelve a autorizar |
| "Quota exceeded" | Muy poco probable en uso normal | Espera unos minutos e intenta de nuevo |
