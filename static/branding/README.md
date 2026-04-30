# Branding visual del restaurante

Aquí van los archivos de imagen específicos del cliente que se sirven desde `/static/branding/`. Las rutas se referencian en `config/restaurante.yaml` (bloque `landing:`).

## Archivos esperados

| Archivo | Tamaño recomendado | Para qué sirve | Obligatorio |
|---|---|---|---|
| `favicon.svg` o `favicon.png` | 64x64 (SVG escala) | Icono de pestaña del navegador | Recomendado |
| `og-image.png` | **1200x630** (estricto) | Preview al compartir link en WhatsApp / Twitter / LinkedIn | Opcional |
| `logo.png` o `logo.svg` | Alto ~200px, fondo transparente | Logo principal en landing y emails | Opcional |

## Cómo usar

1. **Sube tus archivos** a esta carpeta con los nombres de arriba (o los que prefieras)
2. **Edita `config/restaurante.yaml`**, bloque `landing:`:
   ```yaml
   landing:
     favicon: "/static/branding/favicon.svg"
     og_image: "/static/branding/og-image.png"
     logo: "/static/branding/logo.png"
   ```
3. Si dejas alguna ruta como `""`, ese tag no se inyecta en el HTML (no rompe nada, simplemente no aparece).

## Para Casa Lola (demo)

Hay un `favicon.svg` placeholder con la letra "L" en colores Casa Lola. `og_image` y `logo` están vacíos en el YAML — sube los tuyos cuando tengas las imágenes finales.

## Para emails

Si quieres que los emails al dueño lleven logo arriba, edita `config/restaurante.yaml` bloque `emails:`:

```yaml
emails:
  logo_url: "https://tu-dominio.com/static/branding/logo.png"
```

⚠️ La URL del logo en emails debe ser **absoluta** (con `https://...`). Las rutas relativas no funcionan en clientes de correo.
