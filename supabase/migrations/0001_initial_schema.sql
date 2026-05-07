-- ═══════════════════════════════════════════════════════════════════
-- Migracion inicial — Salon Mara (peluqueria)
-- ═══════════════════════════════════════════════════════════════════
-- Crea las tablas que el backend espera, con sus indices, check
-- constraints y RLS. Estilistas y catalogo de servicios viven en YAML
-- (config/peluqueria.yaml), no en BD.
--
-- Aplicar con el MCP de Supabase: apply_migration con
-- name = 0001_initial_schema.
-- ═══════════════════════════════════════════════════════════════════


-- ─── Extension para uuid ────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ─── DROP previo (idempotente) ──────────────────────────────────────
-- Hace la migracion re-ejecutable. Solo seguro porque el proyecto es
-- nuevo y NO contiene datos. Si en el futuro hay datos, NO se debe
-- volver a correr este bloque: usa migraciones incrementales.
DROP TABLE IF EXISTS seguimientos_pendientes CASCADE;
DROP TABLE IF EXISTS escalaciones CASCADE;
DROP TABLE IF EXISTS llamadas_voz CASCADE;
DROP TABLE IF EXISTS web_conversaciones CASCADE;
DROP TABLE IF EXISTS whatsapp_conversaciones CASCADE;
DROP TABLE IF EXISTS cita_servicios CASCADE;
DROP TABLE IF EXISTS citas CASCADE;
DROP TABLE IF EXISTS clientes CASCADE;


-- ═══════════════════════════════════════════════════════════════════
-- 1. clientes — CRM unificado del salon
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT UNIQUE,                       -- formato +34XXXXXXXXX
    nombre TEXT NOT NULL DEFAULT '(sin nombre)',
    email TEXT,
    -- Alergias a tintes / sensibilidades a productos. Texto libre
    -- (ej. "alergica a parafenilendiamina", "piel sensible al amoniaco").
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
-- 2. citas — todas las citas (cualquier canal)
-- ═══════════════════════════════════════════════════════════════════
-- Una cita = un cliente + uno o varios servicios + un estilista +
-- una franja [hora_inicio, hora_fin]. Los servicios concretos viven
-- en la tabla M-N `cita_servicios`. La duracion total se calcula
-- sumando la duracion de cada servicio asociado.
--
-- estilista_id_yaml es un STRING que referencia el id_yaml del
-- estilista en config/peluqueria.yaml (no FK porque el catalogo de
-- estilistas vive en YAML, no en BD).
CREATE TABLE citas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id) ON DELETE SET NULL,
    nombre TEXT NOT NULL,
    telefono TEXT NOT NULL,
    fecha DATE NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    estilista_id_yaml TEXT NOT NULL,            -- id_yaml de config/peluqueria.yaml
    -- Snapshot de las alergias/notas relevantes para esta cita
    -- (independiente de las del cliente, por si esta cita en concreto
    -- tiene un aviso especifico).
    alergias TEXT,
    notas TEXT,
    estado TEXT NOT NULL DEFAULT 'confirmada'
        CHECK (estado IN ('confirmada', 'cancelada', 'completada')),
    motivo_cancelacion TEXT,
    canal_origen TEXT NOT NULL DEFAULT 'web'
        CHECK (canal_origen IN ('web', 'whatsapp', 'voz', 'escalacion')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_citas_telefono ON citas (telefono);
CREATE INDEX idx_citas_fecha ON citas (fecha);
CREATE INDEX idx_citas_estado ON citas (estado);
-- Para detectar solapamientos del mismo estilista en un mismo dia.
CREATE INDEX idx_citas_estilista_fecha
    ON citas (estilista_id_yaml, fecha)
    WHERE estado = 'confirmada';


-- ═══════════════════════════════════════════════════════════════════
-- 3. cita_servicios — relacion M-N entre citas y servicios
-- ═══════════════════════════════════════════════════════════════════
-- Cada fila representa un servicio individual de una cita. Permite
-- combinar (ej. "corte mujer + coloracion completa" = 2 filas para
-- la misma cita_id, sumando duracion y precio).
--
-- Snapshot de precio y duracion al momento de la cita: si en el
-- futuro cambian los precios del YAML, las citas pasadas mantienen
-- el importe que cobramos en su dia.
CREATE TABLE cita_servicios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cita_id UUID NOT NULL REFERENCES citas(id) ON DELETE CASCADE,
    servicio_nombre TEXT NOT NULL,              -- copia del YAML, ej. "Corte mujer"
    categoria TEXT,                             -- ej. "corte", "color"
    especialidad TEXT,                          -- ej. "corte_mujer", "color"
    duracion_min SMALLINT NOT NULL CHECK (duracion_min > 0),
    precio_eur NUMERIC(8, 2) NOT NULL CHECK (precio_eur >= 0),
    orden SMALLINT NOT NULL DEFAULT 1,          -- 1, 2, 3... orden dentro de la cita
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cita_servicios_cita ON cita_servicios (cita_id);


-- ═══════════════════════════════════════════════════════════════════
-- 4. whatsapp_conversaciones — historial WhatsApp
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
-- 5. web_conversaciones — historial chatbot web
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
-- 6. llamadas_voz — transcripciones + resumenes Vapi
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
-- 7. escalaciones — casos derivados al duenno
-- ═══════════════════════════════════════════════════════════════════
-- Motivos adaptados a peluqueria:
--   cliente_lo_pide       — el cliente pide hablar con un humano
--   queja_o_enfado        — incidencia o queja
--   servicio_no_disponible — pide algo que no esta en el catalogo
--   caso_complejo         — situacion no estandar (ej. extensiones)
--   datos_no_capturados   — el bot no logro capturar dato critico
--   otro                  — fallback
CREATE TABLE escalaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL,
    vapi_call_id TEXT,
    motivo TEXT NOT NULL
        CHECK (motivo IN (
            'cliente_lo_pide',
            'queja_o_enfado',
            'servicio_no_disponible',
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
-- 8. seguimientos_pendientes — handoff voz -> WhatsApp
-- ═══════════════════════════════════════════════════════════════════
-- Cuando Kara/Mara no puede capturar un dato por voz (ej. el cliente
-- no se acuerda del servicio exacto), se deriva al chatbot WhatsApp
-- y se registra aqui que pregunta queda pendiente.
CREATE TABLE seguimientos_pendientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL,
    datos_parciales JSONB,
    pregunta_pendiente TEXT
        CHECK (pregunta_pendiente IN (
            'servicio',
            'fecha_y_hora',
            'estilista',
            'confirmacion',
            'nombre',
            'alergias',
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
ALTER TABLE citas ENABLE ROW LEVEL SECURITY;
ALTER TABLE cita_servicios ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_conversaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE web_conversaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE llamadas_voz ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE seguimientos_pendientes ENABLE ROW LEVEL SECURITY;


-- ═══════════════════════════════════════════════════════════════════
-- Comentarios de tabla (utiles en el panel de Supabase)
-- ═══════════════════════════════════════════════════════════════════
COMMENT ON TABLE clientes IS
    'CRM unificado del salon. Identificador principal: telefono.';
COMMENT ON TABLE citas IS
    'Citas de peluqueria. Una franja horaria con un estilista y N servicios.';
COMMENT ON TABLE cita_servicios IS
    'Servicios concretos de cada cita (M-N). Snapshot de precio y duracion.';
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
