-- ═══════════════════════════════════════════════════════════════════
-- Migracion 0006 — Encuestas post-visita y feedback (issue #7)
-- ═══════════════════════════════════════════════════════════════════
-- Tabla para guardar las valoraciones del cliente tras su visita.
-- Cron diario al mediodia manda WhatsApp a los clientes que vinieron
-- ayer pidiendo nota 1-5. Si nota >= 4 se les redirige a Google
-- Reviews; si <= 3 se pide comentario y se manda al duenno por email.
--
-- Tambien anade columnas a `reservas` para trackear el envio sin
-- repetir.
-- ═══════════════════════════════════════════════════════════════════


CREATE TABLE IF NOT EXISTS feedback_clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reserva_id UUID REFERENCES reservas(id) ON DELETE SET NULL,
    telefono TEXT NOT NULL,
    nombre TEXT,
    valoracion SMALLINT CHECK (valoracion BETWEEN 1 AND 5),
    comentario TEXT,
    enviado_a_review BOOLEAN DEFAULT FALSE,  -- true si se le mando enlace de Google Reviews
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_telefono ON feedback_clientes (telefono);
CREATE INDEX IF NOT EXISTS idx_feedback_reserva ON feedback_clientes (reserva_id);
CREATE INDEX IF NOT EXISTS idx_feedback_valoracion ON feedback_clientes (valoracion);

ALTER TABLE feedback_clientes ENABLE ROW LEVEL SECURITY;


-- Columnas en reservas para evitar mandar la encuesta dos veces
ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS encuesta_enviada_at TIMESTAMPTZ;

ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS encuesta_sid TEXT;

CREATE INDEX IF NOT EXISTS idx_reservas_encuesta_pendiente
    ON reservas (fecha)
    WHERE encuesta_enviada_at IS NULL AND estado = 'confirmada';


COMMENT ON TABLE feedback_clientes IS
    'Encuestas post-visita. Cliente que vino ayer recibe WhatsApp con '
    '"puntuanos del 1 al 5". 4-5 -> Google Reviews. 1-3 -> comentario '
    'al duenno por email.';
