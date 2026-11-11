# Acta de Reunión y Compromisos — Integración Chatbot EEP / Flujo Agéntico de Reporte de Daños

**Fecha:** 7 de julio de 2026, 3:19 p.m.
**Duración:** 1h 48m
**Proyecto:** Integración del flujo agéntico con el chatbot existente de WhatsApp de la Empresa de Energía de Pereira (EEP), opción "Reportar daño" (Opción 4), conectado al sistema de gestión técnica de Centro de Control (EventTrack) de Mauricio Frye.

## Asistentes

| Nombre | Rol en el proyecto |
|---|---|
| Edgar Mauricio Frye | Desarrollador y dueño del sistema de Centro de Control — API de órdenes de trabajo, comercial |
| Rafael Valencia Guarín | Centro de Control / Operación línea 115 — reglas regulatorias y operativas |
| Andrés | A cargo del chatbot actual de EEP — WhatsApp Business e IVR |
| Andre Garcia Cristancho | Equipo con Jeison — apoyo en el diseño e implementación del flujo |
| Jeison David Hernandez Peña | Desarrollo del flujo agéntico y de la IA — integración y orquestación |

---

## 1. Alcance acordado

Automatizar, mediante un flujo agéntico orientado a eventos, apoyado en webhooks e IA, el proceso que hoy hace manualmente una persona de la oficina cuando llega un chat de WhatsApp: tomar la matrícula, consultarla en el sistema de Mauricio, generar la orden de trabajo si aplica, e informar al cliente. La asignación de la orden a una cuadrilla sigue siendo 100% manual, autonomía de Centro de Control — no se automatiza en esta fase.

No se toca el canal de llamadas actual; el objetivo es migrar progresivamente el volumen de llamadas hacia el chat.

---

## 2. Arquitectura acordada

```
Usuario → WhatsApp Business (menú existente) → Opción 4 "Reportar daño"
   → Pregunta 1: ¿Pereira o Cartago? — son bases de datos/empresas distintas
   → Pregunta 2: Número de matrícula
   → Andrés reenvía estos datos y el ID de chat al flujo agéntico
   → Flujo agéntico consulta el API único de Mauricio ("por situación") con matrícula + empresa
   → Mauricio retorna un código/situación:
        a) Ya existe orden / consignación / suspensión programada → se informa al usuario
        b) Matrícula sin viabilidad (no ha pagado) → se informa al usuario
        c) Daño masivo activo, integración SPARD pendiente con Víctor → se informa, no se crea orden nueva
        d) Nada de lo anterior → se genera la orden de trabajo (tipo/tag "chatbot") y se retorna el radicado
   → El flujo agéntico arma la respuesta — la IA solo redacta el mensaje final, no toma decisiones de negocio
   → Se devuelve el texto a Andrés, quien lo envía por WhatsApp al usuario
```

Puntos clave de diseño:
- La IA únicamente redacta la respuesta final al cliente con la información ya resuelta por el flujo determinístico. No decide reglas de negocio.
- Los flujos se arman por nodos, estilo n8n: cada flujo es una tool que la IA invoca según la intención detectada — reportar daño → flujo de daños; consultar estado → flujo de estado; hablar con asesor humano → deriva a Opción 2 sin generar nada.
- Arquitectura orientada a eventos vía webhooks, tanto de entrada como de salida.
- La orden que genera el chatbot es la misma orden que ve la cuadrilla en la tablet — no hay duplicidad de sistemas, un solo sistema de origen, el de Mauricio.

---

## 3. Reglas de negocio confirmadas

1. Toda interacción por chat que pase las validaciones debe generar una orden de trabajo — es obligación regulatoria, no se puede omitir por "ya hay muchas órdenes similares".
2. Única excepción: cuando existe un evento de daño masivo confirmado vía SPARD — en ese caso se informa al usuario con un mensaje, sin generar una orden nueva por cada chat.
3. Asociación de órdenes jerárquicas, padre/hijo: se asocian automáticamente solo si pertenecen al mismo transformador, no por circuito. Esta lógica la implementa Mauricio dentro de su API: al crear una orden, verifica si ya existe una abierta para ese transformador y la asocia como hijo.
4. Identificación de origen: las órdenes generadas por este canal deben quedar tipificadas con un tag o tipo nuevo, por ejemplo "chatbot", para poder filtrarlas por origen.
5. Radicado único: toda orden, sin excepción, debe generar un radicado único que se le devuelve al usuario.
6. Dirección/ubicación: se debe confirmar con el usuario la dirección que ya existe en el sistema; si no es exacta, se le pide un punto de referencia adicional. Ese dato se concatena en el campo de observaciones existente; no se reemplaza el campo de dirección, por restricción de la app de la cuadrilla.
7. Trazabilidad obligatoria: todo mensaje recibido y toda respuesta enviada debe quedar registrado en base de datos propia, para poder auditar, igual que hoy se audita el canal de llamadas ante reclamos de "llamé y no me contestaron".
8. Ventana de 24 horas de WhatsApp Business: los mensajes proactivos, por ejemplo notificar el cierre de una orden, solo se pueden enviar gratis dentro de las 24h desde el último mensaje del usuario. A partir de octubre de 2026, Meta cobrará los mensajes fuera de esa ventana — tenerlo en cuenta en el diseño de notificaciones salientes.
9. Multiempresa: el software de Mauricio maneja Pereira y Cartago como bases de datos separadas — nunca se puede consultar una matrícula de una ciudad contra la otra. Por eso la pregunta de ciudad es el primer paso obligatorio del flujo.
10. La asignación de cuadrillas queda fuera de alcance de esta fase — el proceso llega hasta la creación y notificación de la orden.

---

## 4. Compromisos por responsable

### Edgar Mauricio Frye (Centro de Control / EventTrack)
- [ ] Adaptar el API existente de generación de órdenes para que retorne también el estado comercial (pagó / no pagó) bajo el mismo endpoint, basado en "situación".
- [ ] Incluir en la respuesta del API: si existe orden activa, si existe consignación/suspensión programada, y la información histórica/dirección asociada a la matrícula.
- [ ] Crear un nuevo tipo/tag de orden ("chatbot" o similar) para identificar el origen del reporte.
- [ ] Implementar la asociación automática de orden hijo → orden padre cuando coincide el mismo transformador.
- [ ] Habilitar un webhook de cambio de estado de la orden, especialmente al pasar a estado 6 (resuelto), para que el flujo agéntico pueda notificar proactivamente al cliente.
- [ ] Soportar la concatenación de un punto de referencia adicional en el campo de observaciones de la orden.
- [ ] Confirmado: existe entorno de desarrollo/sandbox con base de datos separada de producción — entregar la versión del API apuntando a ese entorno primero.

### Rafael Valencia Guarín (Centro de Control / Operación)
- [ ] Coordinar con Víctor, encargado de SPARD, para definir la consulta/integración que permita detectar un daño masivo activo. Se debe habilitar tanto para Pereira, donde SPARD ya existe, como para Cartago, pendiente por ser una base de datos distinta.
- [ ] Confirmar y definir los destinatarios de la notificación (email/SMS) para órdenes generadas por el chatbot fuera de horario, puntualmente Centro de Control de Cartago en horario nocturno y fines de semana, ya que no tienen operador 115 las 24 horas.

### Andrés (Chatbot / WhatsApp)
- [ ] Diseñar el flujo de entrada dentro de la Opción 4 del chatbot: selección de ciudad (Pereira/Cartago) → número de matrícula → reenvío al flujo agéntico.
- [ ] Generar y entregar un ID de chat único, distinto del ID de llamada del sistema de icono, para trazabilidad, vinculado al radicado de la orden.
- [ ] Encargarse del envío final del mensaje redactado por la IA al usuario vía WhatsApp Business.
- [ ] Confirmar y documentar la restricción de la ventana de 24 horas de WhatsApp Business y el cambio de cobro de Meta desde octubre 2026.

### Jeison David Hernandez Peña y equipo (Flujo agéntico)
Andre Garcia Cristancho trabaja junto con Jeison en el diseño e implementación de esta parte.

- [ ] Construir el flujo agéntico orientado a eventos que reciba los datos desde Andrés, consuma el API de Mauricio, interprete la "situación" devuelta y arme la respuesta final vía IA.
- [ ] Implementar la base de datos local propia con ID de chat, log completo de la conversación, radicado asociado y timestamps, para auditoría de calidad de servicio.
- [ ] Implementar el listener del webhook de cierre de orden, estado 6, de Mauricio para disparar la notificación proactiva al cliente respetando la ventana de 24h.
- [ ] Construir en el dashboard una sección de configuración de notificaciones donde Rafael/Centro de Control puedan definir a quién notificar (email/SMS) cuando se cree una orden por chat fuera de horario.
- [ ] Construir una zona adicional de estadísticas en el dashboard, con las métricas de uso propias del canal chatbot: mensajes recibidos, órdenes generadas, tiempos de respuesta por día y por hora.
- [ ] Diseñar los flujos como nodos reutilizables, estilo n8n: cada flujo es una tool que la IA selecciona según la intención del usuario — reportar daño, consultar estado, o hablar con asesor humano, que deriva a la Opción 2 sin generar orden.
- [ ] Entregar manual/documentación técnica del desarrollo para que otro desarrollador pueda retomarlo en el futuro.
- [ ] Redactar el acta y circularla para aprobación de todos los asistentes.

---

## 5. Seguridad y control de acceso

- Actualmente cualquier persona puede consultar cualquier matrícula con solo el número; se identifica como un riesgo, pero queda abierto sin decisión tomada.
- El personal de atención presencial (ATC/Front) puede tener acceso al chatbot si se requiere; sin embargo, continúan atendiendo bajo su flujo normal actual con el aplicativo de Mauricio.

---

## 6. Puntos abiertos / pendientes de definir

1. Reunión con Víctor de SPARD para especificar la consulta de detección de daño masivo, para Pereira y Cartago.

---

## 7. Próximos pasos

- Se redacta y circula esta acta a los asistentes para visto bueno.
- Una vez aprobada, se inicia el desarrollo del entorno de pruebas contra el API de desarrollo de Mauricio.
- Se agenda una reunión separada con Víctor para la integración de SPARD sobre daño masivo.
