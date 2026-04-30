-- ═══════════════════════════════════════════════════════════════════
-- Migracion 0005 — Estado no_show (issue #10)
-- ═══════════════════════════════════════════════════════════════════
-- Anade el valor 'no_show' al check constraint de reservas.estado para
-- marcar reservas confirmadas que no aparecieron. El cron de deteccion
-- las detecta a posteriori (>30 min sin llegada) y libera la mesa.
--
-- Aplicar en SQL Editor.
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE reservas
    DROP CONSTRAINT IF EXISTS reservas_estado_check;

ALTER TABLE reservas
    ADD CONSTRAINT reservas_estado_check
    CHECK (estado IN ('confirmada', 'cancelada', 'completada', 'no_show'));

-- Indice para detectar candidatos a no-show rapido
CREATE INDEX IF NOT EXISTS idx_reservas_pendientes_llegada
    ON reservas (fecha, hora)
    WHERE estado = 'confirmada';

COMMENT ON COLUMN reservas.estado IS
    'Estado de la reserva: confirmada (activa), cancelada (anulada), '
    'completada (cliente vino), no_show (no aparecio en X min).';
