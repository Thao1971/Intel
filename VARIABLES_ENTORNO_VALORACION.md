# Variables de entorno

## Intel — obligatorias en producción

| Variable | Valor / uso |
|---|---|
| `ARROBA_ENV=production` | Activa el guardián de arranque (`config_guard.py`): Intel **no arranca** si la configuración es insegura. |
| `MONGO_URL`, `DB_NAME` | Base productiva con `master_companies`, `norm_financials`, `users`, `api_keys`. |
| `JWT_SECRET` | Secreto propio, ≥ 32 caracteres. Con el valor por defecto o uno corto, el arranque falla en producción. |
| `CORS_ORIGINS` | Origen exacto de Beta (p. ej. `https://beta.arroba.com`). `*` hace fallar el arranque en producción. |
| `AUTO_BOOTSTRAP_DATA_LAYER=0` | **Defecto 0.** Con 0 no se genera ningún dato sintético (ni Iberinform ni DataComex) aunque la base esté vacía: se registra un error y se omiten los agregados dependientes. Con 1 en producción el arranque falla. |
| `ARROBA_SERVICE_API_KEY` | Clave de servicio para las rutas internas que usan `X-API-Key`. Distinta de la clave Bearer de la pasarela. |

## Intel — opcionales (solo si se usa la función)

`EMERGENT_LLM_KEY`, `OPENAI_API_KEY`, `NVIDIA_*` (chat/IA; la valoración y su PDF **no** los necesitan), `R2_*` (almacenamiento de documentos), `DATA_LAYER_SOURCE_DIR` (origen de la capa de datos), `EDITORIAL_*`, `COPILOT_VOICE_PROVIDER`, `MARKET_READING_PROVIDER`, `IBERINFORM_UPLOAD_API_KEY` (solo si se habilita la carga de Iberinform).

Los tests de humo usan `SMOKE_TEST_PASSWORD` (variable de entorno; ya no hay contraseñas en el código).

## Pasarela `/intel` (proceso de Beta, solo servidor)

| Variable | Uso |
|---|---|
| `INTEL_UPSTREAM_URL` | URL de Intel. Sin ella la pasarela responde 503. |
| `INTEL_SERVICE_API_KEY` | Clave **Bearer** válida en Intel (ver abajo). Sin ella, 503. Nunca `NEXT_PUBLIC_*`. |
| `BETA_SESSION_VALIDATE_URL` | Opcional. Endpoint que valida la cookie `arroba_session` y devuelve `{"user":{"user_id":...}}`. Por defecto `http://127.0.0.1:8001/api/auth/me` (backend de Beta en el mismo contenedor). |

### Cómo crear `INTEL_SERVICE_API_KEY`
Con un usuario administrador de Intel: `POST /api/v1/auth/api-keys` y copiar la clave devuelta (solo se muestra una vez) a los secretos del servidor de Beta.

## Beta — build público

- `NEXT_PUBLIC_INTEL_API_BASE_URL=/intel` (solo una ruta, nunca un secreto; queda en el JavaScript del navegador).

## Comprobación de datos antes del arranque

Deben existir con volumen razonable: `master_companies`, `norm_financials`, `users`, `api_keys`. Comprobar una muestra real por CIF y que el último ejercicio de `norm_financials` es el último publicado. La entrega incluye referencias de mercado, no el universo Iberinform.
