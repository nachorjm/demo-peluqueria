# Guion comercial — Demo Casa Lola

> Chuleta para enseñar el producto Alnora a un dueño de restaurante. Aproximadamente **15-20 minutos** si se siguen todos los pasos. Adapta según interés del cliente.

---

## URLs y datos clave

| Elemento | URL / valor |
|---|---|
| Landing pública del restaurante demo | `https://web-production-aa295.up.railway.app/` |
| Página comercial demo | `https://web-production-aa295.up.railway.app/demo` |
| Panel del dueño | `https://web-production-aa295.up.railway.app/admin` |
| Contraseña del panel | `(la sabe el comercial — no compartir por escrito)` |
| WhatsApp sandbox número | `+1 415 523 8886` |
| WhatsApp palabra clave | `join produce-go` (verificar en Twilio antes de cada demo) |
| Número Vapi para llamar | `(configurar VAPI_PHONE_NUMBER en Railway antes)` |

---

## Antes de la demo (10 min)

Para que la demo no sea pobre, asegúrate de:

- [ ] **Reservas en BD**: el panel admin tiene al menos 20-30 reservas variadas en las próximas 2 semanas (no 4 como hoy). Si no, el calendario y las stats se ven vacíos. → Pendiente: ejecutar `scripts/poblar_demo.py` cuando esté hecho (issue futura).
- [ ] **Hora del día**: si haces demo a las 22:00, el bot va a decir "estamos cerrados". Mejor de día.
- [ ] **WhatsApp keyword vigente**: Twilio renueva las palabras clave. Comprueba en https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn que sigue siendo `join produce-go`.
- [ ] **Vapi número activo**: marca al número desde tu móvil 1 vez antes de la demo para confirmar que Lola contesta.
- [ ] **Email Resend**: que `gestionalnora@gmail.com` esté abierto en otra pestaña para enseñar la notificación al dueño en directo.
- [ ] **Tu propio teléfono libre** para hacer la prueba de WhatsApp delante del cliente sin que tu chat personal aparezca.

---

## Apertura (1 min)

> "Te voy a enseñar **cómo Casa Lola, un restaurante real ficticio**, gestiona reservas con IA en los 3 canales que más usa la gente: WhatsApp, web, y llamada por teléfono. Todo lo que veas son escenarios reales. Después te enseño el panel del dueño y vemos qué te encajaría."

Abre `/demo` en pantalla compartida (es la página comercial pensada para esto).

---

## Bloque 1 — Chat web (3 min)

Click en "Probar el chat web →" desde `/demo`. Llegas a la landing de Casa Lola.

> "Imagínate que esto es la web del restaurante. Cualquier visitante ve el botón de chat abajo a la derecha."

Pulsa el botón. Escribe en vivo:

```
Hola, quiero reservar para 4 el viernes a las 21:00, soy Marta, 600111222
```

> "Mira: el bot ya tiene fecha, hora, personas, nombre y teléfono de un solo mensaje. Te pregunta solo lo que falta."

Bot responde con resumen y pide confirmación. Escribe:

```
sí
```

> "Reserva creada. Marta acaba de tenerla apuntada en menos de 30 segundos sin coger el teléfono."

**Punto comercial**: "Esto es el caso fácil. ¿Quieres que pruebe uno raro para que veas cómo aguanta?"

Si el cliente quiere, prueba un caso límite:

```
quiero mesa para mañana a las 13:00
```

> "El restaurante abre a las 13:30. Mira cómo el bot avisa al instante en lugar de pedirte todos los datos para fallar al final."

---

## Bloque 2 — WhatsApp (4 min)

Vuelve a `/demo`. Click en "Abrir WhatsApp →".

> "WhatsApp es donde está el cliente español. Aquí no hay que descargar nada — usamos un número del restaurante."

Enseña tu pantalla con el chat WhatsApp ya abierto al número sandbox. Si es la primera vez para ti, escribe `join produce-go` para iniciar.

Escribe:

```
quiero reservar mesa para 2 el sábado a las 14h
```

Sigue la conversación. Cuando dé el resumen y pidas confirmación con `sí`, dile:

> "Ahora que está confirmada, mira esto:"

(Cambia a tu pantalla del email de Resend.)

> "El dueño ya tiene la notificación con todos los datos de la reserva, en su email, en el momento. Si no le gusta el email, puede ir directo al panel."

**Punto comercial**: "Lo bueno de WhatsApp: el cliente no instala nada. Solo escribe al número del restaurante como a cualquier amigo."

---

## Bloque 3 — Llamada al agente Lola (4 min)

Vuelve a `/demo`. Pulsa "Llamar al agente →" desde tu móvil (en altavoz para que el cliente lo oiga).

Lola atiende. Pídele reservar mesa de forma natural:

```
Hola, soy Carmen, quiero reservar mesa para 3 el viernes a las 21
```

> "Mira: español natural, conversación fluida, voz Azure que suena humana."

Si tienes tiempo, prueba un caso de derivación:

```
Tengo una alergia muy compleja, ¿podrías mirármelo?
```

Lola debería ofrecerte derivar a WhatsApp o pasar el caso al equipo.

**Punto comercial**: "Esto es las 14:30 cuando estás emplatando. La llamada que normalmente perderías, queda atendida. Y el dueño ve la reserva en el panel."

---

## Bloque 4 — Panel del dueño (5 min)

Abre `/admin` en otra pestaña. Introduce contraseña.

### Tab Calendario

> "Esto es lo que el dueño abre al llegar al restaurante por la mañana. Calendario semanal con cada reserva codificada por color según el canal: azul web, verde WhatsApp, morado voz."

Click en una reserva. Sale el modal.

> "Click en cualquier reserva y ves todos los datos: nombre, teléfono, alergias, qué celebran. Si necesita cancelarla por algún motivo, botón rojo y listo."

### Tab Estadísticas

> "Aquí tiene los KPIs: reservas hoy, esta semana, este mes, comensales totales. Por canal — para saber dónde está captando más. Hora pico por día — para planificar plantilla."

### Tab Sincronizar al móvil

> "Y esto es lo que más le gusta al dueño: una URL que pega en su Google Calendar UNA vez. A partir de ahí ve todas las reservas en su iPhone como cualquier cita. Sin app, sin contraseñas, sin nada."

---

## Cierre (2 min)

> "Resumen rápido: el cliente reserva por donde quiera (web, WhatsApp, llamada), el dueño ve todo en un panel + en su móvil + recibe email cuando entra cada reserva. Plus: recordatorios automáticos por WhatsApp la noche anterior reducen el no-show, y los datos quedan en el CRM del restaurante para fidelizar."

> "El precio es **[X €/mes]** instalación incluida. ¿Tienes alguna duda o te gustaría que lo adaptemos a tu carta?"

---

## Objeciones comunes y respuestas

### "¿Y si el bot dice algo que no debe?"

> "Tenemos guardrails que detectan si el bot afirma algo sin haber ejecutado la acción real. En esos casos, en lugar de mentir, te pide al cliente confirmar los datos. Lo hemos QA-eado durante 4 rondas de testeo."

### "¿Y si quiero personalizar la voz / nombre / colores?"

> "Todo se personaliza editando un archivo de configuración. Nombre del bot ('Lola', 'Carmen', lo que quieras), colores, mensaje de bienvenida, política de antelación de reservas (algunos solo aceptan con 24h, otros última hora)."

### "¿Cuánto tarda el setup?"

> "Entre 1 día y 1 semana según lo que quieras: solo WhatsApp, o también web y voz. La parte técnica son horas; la mayor parte es ajustar el bot a TU carta y TU horario."

### "¿Qué pasa con el GDPR / privacidad?"

> "Los datos quedan en una BD propia tuya en Supabase europeo (Frankfurt o Dublín). Nadie más accede. Puedes borrar en cualquier momento. La IA es Anthropic Claude, que no entrena con tus datos."

### "¿Qué pasa si la IA cae?"

> "Los webhooks tienen retry automático. Si el bot está saturado por una hora pico, el cliente recibe un mensaje pidiendo que llame al restaurante directo. Nunca se pierde la reserva."

### "¿Y si me sale más rentable contratar a alguien que coja el teléfono?"

> "Una persona en plantilla son ~1.500 €/mes mínimo, solo turno parcial. Esto cuesta una fracción y trabaja 24/7. Pero no es excluyente: puedes seguir teniendo a alguien para casos complejos, el bot le filtra el 80% del trabajo repetitivo."

---

## Checklist post-demo

- [ ] Mandar email resumen con grabación / capturas de la demo
- [ ] Resetear BD demo si quedó "sucia" con reservas de prueba (script `scripts/reset_demo.py` cuando esté hecho — issue futura)
- [ ] Apuntar feedback del cliente en CRM interno

---

## Mantenimiento de este guion

Cuando se añada un canal nuevo o cambie sustancialmente uno existente, **actualiza este `DEMO.md`** en el mismo PR. Es la fuente de verdad para el equipo comercial.
