# Guion comercial — Demo Salon Mara

> Chuleta para enseñar el producto Alnora a una dueña de salón / peluquería. Aproximadamente **15-20 minutos** si se siguen todos los pasos. Adapta según interés del cliente.

---

## URLs y datos clave

| Elemento | URL / valor |
|---|---|
| Landing pública del salón demo | `(pendiente de despliegue Railway)` |
| Página comercial demo | `(pendiente)/demo` |
| Panel de la dueña | `(pendiente)/admin` |
| Contraseña del panel | `(la sabe el comercial — no compartir por escrito)` |
| WhatsApp sandbox número | `(pendiente — Twilio nuevo)` |
| WhatsApp palabra clave | `(verificar en Twilio antes de cada demo)` |
| Número Vapi para llamar | `(configurar VAPI_PHONE_NUMBER en Railway antes)` |

---

## Antes de la demo (10 min)

Para que la demo no sea pobre, asegúrate de:

- [ ] **Citas en BD**: el panel admin tiene al menos 20-30 citas variadas en las próximas 2 semanas, repartidas entre los 3 estilistas y los 3 canales. Si no, el calendario y las stats se ven vacíos.
- [ ] **Hora del día**: si haces demo a las 22:00, el bot va a decir "estamos cerrados". Mejor de día.
- [ ] **WhatsApp keyword vigente**: Twilio renueva las palabras clave. Comprueba en https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn que sigue siendo la actual.
- [ ] **Vapi número activo**: marca al número desde tu móvil 1 vez antes de la demo para confirmar que Mara contesta.
- [ ] **Email Resend**: que `gestionalnora@gmail.com` esté abierto en otra pestaña para enseñar la notificación a la dueña en directo.
- [ ] **Tu propio teléfono libre** para hacer la prueba de WhatsApp delante de la clienta sin que tu chat personal aparezca.

---

## Apertura (1 min)

> "Te voy a enseñar **cómo Salón Mara, una peluquería real ficticia**, gestiona citas con IA en los 3 canales que más usa la gente: WhatsApp, web, y llamada por teléfono. Todo lo que veas son escenarios reales. Después te enseño el panel de la dueña y vemos qué te encajaría."

Abre `/demo` en pantalla compartida (es la página comercial pensada para esto).

---

## Bloque 1 — Chat web (3 min)

Click en "Probar el chat web →" desde `/demo`. Llegas a la landing de Salón Mara.

> "Imagínate que esto es la web del salón. Cualquier visitante ve el botón de chat abajo a la derecha."

Pulsa el botón. Escribe en vivo:

```
Hola, quiero corte y color el viernes por la tarde, soy Marta Ruiz, 600111222
```

> "Mira: el bot ya tiene servicios, día, nombre y teléfono de un solo mensaje. Te pregunta solo lo que falta — la hora exacta y si tienes preferencia de estilista."

Bot responde con resumen (estilista asignado + duración total + precio total) y pide confirmación. Escribe:

```
sí
```

> "Cita creada. Marta acaba de tenerla apuntada en menos de 30 segundos sin coger el teléfono. Y el bot ha asignado a Mara directamente porque es la colorista del equipo."

**Punto comercial**: "Esto es el caso fácil. ¿Quieres que pruebe uno raro para que veas cómo aguanta?"

Si la clienta quiere, prueba un caso límite:

```
quiero cita el lunes a las 11
```

> "El salón abre martes a sábado. Mira cómo el bot avisa al instante de que el lunes está cerrado, en lugar de pedirte todos los datos para fallar al final."

---

## Bloque 2 — WhatsApp (4 min)

Vuelve a `/demo`. Click en "Abrir WhatsApp →".

> "WhatsApp es donde está la clienta española. Aquí no hay que descargar nada — usamos un número del salón."

Enseña tu pantalla con el chat WhatsApp ya abierto al número sandbox. Si es la primera vez para ti, escribe la palabra clave del sandbox para iniciar.

Escribe:

```
hola, quiero arreglo de barba el sábado a las 12
```

Sigue la conversación. Cuando dé el resumen y confirmes con `sí`, dile:

> "Ahora que está confirmada, mira esto:"

(Cambia a tu pantalla del email de Resend.)

> "La dueña ya tiene la notificación con todos los datos de la cita en su email, en el momento. Si no le gusta el email, puede ir directo al panel."

**Punto comercial**: "Lo bueno de WhatsApp: la clienta no instala nada. Solo escribe al número del salón como a cualquier amigo."

---

## Bloque 3 — Llamada al agente Mara (4 min)

Vuelve a `/demo`. Pulsa "Llamar al agente →" desde tu móvil (en altavoz para que la clienta lo oiga).

Mara atiende. Pídele cita de forma natural:

```
Hola, soy Carmen, quiero corte y peinado el viernes por la tarde
```

> "Mira: español natural, conversación fluida, voz Azure que suena humana. Y la asignación de estilista es automática — sabe que para corte mujer + brushing puede tirar Lucía."

Si tienes tiempo, prueba un caso de derivación:

```
Mira, quiero hacerme extensiones, ¿qué precios manejáis?
```

Mara debería decir que las extensiones no están en el catálogo y ofrecer pasar el caso a la dueña.

**Punto comercial**: "Esto es las 11:30 cuando estás haciendo mechas. La llamada que normalmente perderías, queda atendida. Y la dueña ve la cita en el panel."

---

## Bloque 4 — Panel de la dueña (5 min)

Abre `/admin` en otra pestaña. Introduce contraseña.

### Tab Calendario

> "Esto es lo que la dueña abre al llegar al salón por la mañana. Calendario semanal con cada cita codificada por color según el canal: azul web, verde WhatsApp, morado voz. Y en el título ves directamente quién es la clienta, quién la atiende y qué servicio."

Click en una cita. Sale el modal.

> "Click en cualquier cita y ves todos los datos: estilista, servicios, teléfono, alergias a tintes si las tiene, notas. Si necesita cancelarla por algún motivo, botón rojo y listo."

### Tab Estadísticas

> "Aquí tiene los KPIs: citas hoy, esta semana, mes. **Por canal** — para saber dónde está captando más clientas. **Por estilista** — para repartir mejor la carga del equipo. **Ingresos estimados** del rango. **Tasa de cancelación** para detectar problemas."

### Tab Sincronizar al móvil

> "Y esto es lo que más le gusta a la dueña: una URL que pega en su Google Calendar UNA vez. A partir de ahí ve todas las citas en su iPhone como cualquier evento. Sin app, sin contraseñas, sin nada."

---

## Cierre (2 min)

> "Resumen rápido: la clienta pide cita por donde quiera (web, WhatsApp, llamada), el sistema asigna automáticamente al estilista que sepa hacer el servicio y esté libre, la dueña ve todo en un panel + en su móvil + recibe email cuando entra cada cita. Plus: los datos quedan en el CRM del salón para fidelizar y reconocer clientas que vuelven."

> "El precio es **[X €/mes]** instalación incluida. ¿Tienes alguna duda o te gustaría que lo adaptemos a tus servicios?"

---

## Objeciones comunes y respuestas

### "¿Y si el bot dice algo que no debe?"

> "Tenemos guardrails que detectan si el bot afirma algo sin haber ejecutado la acción real. En esos casos, en lugar de mentir, le pide a la clienta confirmar los datos. Lo hemos QA-eado durante varias rondas de testeo."

### "¿Y si quiero personalizar la voz / nombre / colores?"

> "Todo se personaliza editando un archivo de configuración. Nombre del bot ('Mara', 'Lucía', lo que quieras), colores, mensaje de bienvenida, política de antelación de citas (algunos salones solo aceptan con 24 h, otros última hora). El catálogo de servicios y el equipo también se editan ahí."

### "¿Cuánto tarda el setup?"

> "Entre 1 día y 1 semana según lo que quieras: solo WhatsApp, o también web y voz. La parte técnica son horas; la mayor parte es ajustar el bot a TUS servicios, TU equipo y TU horario."

### "¿Qué pasa con el GDPR / privacidad?"

> "Los datos quedan en una BD propia tuya en Supabase europeo (Frankfurt o Dublín). Nadie más accede. Puedes borrar en cualquier momento. La IA es Anthropic Claude, que no entrena con tus datos."

### "¿Qué pasa si la IA cae?"

> "Los webhooks tienen retry automático. Si el bot está saturado por una hora pico, la clienta recibe un mensaje pidiendo que llame al salón directo. Nunca se pierde la cita."

### "¿Y si me sale más rentable contratar a alguien que coja el teléfono?"

> "Una persona en plantilla son ~1.500 €/mes mínimo, solo turno parcial. Esto cuesta una fracción y trabaja 24/7. Pero no es excluyente: puedes seguir teniendo a alguien para casos complejos, el bot le filtra el 80% del trabajo repetitivo (citas básicas, consultas de horario y precios)."

### "¿Y si la clienta quiere un servicio que el bot no conoce?"

> "El bot tiene una lista cerrada de servicios (los que tú metas en el catálogo) y, si una clienta pide algo fuera de esa lista, escala al equipo automáticamente con un email a la dueña. Nunca se inventa precios."

---

## Checklist post-demo

- [ ] Mandar email resumen con grabación / capturas de la demo
- [ ] Resetear BD demo si quedó "sucia" con citas de prueba
- [ ] Apuntar feedback del cliente en CRM interno

---

## Mantenimiento de este guion

Cuando se añada un canal nuevo o cambie sustancialmente uno existente, **actualiza este `DEMO.md`** en el mismo PR. Es la fuente de verdad para el equipo comercial.
