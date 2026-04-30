-- ═══════════════════════════════════════════════════════════════════
-- Migracion 0003 — Lista de espera (issue #6)
-- ═══════════════════════════════════════════════════════════════════
-- Tabla para clientes que quieren reservar en una fecha+turno LLENO y
-- piden ser avisados si se libera mesa. Cuando una reserva se cancela,
-- el backend busca aqui candidatos compatibles y manda WhatsApp al primero.
--
-- Aplicar en SQL Editor del proyecto Casa Lola.
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS lista_espera (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    telefono TEXT NOT NULL,                    -- formato +34XXXXXXXXX
    fecha DATE NOT NULL,
    hora_preferida TIME,                       -- nullable: si no le importa la hora exacta
    turno TEXT
        CHECK (turno IN ('comida', 'cena')),
    num_personas SMALLINT NOT NULL
        CHECK (num_personas BETWEEN 1 AND 20),
    alergias TEXT,
    notas TEXT,
    estado TEXT NOT NULL DEFAULT 'esperando'
        CHECK (estado IN ('esperando', 'notificado', 'aceptado', 'rechazado', 'expirado', 'cancelado')),
    notificado_at TIMESTAMPTZ,                 -- cuando se le mando la oferta
    notificado_sid TEXT,                       -- sid del WA enviado
    respuesta_at TIMESTAMPTZ,                  -- cuando respondio SI/NO
    canal_origen TEXT NOT NULL DEFAULT 'web'
        CHECK (canal_origen IN ('web', 'whatsapp', 'voz')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lista_espera_fecha_turno_estado
    ON lista_espera (fecha, turno, estado);

CREATE INDEX IF NOT EXISTS idx_lista_espera_telefono
    ON lista_espera (telefono);

ALTER TABLE lista_espera ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE lista_espera IS
    'Clientes en lista de espera para fechas+turnos llenos. Cuando se '
    'cancela una reserva, se notifica al primero de la lista compatible.';
