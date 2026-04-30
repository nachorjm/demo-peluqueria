-- ═══════════════════════════════════════════════════════════════════
-- Migracion 0004 — Modelo de mesas y duracion (rediseno aforo)
-- ═══════════════════════════════════════════════════════════════════
-- Sustituye el modelo "aforo total = 50 personas/turno" por un modelo
-- de mesas reales con capacidad individual + duracion de reserva.
--
-- Una reserva ahora ocupa una o varias mesas durante un rango horario
-- concreto. Cualquier combinacion de mesas libres puede acoger un grupo
-- mientras la suma de capacidades sea suficiente.
--
-- Aplicar en SQL Editor del proyecto Casa Lola.
-- ═══════════════════════════════════════════════════════════════════


-- ─── 1. Tabla mesas ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mesas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL UNIQUE,           -- ej: 'M1', 'M2', 'T1'
    capacidad SMALLINT NOT NULL CHECK (capacidad BETWEEN 1 AND 20),
    ubicacion TEXT,                        -- 'sala', 'terraza', 'reservado'... opcional
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE mesas ENABLE ROW LEVEL SECURITY;


-- ─── 2. Seed de mesas Casa Lola (14 mesas, 52 plazas) ──────────────
INSERT INTO mesas (nombre, capacidad, ubicacion) VALUES
    ('M1',  2, 'sala'),
    ('M2',  2, 'sala'),
    ('M3',  2, 'sala'),
    ('M4',  2, 'sala'),
    ('M5',  2, 'sala'),
    ('M6',  2, 'sala'),
    ('M7',  4, 'sala'),
    ('M8',  4, 'sala'),
    ('M9',  4, 'sala'),
    ('M10', 4, 'sala'),
    ('M11', 4, 'sala'),
    ('M12', 6, 'sala'),
    ('M13', 6, 'sala'),
    ('M14', 8, 'sala')
ON CONFLICT (nombre) DO NOTHING;


-- ─── 3. Columnas nuevas en reservas ────────────────────────────────
ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS mesas_asignadas UUID[];

ALTER TABLE reservas
    ADD COLUMN IF NOT EXISTS hora_fin TIME;

-- Indice GIN para buscar reservas por mesa rapido (overlap queries).
CREATE INDEX IF NOT EXISTS idx_reservas_mesas_asignadas
    ON reservas USING GIN (mesas_asignadas);

CREATE INDEX IF NOT EXISTS idx_reservas_fecha_horario
    ON reservas (fecha, hora, hora_fin)
    WHERE estado = 'confirmada';


COMMENT ON TABLE mesas IS
    'Mesas fisicas del restaurante. Cualquier combinacion de mesas libres '
    'puede agruparse para acoger un grupo mientras la suma de capacidades '
    'sea suficiente.';

COMMENT ON COLUMN reservas.mesas_asignadas IS
    'Array de IDs de mesas asignadas a esta reserva. 1 elemento = mesa '
    'simple. 2+ = grupo agrupado fisicamente.';

COMMENT ON COLUMN reservas.hora_fin IS
    'Hora estimada de fin de la reserva (calculada al crear: hora + '
    'duracion del turno + extra si arroz). Usado para detectar solapamientos.';
