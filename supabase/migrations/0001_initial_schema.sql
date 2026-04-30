-- ═══════════════════════════════════════════════════════════════════
-- Migracion inicial — Casa Lola
-- ═══════════════════════════════════════════════════════════════════
-- Crea las 7 tablas que el backend espera, con sus indices, check
-- constraints, RLS y la unica policy publica (insert en `clientes`
-- desde la landing si en algun momento se anade un formulario).
--
-- Aplicar con el MCP de Supabase: apply_migration con name = 0001_initial_schema.
-- ═══════════════════════════════════════════════════════════════════


-- ─── Extension para uuid_generate_v4 ────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ─── DROP previo (idempotente) ──────────────────────────────────────
-- Hace la migracion re-ejecutable. Solo seguro porque el proyecto es
-- nuevo y NO contiene datos. Si en el futuro hay datos, NO se debe
-- volver a correr este bloque: usa migraciones incrementales (0002...).
DROP TABLE IF EXISTS seguimientos_pendientes CASCADE;
DROP TABLE IF EXISTS escalaciones CASCADE;
DROP TABLE IF EXISTS llamadas_voz CASCADE;
DROP TABLE IF EXISTS web_conversaciones CASCADE;
DROP TABLE IF EXISTS whatsapp_conversaciones CASCADE;
DROP TABLE IF EXISTS reservas CASCADE;
DROP TABLE IF EXISTS clientes CASCADE;


-- ═══════════════════════════════════════════════════════════════════
-- 1. clientes — CRM unificado del restaurante
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT UNIQUE,                       -- formato +34XXXXXXXXX
    nombre TEXT NOT NULL DEFAULT '(sin nombre)',
    email TEXT,                                 -- opcional
    alergias TEXT,
    notas TEXT,
    canal_origen TEXT NOT NULL DEFAULT 'web'
        CHECK (canal_origen IN ('web', 'whatsapp', 'voz', 'escalacion')),
    ultima_interaccion TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_clientes_telefono ON clientes (telefono);
CREATE INDEX idx_clientes_email ON clientes (LOWER(email));


-- ═══════════════════════════════════════════════════════════════════
-- 2. reservas — todas las reservas (cualquier canal)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE reservas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id) ON DELETE SET NULL,
    nombre TEXT NOT NULL,
    telefono TEXT NOT NULL,
    fecha DATE NOT NULL,
    hora TIME NOT NULL,
    turno TEXT NOT NULL
        CHECK (turno IN ('comida', 'cena')),
    num_personas SMALLINT NOT NULL
        CHECK (num_personas BETWEEN 1 AND 20),
    alergias TEXT,
    ocasion_especial TEXT,
    notas TEXT,
    estado TEXT NOT NULL DEFAULT 'confirmada'
        CHECK (estado IN ('confirmada', 'cancelada', 'completada')),
    motivo_cancelacion TEXT,
    canal_origen TEXT NOT NULL DEFAULT 'web'
        CHECK (canal_origen IN ('web', 'whatsapp', 'voz', 'escalacion')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_reservas_telefono ON reservas (telefono);
CREATE INDEX idx_reservas_fecha_turno ON reservas (fecha, turno);
CREATE INDEX idx_reservas_estado ON reservas (estado);


-- ═══════════════════════════════════════════════════════════════════
-- 3. whatsapp_conversaciones — historial de mensajes WhatsApp
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE whatsapp_conversaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL,                     -- 'whatsapp:+34...' por compat con plantilla
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_wa_conv_telefono_created
    ON whatsapp_conversaciones (telefono, created_at DESC);


-- ═══════════════════════════════════════════════════════════════════
-- 4. web_conversaciones — historial del chatbot web
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE web_conversaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_web_conv_session_created
    ON web_conversaciones (session_id, created_at DESC);


-- ═══════════════════════════════════════════════════════════════════
-- 5. llamadas_voz — transcripciones + resumenes del agente Vapi
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE llamadas_voz (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL,
    vapi_call_id TEXT,
    duracion_segundos INTEGER,
    resumen TEXT,
    transcripcion JSONB,
    ended_reason TEXT,
    coste_usd NUMERIC(10, 4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_llamadas_telefono_created
    ON llamadas_voz (telefono, created_at DESC);


-- ═══════════════════════════════════════════════════════════════════
-- 6. escalaciones — casos derivados al duenno
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE escalaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL,
    vapi_call_id TEXT,
    motivo TEXT NOT NULL
        CHECK (motivo IN (
            'cliente_lo_pide',
            'queja_o_enfado',
            'grupo_grande',
            'evento_privado',
            'caso_complejo',
            'datos_no_capturados',
            'otro'
        )),
    contexto TEXT NOT NULL,
    datos_cliente JSONB,
    resend_message_id TEXT,
    email_status TEXT
        CHECK (email_status IN ('pendiente', 'enviado', 'fallido')),
    email_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_escalaciones_created ON escalaciones (created_at DESC);


-- ═══════════════════════════════════════════════════════════════════
-- 7. seguimientos_pendientes — handoff voz -> WhatsApp
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE seguimientos_pendientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL,
    datos_parciales JSONB,
    pregunta_pendiente TEXT
        CHECK (pregunta_pendiente IN (
            'alergias',
            'fecha_y_hora',
            'num_personas',
            'confirmacion',
            'nombre',
            'otro'
        )),
    contexto TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'completado', 'cancelado')),
    vapi_call_id TEXT,
    twilio_message_sid TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_seguimientos_telefono_estado
    ON seguimientos_pendientes (telefono, estado);


-- ═══════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY (RLS)
-- ═══════════════════════════════════════════════════════════════════
-- RLS activado en todas las tablas. El backend se conecta con la
-- service_role key (que SALTA RLS), asi que las policies solo afectan
-- a clientes anonimos / autenticados via la API publica.
--
-- Para esta demo NO exponemos ninguna tabla a anon. Todo el acceso
-- pasa por el backend FastAPI con service role.

ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reservas ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_conversaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE web_conversaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE llamadas_voz ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE seguimientos_pendientes ENABLE ROW LEVEL SECURITY;


-- ═══════════════════════════════════════════════════════════════════
-- Comentarios de tabla (utiles en el panel de Supabase)
-- ═══════════════════════════════════════════════════════════════════
COMMENT ON TABLE clientes IS
    'CRM unificado del restaurante. Identificador principal: telefono.';
COMMENT ON TABLE reservas IS
    'Todas las reservas. Una mesa = una fila. estado=confirmada por defecto.';
COMMENT ON TABLE whatsapp_conversaciones IS
    'Historial de mensajes WhatsApp. Clave por telefono (con prefijo whatsapp:).';
COMMENT ON TABLE web_conversaciones IS
    'Historial del chatbot web embebido. Clave por session_id (uuid).';
COMMENT ON TABLE llamadas_voz IS
    'Transcripcion + resumen estructurado de cada llamada del agente Vapi.';
COMMENT ON TABLE escalaciones IS
    'Casos que el bot deriva al duenno por email (Resend).';
COMMENT ON TABLE seguimientos_pendientes IS
    'Handoff voz -> WhatsApp: dato que no se pudo capturar por voz.';
