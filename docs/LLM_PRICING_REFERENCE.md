# ¿Cuánto cuesta usar IA en OpenACM?

> Precios actualizados a junio 2026.

---

## ¿Cómo funciona?

OpenACM puede conectarse a diferentes servicios de inteligencia artificial para procesar los correos. Tú eliges cuál usar según precio y calidad. Todos se conectan igual, solo cambias una línea de configuración.

---

## Servicios disponibles

### De pago (API)

Pagas según cuánto uses — sin suscripción mensual fija.

| Servicio | Empresa | Precio entrada | Precio salida | Ventaja principal |
|---|---|---|---|---|
| **Claude Haiku 4.5** | Anthropic | $1.00 / 1M tokens | $5.00 / 1M tokens | Mejor comprensión de español |
| **Claude Sonnet 4.6** | Anthropic | $3.00 / 1M tokens | $15.00 / 1M tokens | Muy alta precisión |
| **Claude Opus 4** | Anthropic | $5.00 / 1M tokens | $25.00 / 1M tokens | El más capaz de Anthropic |
| **GPT-4.1** | OpenAI | $2.00 / 1M tokens | $8.00 / 1M tokens | Muy conocido y confiable |
| **Gemini 2.5 Flash** | Google | $0.30 / 1M tokens | $2.50 / 1M tokens | Económico + tiene nivel gratis ⚠️ |
| **Gemini 2.5 Flash-Lite** | Google | $0.10 / 1M tokens | $0.40 / 1M tokens | El más barato de Google ⚠️ |
| **Mistral Medium 3.5** | Mistral AI | $1.50 / 1M tokens | $7.50 / 1M tokens | Empresa europea, datos en Europa |
| **DeepSeek v4 Flash** | DeepSeek | $0.14 / 1M tokens | $0.28 / 1M tokens | Muy barato, calidad sorprendente |
| **DeepSeek v4 Pro** | DeepSeek | $0.44 / 1M tokens | $0.87 / 1M tokens | Alta calidad a bajo precio |
| **Kimi K2.6** | Moonshot AI | $0.95 / 1M tokens | $4.00 / 1M tokens | Modelo incluido en OpenCode Go |

> **¿Qué es un token?** Aproximadamente 4 caracteres de texto. "Hola, ¿cómo estás?" son ~5 tokens.
>
> ⚠️ **Nota sobre modelos Flash (Google):** Los modelos Flash son más económicos porque son versiones más ligeras. Pueden cometer más errores de clasificación que modelos más completos como Claude Haiku o Kimi K2.6. Para correos de baja criticidad están bien; para correos importantes, mejor usar un modelo más robusto.

---

### Por suscripción mensual (CLI)

Estos funcionan como programas instalados en tu computadora. El costo de la IA ya está incluido en la suscripción — no pagas por correo ni por uso. Y lo mejor: **la misma suscripción te da acceso a un asistente de IA completo para programar, redactar, analizar archivos y mucho más**, no solo para los correos.

| Servicio | Empresa | Suscripción | Qué incluye además de los correos |
|---|---|---|---|
| **Claude Code** (Claude CLI) | Anthropic | ~$20–$100 / mes | Asistente de código, análisis de archivos, automatizaciones, agentes |
| **Gemini CLI** | Google | ~$20 / mes (Google One AI Premium) | Gemini en todos los productos Google, Workspace, generación de imágenes |
| **OpenCode Go** | Open Source | $10 / mes | Asistente de código en terminal — incluye acceso a **Kimi K2.6**, DeepSeek, y otros modelos de alta calidad |
| **Ollama** (local) | Comunidad | Gratis (hardware propio) | Modelos corriendo en tu propia máquina, sin internet, sin límites |

> **Clave:** Con Claude Code o Gemini CLI, el uso en OpenACM se descuenta del mismo plan que ya estás pagando para trabajar con IA todo el día. Los correos salen "de propina".

---

## ¿Cuánto gastaría con 300 correos al día?

El clasificador de correos procesa los mensajes en grupos de 20, lo que lo hace muy eficiente.

### ¿Por qué es tan barato el clasificador?

Puede parecer poco, pero hay dos razones concretas:

1. **Procesa 20 correos por llamada** (no uno por uno) → 300 correos al día = solo 15 llamadas al LLM
2. **Solo lee el asunto + remitente + un extracto de 200 caracteres** del correo, no el cuerpo completo

Si cada correo fuera una llamada individual leyendo el body completo, el costo sería 10–20x mayor. La eficiencia viene del diseño por lotes.

---

### Costo único de arranque (backfill del último mes)

La primera vez que se activa el plugin, lo ideal es procesar los últimos 30 días de correos para que el sistema tenga contexto histórico. Eso son **9,000 correos de una sola vez**.

| | Arranque (9,000 correos, única vez) | Operación mensual (300/día × 30 días) |
|---|---|---|
| Correos procesados | 9,000 | 9,000 |
| Llamadas al LLM | 450 | 450 |
| Tokens entrada | ~537,000 | ~537,000 |
| Tokens salida | ~124,000 | ~124,000 |

> El costo del backfill inicial es **exactamente igual** a un mes de operación normal — porque es la misma cantidad de correos. En la práctica, significa que el primer mes pagas el doble (arranque + operación), y del segundo mes en adelante solo pagas la operación mensual.

**Ejemplo con Claude Haiku 4.5:** primer mes ~$2.32 (arranque + operación), segundo mes en adelante ~$1.16/mes.

---

### Costo mensual en operación normal (30 días):

| Servicio | Costo al mes | Nota |
|---|---|---|
| 🥇 **Gemini 2.5 Flash** | **$0.00** | Nivel gratis de Google: hasta 250 requests/día — nuestros 300 correos solo usan 15 requests/día ✅ |
| 🥈 **DeepSeek v4 Flash** | **$0.11** | Menos de un dólar al mes |
| 🥉 **Gemini 2.5 Flash-Lite** | **$0.10** | El más barato de pago |
| **DeepSeek v4 Pro** | $0.34 | Buena relación calidad-precio |
| **Claude Haiku 4.5** | $1.16 | Mejor comprensión en español |
| **Kimi K2.6** *(via OpenCode Go)* | $1.00 | Alta calidad, incluido en suscripción de $10/mes |
| **Mistral Medium 3.5** | $1.73 | Opción si los datos deben estar en Europa |
| **GPT-4.1** | $2.06 | Alternativa sólida de OpenAI |
| **Claude Sonnet 4.6** | $3.47 | Alta precisión para correos complejos |
| **Claude Opus 4** | $5.78 | Máxima calidad, overkill para clasificación simple |

> **Fuente nivel gratis Gemini:** [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) — los límites exactos varían por cuenta. El límite publicado actualmente es 250 requests/día para Gemini 2.5 Flash.
>
> **Fuente precios Kimi K2.6:** [openrouter.ai/moonshotai/kimi-k2.6](https://openrouter.ai/moonshotai/kimi-k2.6)

---

## Funcionalidad adicional: Auto-redacción de respuestas

A diferencia del clasificador, la auto-redacción **no puede hacer batches** — cada correo necesita su propia llamada al LLM porque la respuesta es personalizada. Además, necesita leer el cuerpo completo del correo para redactar una respuesta coherente. Esto lo hace significativamente más caro.

**Supuestos por correo auto-redactado:**
- Instrucciones + contexto del sistema: ~500 tokens de entrada
- Cuerpo del correo (promedio): ~400 tokens de entrada
- Borrador de respuesta generado: ~200 tokens de salida
- **Total por correo: ~900 tokens entrada + ~200 tokens salida**

> No todos los correos van a necesitar auto-respuesta. El costo depende de qué porcentaje se activa esta función.

### Costo mensual de auto-redacción según volumen

| Correos auto-redactados/día | Claude Haiku 4.5 | Gemini 2.5 Flash | **Kimi K2.6 (OpenCode Go)** | DeepSeek v4 Flash |
|---|---|---|---|---|
| **30/día** (10% del total) | USD 1.71 | USD 0.69 | **Incluido en plan** | USD 0.16 |
| **90/día** (30% del total) | USD 5.13 | USD 2.08 | **Incluido en plan** | USD 0.49 |
| **150/día** (50% del total) | USD 8.55 | USD 3.47 | **Incluido en plan** | USD 0.82 |
| **300/día** (100% del total) | USD 17.10 | USD 6.93 | **Incluido en plan** | USD 1.64 |

> Con OpenCode Go (USD 10/mes), el uso de Kimi K2.6 para todos estos volúmenes cabe dentro del límite mensual del plan (USD 60 de consumo real). No se paga extra.

### Costo total combinado (clasificación + auto-redacción)

Asumiendo que el **30% de los correos** (90/día) reciben auto-respuesta:

| Modelo | Clasificación/mes | Auto-redacción/mes | **Total/mes** |
|---|---|---|---|
| **Kimi K2.6 (OpenCode Go)** | Incluido | Incluido | **USD 10.00 fijos** ⭐ |
| DeepSeek v4 Flash | USD 0.11 | USD 0.49 | **USD 0.60** |
| Gemini 2.5 Flash | USD 0.00 | USD 2.08 | **USD 2.08** |
| Claude Haiku 4.5 | USD 1.16 | USD 5.13 | **USD 6.29** |
| GPT-4.1 | USD 2.06 | USD 6.08 | **USD 8.14** |
| Claude Sonnet 4.6 | USD 3.47 | USD 20.25 | **USD 23.72** |

> **Nota importante:** La auto-redacción multiplica el costo mucho más que la clasificación. OpenCode Go a USD 10/mes fijos es la opción más predecible — sin sorpresas en la factura.

---

## Recomendación

### ⭐ Opción recomendada: OpenCode Go (USD 10/mes, todo incluido)

**OpenCode Go incluye los tokens en el plan** — no pagas API por separado. Por USD 10/mes tienes acceso a Kimi K2.6 y una docena de modelos más, con un límite de uso de USD 60/mes en consumo real de tokens.

Para nuestro caso (300 correos/día clasificados + 30% auto-redactados), el consumo estimado de tokens sería **~USD 6.13/mes** — estamos muy lejos del límite de USD 60, así que la suscripción básica sobra ampliamente.

| | Con OpenCode Go (USD 10/mes) |
|---|---|
| Clasificación de 300 correos/día | Incluido |
| Auto-redacción del 30% de correos | Incluido |
| Modelo usado | Kimi K2.6 (alta calidad) |
| Uso estimado del límite mensual | ~USD 6.13 de USD 60.00 (10%) |
| **Costo total mensual** | **USD 10.00 fijos** |
| Bonus | Asistente de código completo para el equipo |

**¿Por qué es la mejor opción a largo plazo?**
OpenACM está en constante crecimiento — cada nueva funcionalidad (resumen de correos, respuestas automáticas, alertas inteligentes, integración con calendarios, etc.) consume más tokens. Con OpenCode Go, activar cualquier funcionalidad nueva **no genera un costo adicional** mientras el consumo total no supere los USD 60/mes de tope. Con las funcionalidades actuales solo usamos el 10% de ese límite, lo que deja margen para seguir ampliando sin revisar presupuestos ni cambiar de plan.

Fuente: [opencode.ai/go](https://opencode.ai/go) · [opencode.ai/docs/go](https://opencode.ai/docs/go/)

---

### Otras opciones si no se quiere suscripción fija

**Solo clasificación (300 correos/día):**
- Gratis: Gemini 2.5 Flash (dentro del free tier de Google)
- Más económico de pago: DeepSeek v4 Flash (USD 0.11/mes)
- Mejor calidad en español: Claude Haiku 4.5 (USD 1.16/mes)

**Clasificación + auto-redacción (30% de correos):**
- Más económico: DeepSeek v4 Flash (USD 0.60/mes total)
- Más equilibrado: Gemini 2.5 Flash (USD 2.08/mes)
- Evitar Sonnet o Opus para auto-redacción masiva — escala rápido a más de USD 20/mes

---

> Los precios pueden variar. Fuentes verificadas: [Anthropic](https://docs.anthropic.com/en/docs/about-claude/pricing) · [Google](https://ai.google.dev/gemini-api/docs/pricing) · [OpenAI](https://developers.openai.com/api/docs/pricing) · [Mistral](https://mistral.ai/pricing/) · [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing) · [Kimi/OpenRouter](https://openrouter.ai/moonshotai/kimi-k2.6)
