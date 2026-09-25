# Informe · Aplicación ZIP `ARROBA_INTEL_EMERGENT_20260925_REVISADO_CODEX.zip` sobre Intel

**Fecha:** 2026-09-25 · **Entorno:** Preview (Mongo local) · **SHA-256 verificado:** `425afe3f4a22cb44a2e33081aa468809476ff6317bb23442487b60201eecba5b` ✅

## 1. Confirmación del despliegue
- ZIP aplicado completo sobre `/app/backend` conservando `.env` (credenciales, `MONGO_URL`, claves), datos existentes y config de despliegue.
- Cron de precalentamiento conservado según tu instrucción: `routes/cron_prewarm.py` + `.emergent/crons.yml` intactos y `cron_prewarm` re-registrado en el `server.py` del ZIP.
- Backend arranca sin errores. Frontend/Beta no tocados.
- **Punto de restauración:** `/app/memory/backups/backend_pre_codex_20260925_192538.tar.gz` (backend + .emergent pre-ZIP).

## 2. Versión / commit
- **NO** se hizo commit, push ni reset (según tu instrucción).
- Base de trabajo: HEAD `a3f2dcd`. Cambios aplicados en árbol de trabajo, sin nuevo commit.

## 3. Compilación y tests
- `py_compile server.py` ✅ · `py_compile services/my_space_requests.py` ✅ · `py_compile routes/cron_prewarm.py` ✅
- `py_compile` de TODO el backend (Python 3.11.16): **0 ficheros con error**.
- `pytest tests/test_my_space_requests.py tests/test_my_space.py tests/test_delivery_hardening.py`: **27 passed**.
  - Solicitudes (`test_my_space_requests.py`): 11 passed.
  - Endurecimiento (`test_delivery_hardening.py`): 9 passed.

## 4. Índice `uniq_listing_buyer`
- Preflight duplicados en Preview: colección `my_space_requests` inexistente (instalación limpia, 0 duplicados).
- Creado en el arranque: `uniq_listing_buyer` sobre `(listing_id, buyer_id)`, `unique=True`. Sin errores de índice.
- Rechazo de duplicado verificado (código + test): chequeo de app + `DuplicateKeyError` traducido a `ValidationError` (sin exponer Mongo).
- No-doble-cambio concurrente verificado: update condicional por `expected_status`; si `modified_count != 1` → "La solicitud ha cambiado; actualiza la página".

## 5. Endpoints comprobados (en vivo)
| Endpoint | Auth | Resultado |
|---|---|---|
| `POST /api/v2/financial-intelligence/valuation` (contrato Beta) | X-API-Key servicio | 401 sin/mal key · **200** con contrato completo ✅ |
| `POST /api/v1/financial-intelligence/analyze` (analizar empresa) | X-API-Key servicio | **200** (perfil financiero completo) ✅ |
| `GET /api/v1/company/{cif}/ficha` (ficha empresarial) | X-API-Key servicio | 401 sin key · **200** con key ✅ |
| `GET /api/v1/company/{cif}/market` (lectura async) | X-API-Key servicio | **200** con `reading_status`/`reading_ai` ✅ |
| `GET /api/v1/public/sector-intelligence/overview` (analizar sectores) | pública | **200** ✅ |
| `GET /api/v1/public/geo-intelligence/overview` (analizar territorios) | pública | **200** ✅ |
| my-space / marketplace / solicitudes / NDA | — | cubierto por 27 tests ✅ |
| `POST /api/cron/prewarm-descriptions` | Bearer WEBHOOK_CRON_SECRET | 401 sin/mal token · **200** `accepted` con token ✅ |

Prueba usada: `LABORATORIOS SERVIER` (CIF `B28184687`, con `norm_financials`).

## 6. Cron: tanda pequeña + liberación del lock
- Ruta `/api/cron/prewarm-descriptions` presente en OpenAPI (`/api/v1/openapi.json`).
- 401 sin `Authorization` y con token incorrecto; `202/200 accepted` con `WEBHOOK_CRON_SECRET`.
- Tanda limpia (`BATCH=3`): **acquire lock → generó 2/3 (1 descartada por guard, motivo `none`) → escribió run → liberó el lock** ✅.
- Protección de solapamiento: disparo con lock ocupado → ACK 200 y **no-op** (no crea run) ✅.
- Cadencia de producción restaurada: `PREWARM_CRON_BATCH=40`, `PREWARM_CRON_DELAY=2`. El cron de plataforma disparó solo a las 19:30 y 19:45 (E2E vivo post-ZIP).

## 7. Desviaciones respecto al ZIP
1. **Cron conservado (autorizado por ti):** el ZIP no incluía `routes/cron_prewarm.py` ni `.emergent/crons.yml`; se conservaron y se re-añadieron 2 líneas en `server.py` (import + `include_router`).
2. **`tests/test_my_space.py` (3 líneas, autorizado):** las líneas 124-126 usaban f-strings con comillas anidadas (`{r.json()["id"]}`), sintaxis Python **3.12+**; este entorno es **3.11.16**. Cambiado a `{r.json()['id']}` (solo comillas internas, sin tocar lógica). Es el único fichero del ZIP incompatible con 3.11.
3. **`xlrd==2.0.1`** instalado (nueva dependencia declarada en el `requirements.txt` del ZIP).
4. `PREWARM_CRON_BATCH/DELAY` se tocaron temporalmente para la tanda de prueba y se **restauraron** a 40/2.

## 8. Observaciones (no bloqueantes)
- NVIDIA primario `mistralai/mistral-nemotron` con `ReadTimeout` intermitente ahora mismo; el failover a `meta/llama-3.2-11b-vision-instruct` funciona (disponibilidad del proveedor, no del ZIP).
- Errores de CNMV/BME por Playwright/chromium no instalado en el pod: pre-existentes y ajenos al ZIP.

## 9. Notas para producción (pendiente, no aplicado en Preview)
- Con `ARROBA_ENV=production` el arranque **falla** si `CORS_ORIGINS="*"` → fijar origen exacto de Beta.
- Repetir la comprobación de duplicados de `my_space_requests` en el Mongo de producción **antes** de crear `uniq_listing_buyer`.
- `WEBHOOK_CRON_SECRET` debe existir en el entorno de producción.
