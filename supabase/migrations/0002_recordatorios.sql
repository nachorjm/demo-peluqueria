-- ═══════════════════════════════════════════════════════════════════
-- Migracion 0002 — Recordatorios automaticos (issue #5)
-- ═══════════════════════════════════════════════════════════════════
-- Anade columnas a `reservas` para soportar el envio de recordatorios
-- el dia anterior por WhatsApp y el procesamiento de la respuesta del
-- cliente (confirmar / cancelar).
--
-- Aplicar en SQL Editor del proyecto Casa Lola.
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS recordatorio_enviado_at TIMESTAMPTZ;

ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS recordatorio_sid TEXT;
    -- SID del mensaje WA enviado por Twilio, para trazabilidad.

ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS recordatorio_respuesta TEXT
        CHECK (recordatorio_respuesta IN ('confirmado', 'cancelado', 'sin_respuesta'));

ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS recordatorio_respuesta_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_reservas_recordatorio_pendiente
    ON reservas (fecha, estado)
    WHERE recordatorio_enviado_at IS NULL AND estado = 'confirmada';
