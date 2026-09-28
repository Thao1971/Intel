# Architecture CHANGELOG

> Registro de cambios de arquitectura de la plataforma Agency Tool (compartida: Valuo.pro + arroba.com + Platform Console).

## 2026-09-28 — Delta `ARROBA_INTEL_DELTA_SCREEN_GRADE` (Preview) ✅
- **SHA-256 del ZIP verificado** (`5e9853d4…c9359`). 2 archivos, aplicados full-file, sin tocar nada más. Sin commit/push/reset.
- **`services/engines/valuation/reconciliation.py`**: cuando `total_raw <= 0` (ningún método reconciliado) pero el `valuation` trae cifra de respaldo (`enterprise_value`+`range`), devuelve nuevo estado `screen_grade` con rango, `confidence:0.0` y warnings `no_valuation_method_reconciled` + `screen_grade_single_method_estimate`. Sin respaldo → sigue `unavailable` (igual que antes). R15 intacta.
- **`services/engines/valuation/contract.py`**: propaga `screen_grade`; `status` ∈ {available, screen_grade, unavailable}; `ev_range` incluido para screen_grade.
- **Validación Preview**: py_compile OK; suite valoración 71 passed / 1 failed (fallo preexistente de precisión float en `test_private_company_adjustments.py`, módulo no tocado por el delta). NCR España B28031458 en vivo → `screen_grade`, EV 74.437.509 €, rango 52.106.257–96.768.762 €, 2 warnings (coincide con LEEME). Regresión: SERVIER/OPEL siguen `available`.
- **Pendiente (fuera de este delta)**: Beta necesita su paquete `07_BETA_...SCREEN_GRADE` para pintar el estado; calibración sectorial `valuation-calibration-2026-09-28-b0f80f6076` publicada pero NO activada (352 candidatos `active:false`); aprobación negocio/legal de la redacción de advertencias.


## 2026-09-28 — Delta `ARROBA_INTEL_DELTA_20260928` (Preview) ✅
- **SHA-256 del ZIP verificado** (`045632b7…433d19`). 2 archivos, aplicados tal cual (full-file), sin tocar nada más. Sin commit/push/reset.
- **`routes/auth.py`**: cierra el registro público de admin. `POST /api/v1/auth/register` ahora exige token de un admin existente vía nueva dependencia `require_admin` (sin token→401, no-admin→403, admin→200). `login`/`api-keys`/`me` sin cambios.
- **`routes/company_screener.py`**: `GET /api/v2/company-intelligence/screen/signals` añade clave **aditiva** `labels_es` (34 etiquetas ES por `signal_type`); `signals` intacto. Import `Dict` añadido.
- **Validación Preview**: py_compile OK; cobertura `SIGNAL_LABELS_ES` == `taxonomy.SIGNAL_TYPES` (34/34 exacto); register 401/403/200 verificados (usuarios de prueba creados y borrados); `/screen/signals` devuelve `signals`+`labels_es`(34). 
- **Nota**: el bug conocido `get_current_user` `KeyError:'id'` (clave de servicio como Bearer) sigue sin tocar por indicación de Daniel (problema aparte).


## 2026-09-25 — Aplicación ZIP `ARROBA_INTEL_EMERGENT_20260925_REVISADO_CODEX` (Preview) ✅
- **SHA-256 verificado** (`425afe3f…eecba5b`). Entrega consolidada completa del backend aplicada sobre `/app/backend` conservando `.env`, datos y config de despliegue. Backup: `/app/memory/backups/backend_pre_codex_20260925_192538.tar.gz`. Sin commit/push/reset.
- **Novedades del ZIP**: motor de valoración avanzada (`services/engines/valuation/*`), `screener`, `sector_market`, sistema `my_space_*` (services+routes) con **protección de concurrencia** en solicitudes/NDA, `config_guard.py`, tests.
- **Concurrencia my_space_requests**: índice único `uniq_listing_buyer (listing_id, buyer_id)` creado en arranque; `DuplicateKeyError` → `ValidationError` (sin exponer Mongo); cambios de estado condicionales por `expected_status` (segundo actor concurrente recibe error claro).
- **Cron conservado (autorizado)**: `routes/cron_prewarm.py` + `.emergent/crons.yml` intactos; `cron_prewarm` re-registrado en `server.py` del ZIP. Verificado: ruta en OpenAPI, 401 sin/mal auth, tanda limpia (acquire→genera→run record→release) y protección de solapamiento.
- **Desviaciones**: (1) 3 líneas en `tests/test_my_space.py` (f-string 3.12 → compat 3.11, sin lógica); (2) `xlrd==2.0.1` instalado (declarado en requirements del ZIP); (3) cron conservado.
- **Validación**: `py_compile` todo el backend 0 errores (py3.11); `pytest` solicitudes+my_space+delivery_hardening **27 passed**; smoke en vivo 200 de valoración (contrato Beta), analyze, ficha, market async, sector, geo.
- **Observación**: NVIDIA primario `mistral-nemotron` con ReadTimeout intermitente; failover `llama-3.2-11b-vision` OK (disponibilidad del proveedor, no del ZIP).
- **Pendiente producción**: `ARROBA_ENV=production` exige `CORS_ORIGINS` exacto; repetir preflight de duplicados en Mongo prod antes de crear `uniq_listing_buyer`; `WEBHOOK_CRON_SECRET` en el entorno.



## 2026-09-25 — Precalentamiento de descripciones como CRON de plataforma (reemplaza al worker de 12h)
El worker continuo de supervisor era frágil (el pod de Preview se suspende por inactividad y el deadline es de reloj de pared; en el run anterior solo generó 568/22.5k antes de suspenderse). Sustituido por una tarea programada nativa de Emergent, robusta para producción (servidor siempre activo).
- **`.emergent/crons.yml`**: `prewarm-descrip`, `*/15 * * * *`, `POST {{BASE_URL}}/api/cron/prewarm-descriptions`. Se sincroniza sola al desplegar.
- **`backend/routes/cron_prewarm.py`** (`/api/cron/prewarm-descriptions`): valida `Authorization: Bearer WEBHOOK_CRON_SECRET` (comparación en tiempo constante, 401 si falta/incorrecto), **ACK 2xx inmediato** y procesa el lote en `asyncio.create_task`. Lote configurable `PREWARM_CRON_BATCH` (40) / `PREWARM_CRON_DELAY` (2). **Lock por lease en Mongo** (`prewarm_cron_lock`, 14 min) evita solapamiento entre disparos; **soft-stop a 12 min** corta el lote antes de que expire el lease. Registra cada corrida en `prewarm_cron_runs` (attempted/generadas/fallidas/reparto_por_modelo/fallback_used/motivos/pendientes_restantes/cache_total). Reanudable e idempotente (caché excluye lo hecho); no-op cuando no quedan pendientes (0 coste). Reutiliza `resolve_description` (guarda de calidad + trazabilidad).
- **`backend/.env`**: nuevo `WEBHOOK_CRON_SECRET` (secreto). Retirado el programa de supervisor `prewarm` (superado).
- **Verificado en Preview:** ruta registrada en OpenAPI; 401 sin/मal auth; ciclo completo con lote de prueba (generadas 3/3, `pendientes_restantes=21962`, cache 671→674, lock liberado al terminar); doble disparo simultáneo → el segundo no-op por lock; `crons.yml` válido. Restaurado a batch=40/delay=2.
- **Para producción:** el `crons.yml` y el endpoint se despliegan con la app; el pipeline debe asegurar `WEBHOOK_CRON_SECRET` (y opcional `PREWARM_CRON_BATCH`/`PREWARM_CRON_DELAY`) en el entorno de producción. Autorizado consumir presupuesto NVIDIA de forma continua hasta agotar ~22.5k y luego no-op.


## 2026-09-16 — Semáforo de concurrencia LLM + paquete de despliegue Market (para el pipeline de producción)
- **Semáforo (`model_provider.py`):** `_send_message_threaded` ahora limita la concurrencia con `_get_llm_semaphore()` (asyncio.Semaphore lazy). Configurable con **`LLM_MAX_CONCURRENCY`** (por defecto **2**). Evita saturar el threadpool/proveedor cuando varias fichas/lecturas se generan a la vez. Validado: /market pending 0,37 s → ready → cache, sin regresión.
- **Smoke OpenAI:** `_call_openai` (gpt-5.2, aislado en hilo) devuelve JSON válido en ~3 s y NO bloquea el loop (56 ticks durante la llamada). Nota: ninguna ruta actual pasa `provider="openai"` (todos los `generate_*` usan claude por defecto).
- **Paquete de despliegue para producción** en `/app/deploy_market/` y ZIP `/app/emergent-intel-market-deploy-160926.zip` (SHA256 `8d2080ec…`). Contiene `market-async-concurrency-intel.patch` (hunk-based, 4 ficheros/9 hunks: company_summary market-async + company_ficha reading_status + model_provider concurrencia+semáforo + test nuevo), instrucciones, rollback (`patch -R`), variable nueva `LLM_MAX_CONCURRENCY=2`, checklist de validación de producción, contrato Beta y `SHA256.txt`. Sin secretos ni `.env`. Verificado reverse-apply (dry-run) contra el código actual y forward-apply+py_compile sobre baseline reconstruida.


## 2026-09-16 — Parche INTEL market-async: narrativa de mercado asíncrona (pending → ready) ✅ (solo PREVIEW)
Aplicado `market-async-intel.patch` (checksum OK) por hunks (`patch -p1`, offset 4 por ediciones NVIDIA previas, sin conflictos), conservando todos los cambios recientes de NVIDIA/trazabilidad/guardas.
- **`services/company_summary.py`:** `resolve_market_reading` refactorizado en `_market_reading_material` + `_generate_market_reading` + `defer_market_reading` (+ `resolve_market_reading` de compatibilidad). `defer_market_reading` devuelve estados públicos `ready` (caché Mongo), `pending` (una única tarea en curso, dedupe por `_MKT_INFLIGHT`) y `unavailable` (sin contexto o fallo reciente vía caché negativa `_MKT_FAILURE_UNTIL`/`_MKT_FAILURE_TTL=300s`). No bloquea la petición HTTP (`asyncio.create_task`).
- **`routes/company_ficha.py`:** `market()` añade `reading_status` (null en /ficha con `include_reading=False`); `/market` usa `defer_market_reading` → expone `reading_status: pending|ready|unavailable`.
- **`tests/test_market_reading_deferred.py`** (nuevo): dedupe pending→ready + unavailable. 2/2 PASSED (instalado `pytest-asyncio`).
- **Fix de concurrencia (opción a, autorizado):** `_call_claude`/`_call_openai` ahora ejecutan la llamada de `emergentintegrations` en un hilo con su propio loop (`_send_message_threaded` → `asyncio.to_thread`), porque bloqueaba el event loop del único worker de uvicorn y hacía que la primera `/market` tardara ~15 s pese a devolver `pending`. NO toca NVIDIA (descripciones) ni la lógica del parche.
- **Validación E2E (Preview, service-key):** primera `/market` sin caché = **pending en 0,44 s** (<500 ms); polls siguientes `pending` sin regenerar; al terminar Claude `ready` con `reading_ai`; siguiente llamada `ready` inmediato desde `market_readings`; delta caché **+1** con **1** `background_started` (una sola generación por `master_id+ctx_hash`); `unavailable` para empresa sin contexto; `/ficha` mantiene latencia V4 (0,28 s). **NO desplegado a producción** (intel.arroba.com), a la espera de la orden de Daniel.
- **Contrato Beta:** `/market` incluye `reading_status`; Beta debe seguir consultando mientras reciba `pending` (no convertirlo en `unavailable`) y al recibir `ready` mostrar `reading_ai` y detener el polling.


## 2026-09-16 — Precalentamiento de descripciones de compañía (NVIDIA) ✅ (solo PREVIEW)
Activado `backend/scripts/prewarm_company_descriptions.py`. No afecta a Beta ni a la narrativa de mercado (Claude).
- **Modelos NVIDIA:** el `NVIDIA_MODEL` previo (`meta/llama-3.3-70b-instruct`) y el fallback por defecto (`meta/llama-3.1-8b-instruct`) devuelven **410 Gone**. Tras escanear el catálogo (82 modelos, la mayoría 404 "función no disponible para la cuenta"), operativos y aptos: `mistralai/mistral-nemotron` (limpio, mejor calidad), `meta/llama-3.2-11b-vision-instruct` (limpio, no-razonador). **DESCARTADO** `nvidia/nemotron-3-super-120b-a12b`: es un modelo de razonamiento que vuelca su CoT en `content` → envenenó la caché (docs de 442 y 1 palabra, borrados).
- **Config persistida en `backend/.env`** (nombres de modelo, no secretos): `NVIDIA_DESC_MODEL="mistralai/mistral-nemotron"` (primario), `NVIDIA_MODEL_FALLBACK="meta/llama-3.2-11b-vision-instruct"` (fallback). `NVIDIA_MODEL` (410) se dejó sin cambiar: solo se usa como default de `_call_nvidia` cuando no se pasa modelo, y el único llamador (`generate_company_description`) siempre pasa `NVIDIA_DESC_MODEL`, así que la ruta de descripciones NO depende de él.
- **Cambios de código** (`docstudio/model_provider.py`, `services/company_summary.py`):
  - Trazabilidad: `_call_nvidia` marca `_fallback_used`; `_call_provider` gana `keep_meta=True` para conservar `_model`/`_fallback_used` internamente (NUNCA expuesto en /ficha); `resolve_description` guarda en `company_descriptions` el `model` real (primario o fallback) y `fallback_used`.
  - Guarda anti-basura `_reject_description`: rechaza salidas sin JSON válido, <3 o >120 palabras, o con marcadores de razonamiento; se eliminó el fallback a `raw_text` que había guardado la fuga de CoT.
  - Prompt V3 reforzado: alcanzar 40-75 palabras cuando la fuente lo permita; prohibición estricta de mencionar el nombre/razón social.
  - **Bugfix crítico:** `web_description` es un **dict** (`{description, ...}`) en casi todas las empresas; el script pasaba el dict a `resolve_description` → crash `'dict' object has no attribute 'strip'`. Corregido en `scripts/prewarm_company_descriptions.py` (extrae `wd.get("description")`).
- **Validación:** vista previa `--limit 100` (pending=22630); prueba real `--execute --limit 5` (5/5 por primario, 40-75 palabras, sin nombre, trazabilidad OK); tanda de 100 con `--delay 2`: **93 generadas / 7 fallidas** (cortes por timeout 25 s), avg 11,1 s, reparto `mistral-nemotron=38` + `llama-fallback=55` (NVIDIA sobrecargado durante la corrida). Borrados 3 docs del fallback con meta-comentario ("su objeto social no menciona…"). `company_descriptions`=106, todos `source=ai`. `/ficha` lee de caché (0,86 s, 0 llamadas NVIDIA). **NO ejecutado el lote de 22.527 restante** (pendiente de aprobación).
- **Worker en 2º plano (12h, resumable) — supervisor:** `backend/scripts/prewarm_worker.py` + `/etc/supervisor/conf.d/prewarm.conf` (`[program:prewarm]`, `autostart=true`, `autorestart=unexpected`, `exitcodes=0`). Reanudable (idempotente por caché), tope de 12h persistido en `prewarm_state.json` (sobrevive a reinicios del pod: al relanzar dice "REANUDANDO" y conserva deadline+stats). Backoff de 60 s ante caídas de NVIDIA. Progreso en `prewarm_progress.json` (generadas/fallidas/reparto_por_modelo/fallback_used/motivos/horas_restantes), log en `prewarm_worker.log`. Al llegar al deadline marca `done=true` y sale 0. Arrancado 2026-09-16T16:16Z → deadline 2026-09-17T04:16Z.
- **Guarda endurecida (2a):** `_reject_description` rechaza también meta-comentario (`_META_MARKERS`: "no menciona", "sin especificar si", "no se especifica", "objeto social no", …) para que el fallback `llama-3.2-11b-vision` no envenene la caché sin supervisión.


## 2026-09-16 — Parche INTEL V4 (rendimiento `/ficha`): narrativa Claude fuera del camino crítico ✅ (solo PREVIEW)
Aplicado `emergent-intel-ficha-rendimiento-v4-160926.zip`. De los 4 archivos del ZIP, 3 eran idénticos a los actuales (SHA256 coincide: `company_summary.py`, `docstudio/model_provider.py`, `scripts/prewarm_company_descriptions.py`); **solo cambió `routes/company_ficha.py`** (SHA256 destino `f6e41ef4…`). El diff aplicó limpio sobre la versión actual (base exacta que V4 esperaba), sin pisar trabajo reciente de Emergent. Backup del previo en `/tmp/company_ficha.pre_v4.bak`.
- **Cambios:** helper `_timed_ficha_block` que loguea `company_ficha.block_duration block=<nombre> duration_s=<seg>`; `market()` gana `include_reading=True` por defecto; `/ficha` llama a `market(..., include_reading=False)` para NO esperar la narrativa IA; los 9 bloques (finances, governance, market, capital_markets, signals, control_graph, ownership, events, description) se ejecutan en paralelo con `asyncio.gather`; dentro de `market()` sector/geo/concentración/posición también en paralelo. `/ficha` sigue con `generate_if_missing=False` (usa descripción v3 cacheada/web, sin llamar a proveedor).
- **Validado E2E (preview, service-key `X-API-Key`)** con empresa SIN caché `B95222139` (desc_cached=0, market_reading=0):
  - Cold `/ficha`: **0,20 s**, HTTP 200, `market.reading_ai=null`, sin auditoría summary/Claude. 9 bloques logueados: description 0,002 · ownership 0,005 · signals 0,015 · governance 0,018 · events 0,022 · control_graph 0,023 · finances 0,029 · capital_markets 0,036 · market 0,039.
  - `market-reading` diferida (`GET /market`, include_reading=True): **12,96 s**, generó narrativa con `claude-sonnet-4-6` (LiteLLM), `reading_ai` string no vacío, `provenance.reading_ai=ai_narrative`, cacheada en `market_readings` (9→10).
  - Repetición caliente: `/ficha` 0,30 s, `/market` 0,18 s con `reading_ai` servido de caché y **0** nuevas llamadas a LiteLLM.
- Sin desplegar a producción (intel.arroba.com), por acuerdo con Daniel. Batch `prewarm_company_descriptions.py` NO ejecutado (pendiente de configurar/verificar `NVIDIA_DESC_MODEL`; el modelo `meta/llama-3.1-8b-instruct` devolvía HTTP 410).



## 2026-09-11 — Ingesta PROD `20260821_base.zip`: fases de DATO completadas + rebuild DIRIGIDO (no full) de señales/semántico ✅ (PRODUCCIÓN Atlas)
El worker `run_delivery_worker` (PID 2454) contra Atlas completó y verificó las fases de DATO: legacy_ingest (+611 empresas nuevas, 389 modificadas), balances (+2.542), master_builder full (25.603), ownership_graph (2.805 aristas, 140 resueltas, 15 grupos). Conteos Atlas post-ingesta: master_companies/companies_master 25.603, norm_financials 16.044, norm_officers 88.122, norm_ownership 2.805, signals 66.3xx, semantic_profiles 25.868.
- **HALLAZGO (medido, no estimado):** las fases finales `signal_builder` + `semantic_index` del worker recomputan TODO el universo (25.603) una a una contra Atlas a ~0,3-0,5/s → ETA ~24-30 h. Innecesario para una entrega incremental de ~1.000 empresas (las 25k existentes ya tienen señales + embeddings de despliegues previos). El traspaso anterior asumía "termina pronto" — era incorrecto.
- **DECISIÓN (Daniel, opción b):** parado el recompute completo; lanzado `scripts/targeted_rebuild_delivery.py` que recomputa señales + perfil semántico + embedding SOLO de las 1.000 empresas de la entrega (`master_companies.sources.source_version == delivery_prod_7002ffb947`). Script auto-contenido: captura MONGO_URL/DB_NAME/OPENAI_API_KEY del proceso worker vía `/proc/<pid>/environ` (NUNCA imprime la URI), para el worker (SIGTERM→SIGKILL con guardia de cmdline), reconstruye, marca el run como `completed_targeted` y el sub-run `_modern` como `stopped_after_data_phases`. Progreso persistido en `iberinform_delivery_runs.targeted_rebuild`.
- **Estado:** ✅ COMPLETADO (18:02). Rebuild dirigido terminado: señales 1000/1000 (0 err, 3592 s) + semántico 1000/1000 con 1000 embeddings (0 err, 3956 s); total ~2 h 6 m. Run `delivery_prod_7002ffb947` marcado `completed_targeted` en `iberinform_delivery_runs` (`targeted_rebuild`: targets 1000, signals_ok 1000, semantic_ok 1000, semantic_emb 1000, duration_s 7548). Sub-run `_modern` marcado `stopped_after_data_phases`. Las 611 empresas nuevas + 389 modificadas quedan con señales + perfil semántico + embedding al día en prod. El dato núcleo estaba vivo desde las fases de DATO; la inteligencia (señales/semántico) ya está completa para la entrega.
- Cero deploy de código a prod (solo dato), por acuerdo con Daniel. Helpers de sesión: `scripts/targeted_rebuild_delivery.py` (reutilizable para futuras entregas incrementales; capta config de Atlas del worker sin imprimir la URI).


## 2026-09-11 — Taxonomía: desempate por PADRE COMÚN en `resolve_label` (fix bug "software") ✅ (solo PREVIEW)
`services/taxonomy/search.py::resolve_label()`. Bug de backlog (ROADMAP, priorizado por Daniel): "software" empataba las 6 industrias de S02 (Software empresarial/financiero/RRHH/comercial/marketing/Desarrollo de software) y el desempate por longitud de etiqueta devolvía arbitrariamente "Software de RRHH" → buscar "software" solo daba empresas de RRHH, no un resultado general de software.
- **Fix (idea (a) de Daniel):** cuando el grupo de mejores empates (mismo n-grama, mismo nivel, misma exactitud) son **≥3 nodos DISTINTOS que comparten un ÚNICO padre**, se resuelve al PADRE en lugar de a una hoja arbitraria. Umbral en 3 a propósito: un empate de 2 suele ser un par de sinónimos donde una hoja SÍ es la respuesta canónica (p.ej. "farmaceutico" empata "Industria farmacéutica" + "CRO y servicios farmacéuticos" → debe quedarse en "Industria farmacéutica", NO saltar al sector S05). Coincidencias EXACTAS (forman su propio top_rank) y padres None (sectores/dimensiones) quedan protegidos. Añadidos `parent_id` al índice de etiquetas + mapa `_NODE_BY_ID`; constante `_GENERIC_PARENT_MIN_TIES=3`.
- **Verificado:** unit (software→S02 "Tecnología"; farmaceutico/farmaceutica/laboratorio farmaceutico→Industria farmacéutica; Tecnología→S02; salud→S05; adtech/fintech/biotecnología/ciberseguridad/IA→industria específica; desarrollo de software→industria exacta) + tests taxonomía 3/3 verdes + py_compile OK. E2E por URL de preview (service-key): `search?q=software` → resolved S02, count 859; `q=farmaceutico` → Industria farmacéutica, count 61; `q=marketing` → S03, count 2302.
- Efecto colateral (menor, benigno): "marketing"/"agencias" a secas ahora resuelven al sector S03 (antes hoja arbitraria) — más sensato para términos genéricos. Sin regresión en los casos curados (alias corren antes) ni en los tests.
- Sin desplegar.


## 2026-09-10 (b) — top-dynamic: `cnae_level_es` por fila ✅ (solo PREVIEW)
`routes/sector_intelligence.py`: `_sector_card()` añade `cnae_level_es` (etiqueta traducida del nivel CNAE vía nueva constante `_CNAE_LEVEL_ES = {section:"Sección", division:"División", group:"Grupo"}`), para que Beta etiquete cada fila del ranking multi-nivel sin mapeo propio (venía `null`). Verificado: `/top-dynamic?level=section,division&limit=6` → las 6 filas con `cnae_level_es` no-nulo; single-level intacto; suites externa 11/11 + smoke 7/7 PASS. Sin desplegar.


## 2026-09-10 — Paquete "Intel-70926 deploy pendiente" (Home nueva) ✅ (solo PREVIEW)
Zip con 3 ficheros. `engine.py` NO se toca: ya estaba aplicado íntegro en rondas previas (valuation prosa + range.central + scenarios.name + benchmark plano + evolution 11 líneas); las únicas diferencias del zip eran un comentario y un orden de claves, y además el pod va por delante (tiene el reorden `multiple_basis`/`multiple` que Daniel pidió en la ronda b) — aplicarlo lo revertiría. Aplicados los 2 ficheros nuevos del paquete Home:
1. `routes/business_demography.py` — `_card()` (usada por `/overview`, `/active-companies`, `/new-companies`, `/closed-companies`, prefijo `/api/v1/public/business-demography`): elimina el campo ambiguo `change_pct` (era interanual) y expone `change_pct_mom` (desde `mom_change_pct`, ya guardado en el doc pero no salía) + `change_pct_yoy`. ⚠️ Consumidor en Beta (Mapa Empresarial) leía `change_pct` → debe migrarse a `change_pct_yoy` (fix en el paquete Beta hermano; desplegar juntos o Intel primero).
2. `routes/sector_intelligence.py` — `GET /top-dynamic`: `level` acepta lista separada por coma (`section,division,group`) además del valor único; valida contra `_VALID_CNAE_LEVELS` (422 si vacío/ inválido); respuesta añade `levels` (lista) manteniendo `level` (string) por compat.
- Verificado end-to-end: overview → cards con `change_pct_mom`/`change_pct_yoy`, sin `change_pct` (new_companies mom -0.0315, yoy -0.154). top-dynamic nivel único OK (compat), multi-nivel mezcla 5 section + 1 division, `level=foo`/`section,foo` → 422. Suites externa 11/11 + smoke 7/7 PASS, compila limpio.
- Sin desplegar.


## 2026-09-09 (g) — Gobierno: traducción de 134 roles ingleses + reclasificación de 54 ✅ (solo PREVIEW)
`routes/company_ficha.py`. Patch de Daniel (2 ediciones):
1. `_ROLE_ES`: añadidas traducciones ES de los 134 roles ingleses que se mostraban en crudo (terminología societaria; `Creditors? Commission` con `?` literal por mojibake de origen, match exacto).
2. `_ROLE_GROUP`: reclasificados 54 de esos 134 en grupo real (35 administracion, 9 apoderados, 10 auditor); los otros 80 (comisionados/liquidadores concursales/comités complejos) se quedan en "otros" a propósito, ya traducidos.
- Verificado: sanity `_role_es`/`_role_group` OK (Member Of The Board Of Directors→administracion, Officer→Apoderado/apoderados, Alternate Accounts Auditor→auditor, Tax Representative→apoderados, Audit Commission→auditor; Creditors?/Bankruptcy Liquidator→otros). Roles sin traducción = 4 (los ES crudos, que ya están en español, no la necesitan) → 0 inglés crudo restante. En grupo "otros": 95 (los 80 previstos + ~15 originales). Servier sin cambios (27, 0 duplicados, {admin:2, apoderados:24, auditor:1}). Suites externa 11/11 + smoke 7/7 PASS, compila limpio.
- Sin desplegar.


## 2026-09-09 (f) — Gobierno: dedup por persona + mapeo de 4 roles ES crudos ✅ (solo PREVIEW)
`routes/company_ficha.py`. Patch final de Daniel para el hallazgo de duplicados (2 ediciones):
1. `_ROLE_GROUP`: añadidos los 4 únicos `role` en español crudo que existen en `norm_officers` (tal cual, case-sensitive): `Apoderado`→apoderados, `Administrador Solidario`/`Administrador Único`→administracion, `Auditor Cuentas Conjunto`→auditor. (Los otros 134 roles ingleses sin mapear siguen cayendo a "otros" a propósito — fuera de alcance, degradan limpio.)
2. `governance()`: dedup cambia de `(person_key, role)` a solo `person_key`, quedándose con la fila que clasifique en grupo real (no "otros") y, a igualdad, mayor `year`. Elimina el doble listado de cada persona (fila inglesa + fila española).
- Verificado Servier `/governance`: **officers_count 55 → 27**, **0 duplicados por nombre**, reparto {administracion:2, apoderados:24, auditor:1}, `since_iso` en todos, orden por grupo+fecha correcto. Suites externa 11/11 + smoke 7/7 PASS, compila limpio.
- Sin desplegar.


## 2026-09-09 (e) — Gobierno: orden por grupo de cargo + fecha ISO normalizada ✅ (solo PREVIEW)
`routes/company_ficha.py`. Patch de Daniel aplicado tal cual (2 ediciones):
1. `governance()`: `appointment_date` (formatos mixtos `DDMONYYYY` / `dd/mm/yyyy`) se normaliza a ISO `YYYY-MM-DD` en `since` (+ nuevo `since_iso`); orden por grupo de cargo (Administración→Apoderados→Auditoría→Otros) y fecha desc dentro de grupo (antes ordenaba por `year`, uniformemente 2024 = inútil). Nuevos campos por officer: `since_iso`, `role_group`, `role_group_es`.
2. Helpers nuevos: `_parse_officer_date()`, `_MONTH_ABBR_EN`, `_ROLE_GROUP` (60 roles→4 grupos), `_ROLE_GROUP_ORDER`, `_ROLE_GROUP_ES`, `_role_group()`. R15: solo reformatea/clasifica valores reales; fecha/rol no reconocidos → None/"otros".
- Verificado: Servier `/governance` → 55 officers, `since` ISO en todos (since_iso=None=0), orden correcto por grupo+fecha. Suites externa 11/11 + smoke 7/7 PASS.
- ⚠️ HALLAZGO DE DATOS (reportado a Daniel, sin tocar): `norm_officers` guarda CADA persona DOS veces con `role` distinto — uno en inglés (`Representative`, `Joint And Several Director`, mapeado a grupo) y otro en español crudo (`Apoderado`, `Administrador Solidario`, `Auditor Cuentas Conjunto`, NO mapeado → caen a "Otros"). Servier: 27 personas reales → 55 filas. El dedup por `(person_key, role)` no colapsa los duplicados porque el `role` difiere. La tabla muestra a cada persona 2 veces (una en su grupo, otra en "Otros"). Pendiente de decisión de Daniel (spec) — no es regresión del patch (el dedup era así antes).
- Sin desplegar.


## 2026-09-09 (d) — Grafo de control click-to-expand: fallback por CIF crudo + expandable ampliado ✅ (solo PREVIEW)
Contrapartida Intel del fix de cobertura del click-to-expand. `routes/company_ficha.py`:
1. Import: `normalize_cif` desde `services.data_layer.normalize`.
2. `connections()` refactorizado a dispatcher: si el `node_id` resuelve a master → `_connections_from_master()` (lógica previa byte-idéntica, ahora con `coverage.resolution="master_relationships"`); si NO resuelve → nuevo `_connections_from_raw_cif()` que cruza `norm_ownership` por `counterparty_cif` (qué otras empresas ya mastereadas declaran a ese CIF como accionista/participada) y devuelve `coverage.resolution="raw_cif_crossref"`. R15: solo reexpone lo declarado, cero fabricación; 404 limpio si no hay referencia cruzada.
3. `_control_graph_block()`: `expandable` de shareholders/subsidiaries pasa de `bool(master_id)` a `bool(master_id or cif)` — un vecino conocido solo por CIF (típico: counterparty sin ficha propia, ej. DANVAL-SA/Servier) ya es candidato a expandir porque el fallback puede resolverlo.
- Verificado: Servier control-graph → 5 nodos, 2 expandable (ambos cif-sin-master, antes no expandibles). `/company/A79479846/connections` (DANVAL-SA) → HTTP 200 (antes 404), available=true, resolution=raw_cif_crossref, owned_by=2. Suites externa 11/11 + smoke 7/7 PASS, compila limpio. Sin desplegar.


## 2026-09-09 — valuation(): hipótesis en prosa ES (diff de Daniel, aplicado tal cual) ✅ (solo PREVIEW)
- `services/engines/financial/engine.py::valuation()`: las cadenas de `hypotheses[]` pasan de jerga cruda ("Múltiplo EV/EBITDA sectorial (sección M) = 6.5x (REFERENCIA inferida)") a prosa cuidada en español. Nueva `_fmt_eur()` (formato "1.696.320 €"). Afecta a las 6 ramas: `_nd_hyp` (deuda conocida/desconocida), múltiplo real M&A Radar, múltiplo sectorial inferido, EV/Ingresos, valor en libros y datos insuficientes. **No cambia ningún campo numérico ni la estructura del contrato — solo texto.**
- Verificado: `py_compile` OK; `_fmt_eur(1696320)` → "1.696.320 €". Endpoint real de este pod: `valuation` devuelve method `ev_ebitda`, `multiple_basis` `inferred_reference` y hypotheses en prosa ("El múltiplo de 7.5× es una referencia sectorial (sección CNAE C)…", "Se ha restado la deuda financiera neta (deuda − caja: -520.970 €)…").
- **Suites existentes**: externa (contrato API) 11/11 PASS y smoke financial-intelligence 7/7 PASS contra este pod. NOTA: los ficheros de test tienen hardcodeado el `BASE_URL`/`API_KEY` de OTRO pod (`data-factory-hub`, sesión previa), por eso `pytest` directo daba 404; corridos apuntando a `REACT_APP_BACKEND_URL` de este pod pasan todos. (Latente: convendría que el test externo leyera `BASE_URL` de env como dice su docstring — no tocado por no salirse del diff pedido.)
- **Sin desplegar**: preview hasta que Daniel autorice el deploy aparte.

## 2026-09-09 (b) — valuation()/_valuation_full(): 3 correcciones de contrato para la ficha (diff de Daniel) ✅ (solo PREVIEW)
Encontradas revisando la ficha F01 pestaña Valoración. No cambian method/multiple/multiple_basis/confidence/equity_value/enterprise_value — solo estructura que Beta ya esperaba:
1. Los 3 `range` de `valuation()` incluyen ahora `central` (= round(ev,0)); antes solo low/high y la fila "Medio" del EV salía "No disponible".
2. `scenarios[]` de `_valuation_full()` usan clave `name` (no `label`) — Beta leía `.name` y caía al fallback "Escenario 1/2/3".
3. `benchmark` de `_valuation_full()` reescrito como objeto plano (`peers_count/scope/median_ebitda_margin/subject_ebitda_margin/median_revenue/subject_revenue/ebitda_margin_percentile`, contrato `ValuationBenchmark`); antes era lista que Beta no leía y solo se emitía con peers → el card "Benchmark del sector" salía vacío para todas. Ahora se emite si hay margen/ingresos propios o peers (R15: resto a null, sin inventar).
- Verificado end-to-end en este pod: range `{low,central,high}`, scenarios name conservador/base/optimista, benchmark dict con peers_count=8/subject_revenue poblados. Suites externa 11/11 + smoke 7/7 PASS (apuntando a REACT_APP_BACKEND_URL).
- Sin desplegar.

## 2026-09-09 (c) — compute_evolution(): exponer las 11 líneas de balance por año (pestaña Balance) ✅ (solo PREVIEW)
Mismo síntoma que el fix de PyG de esta mañana pero en la pestaña Balance (Sobron B95222139): 2022/2023/2024 en "—", solo el último ejercicio con dato, pese a haber histórico real.
- Causa: `metrics.py::_year_metrics()` ya calculaba las 11 líneas de balance por año, pero `compute_evolution()` (engine.py) solo proyectaba a `points[]` revenue/ebitda/net_income + derivados; el resto no salía nunca al API.
- Fix: en el dict de cada punto de `points[]` (tras `"employees": None`) se añaden 11 claves tomadas de `s` (sin calcular nada nuevo): `current_assets, non_current_assets, total_assets, cash, current_liabilities, non_current_liabilities, total_liabilities, st_debt, lt_debt, financial_debt, equity`. Nada más de la función cambia (revenue/ebitda/net_income/márgenes/working_capital/net_financial_position intactos).
- Verificado end-to-end: `evolution.points` trae las 11 claves para TODOS los años — Sobron 2022-2025 (total_assets/equity poblados, financial_debt=None por no reportarlo), Servier 2022-2024 (9 con dato). Suites externa 11/11 + smoke 7/7 PASS, compila limpio, ningún test roto.
- Sin desplegar.



## 2026-09-09 — Batch Intel 3 puntos (paginación determinista + orden por columna + buscador predictivo) ✅ (solo PREVIEW)
Autorizado por Daniel. Todo backend, aditivo, sin romper contratos (solo 2 params opcionales nuevos). Verificado con testing_agent (iteration_17): **17/17 tests PASS, 100%**, sin incidencias.

- **Punto 1 — Desempate determinista en paginación** (evita duplicados/huecos entre páginas cuando muchos docs empatan en el campo de orden):
  - `services/taxonomy/search.py::search_by_taxonomy()`: `.sort("confidence", -1)` → `.sort([("confidence", -1), ("company_id", 1)])`.
  - `services/skills_search.py::search_companies()`: consulta del pool → `.sort([(sort_field, -1), ("master_company_id", 1)])`; re-sort en Python → `key=lambda x: (-x[0], x[1]["master_company_id"])`.
- **Punto 2 — Orden por columna sobre TODO el resultado** (params opcionales `sort_by`/`sort_dir` en `GET /api/v1/company-taxonomy/search` y `POST /api/v1/skills/search`):
  - Whitelist (Grupo A, campos guardados): `name`, `revenue`, `ebitda`, `employees`, `cif`. Cualquier valor fuera de la whitelist se **ignora** (cae al comportamiento actual) — nunca se arma el path de Mongo con el string crudo del cliente (verificado: `sort_by='DROP TABLE'` → fallback a relevancia).
  - `search_by_taxonomy`: con `sort_by` válido resuelve el pool completo de `company_ids` (tope `_TAXO_SORT_POOL_CAP=3000`, orden estable por `company_id`) y pagina sobre `master_companies` ordenado en BD con desempate por `master_id`. **Por diseño**: para nodos muy grandes (p.ej. S09 = 8458) el orden es sobre ese pool de 3000, no el máximo global (decisión explícita de Daniel).
  - `search_companies`: con `sort_by` válido empuja el orden a la consulta Mongo inicial y salta el scoring de relevancia (y el semántico).
  - Grupo B (Crecimiento %, Score señales, Valoración, Score Arroba — campos calculados) queda para una 2ª tanda, fuera de este batch.
- **Punto 3 — Buscador predictivo** `GET /api/v1/companies/suggest?q=<texto>&limit=8` (nuevo, `routes/companies.py`, público, registrado en `server.py`): `limit` topado a 20; `q`<2 chars → `{"results": []}` sin tocar BD; normaliza `q` con `_normalize_name` (entity_resolution); tolerancia a tildes con `_diacritic_insensitive_regex` anclado con `^` (prefijo); consulta `companies_master.normalized_name` excluyendo `merge_status=merged`; orden `financials.latest.revenue` desc + `master_company_id`; respuesta `{"results":[{master_company_id,name,name_parts,cif,sector}]}`. `name_parts` = `{before, match, after}` (aditivo, 2026-09-09): resalta el tramo que casó, calculado corriendo el mismo patrón de prefijo tolerante a tildes contra el `legal_name` mostrado (no contra `normalized_name`), para que el rango sea exacto sobre el texto visible. **Formato título (2026-09-09)**: `name` y `name_parts` se devuelven en "tipo título" ("Banco De Depositos") conservando siglas/formas jurídicas en mayúsculas (SA, SL, SLU, acrónimos sin vocales tipo FSM, formas con puntos S.L.); `name_parts` se calcula sobre el nombre ya en título para que `match` case visualmente con el resto.
- **Sin desplegar**: queda en preview hasta que Daniel suba con "Save to GitHub → Deploy".
- Nota de datos del pod: `skills/search` con el default `has_domain=true` da ~0 (solo 2 empresas con dominio); los tests de orden/paginación usan `has_domain=false`.



## 2026-06 (jun) — Aplicado paquete "Intel-290826-deploy-pendiente" (autorizado por Daniel) ✅ (solo PREVIEW)
- Daniel subió el zip `Intel-290826_deploy_pendiente_*.zip`. Al comparar contra el pod, 5 ficheros ya estaban idénticos (search.py, registry.py, ratios_library.py, transaction/engine.py, transaction_intelligence.py). El pod iba POR DELANTE del zip en 3 ficheros, así que se aplicó de forma **quirúrgica** (no sobrescribir) para no regresar código ya presente:
  - **`services/skills_search.py`** — añadido fix de territorio + tildes: `_strip_accents()`/`_diacritic_insensitive_regex()` (regex insensible a tildes á/é/í/ó/ú/ü, ñ intacta), tabla `_CCAA_TO_PROVINCES` (17 CCAA) + `_resolve_territory_provinces()`. `_build_candidate_query()` ahora añade `location.provincia`/`location.municipio`/`province_name` al `$or` léxico y expande CCAA→provincias. **Conservado el bloque REQ-004b id bridge** (mc_→UUID) que el pod ya tenía y el zip no.
  - **`services/taxonomy/classify.py`** — añadido SOLO el índice compuesto `[role:1, taxonomy_id:1, confidence:-1]` en `ensure_indexes()` (Atlas Performance Advisor). Se conservaron los keyword-seeds ampliados y `CLASSIFIER_VERSION v1.3` del pod.
  - **`routes/procurement.py`** — `procurement_overview()` lanza sus ~15 counts/aggregates/distinct con `asyncio.gather()` (mismos resultados, en paralelo) sobre la caché+TTL ya existente.
  - **NO tocados** `routes/engine_schemas.py` (pod tiene campos extra `cif`/`summary`) ni `transaction_os/store.py` (solo diferían en una línea en blanco).
- **Verificación (testing_agent, iteration_16 — 100% backend, 6/6):** búsqueda territorio con `has_domain=false` → 'Malaga' (sin tilde), 'Málaga', 'Andalucía' y 'Castilla la mancha' devuelven resultados (expansión CCAA confirmada: Andalucía casa provincias andaluzas). `/public-procurement/overview` → 200 con 15 claves + 11 en field_coverage; caché 3,91s→0,07s (~55x). Nota: el default `has_domain=true` da ~0 en este pod de preview (solo 2 empresas con dominio) — es el estado de datos del pod, NO un bug. `/public-procurement/status` requiere auth (no se probó sin credenciales; su fix de caché es interno).
- **Sin desplegar**: queda en preview hasta que Daniel suba con "Save to GitHub → Deploy".


## 2026-06 — Credencial R2 rotada + revalidación completa (pre-deploy) ✅ (solo PREVIEW)
- La clave R2 anterior (`…71f9`) quedó revocada en Cloudflare → todas las ops daban `SignatureDoesNotMatch`. Daniel emitió nueva; actualizado `R2_SECRET_ACCESS_KEY` en `backend/.env` (mismo Access Key ID `639f2a2b…` y cuenta `bb3a45…`).
- Revalidado: list/put/head/get/delete R2 OK; `GET /storage-deliveries` → 200 listando la entrega real `Muestra_25000_base.zip` (9,8 MB) que Daniel ya subió.
- **Estado pre-deploy verificado en vivo**: streaming R2 (legacy+moderno), aislamiento del rebuild en subproceso, y pack de 5 fixes (taxonomía/búsqueda/procurement/ratios/deal-aside) → todos aplicados, compilan (16 ficheros), backend+frontend RUNNING, sin errores. Listo para deploy. **Recordatorio**: meter las 4 vars R2 (con el secret NUEVO) en la config de Deploy antes de "Deploy Now".


## 2026-06 — Pack de 5 fixes backend (autorizado por Daniel) ✅ (solo PREVIEW)
- **#1 `taxonomy/registry.py`** (alias "publicidad" en S03): YA aplicado en este pod (marcador presente). Sin cambios.
- **#2 `taxonomy/search.py`** (`_strip_stopwords` + tolerancia a conectores): YA aplicado. Verificado: "agencias marketing"/"agencia de publicidad"/"agencias de publicidad" → S03; "agencias de viajes" → viajes (sin regresión).
- **#3 `routes/procurement.py`** (cache + `estimated_document_count`): YA aplicado (marcador `_total_contracts` presente).
- **#4 `services/engines/financial/ratios_library.py`** (fix signo DPO/Días existencias/CCC): APLICADO AHORA (no estaba — confirmado bug en Servier). Añadida `_mag()` (valor absoluto del coste como denominador); DPO/inventory_days/CCC usan `_mag(supplies)`. Verificado con datos reales de Servier B28184687: DPO=8.1, Días existencias=128.7, CCC=165.0 (positivos, antes -8.1/-128.7/-76.2).
- **#5 endpoint `POST /api/v1/transaction-intelligence/deal-aside`**: APLICADO AHORA (4 ficheros: `store.py` `find_active_transaction_for_target`+`party_role`; `engine.py` `deal_aside_view`; `routes/transaction_intelligence.py` request+endpoint; `engine_schemas.py` `DealAsideResponse`). Verificado: empresa sin tx → `{"active":false}`; con tx de prueba → persona/stage/checklist coherentes (advisor→"asesor", side buy→"comprador"), next_action con título. Anclajes sin drift.
- **Pregunta abierta #5 (forma de `parties`)**: la suposición `{"user_id":..., "role":...}` NO está confirmada en el código — `parties` se pasa verbatim en todos los callers, sin esquema ni test que fije su forma. `party_role()` es best-effort y solo hay que tocar esa función si la forma real difiere.


## 2026-06 — Rebuild pesado de entregas Iberinform AISLADO en subproceso ✅ (solo PREVIEW)
- **Problema**: `_run_delivery`/`_run_delivery_from_r2` corrían el flujo completo (legacy + Sector/Geo + `run_bootstrap_tab`: rebuild_master full + ownership + señales + índice semántico) como `asyncio.create_task` DENTRO del event loop del backend → una reingesta de 25k (~15-20 min) ralentizaba el resto de peticiones a intel.arroba.com.
- **Cambio**: nuevo `scripts/run_delivery_worker.py` (subproceso aislado, mismo enfoque que `scripts/prod_seed_eav`) que ejecuta las 3 fases idénticas y reporta progreso a la MISMA colección `iberinform_delivery_runs` (mismo shape steps/status). `iberinform_admin.py`: `upload-delivery` y `process-from-storage` ahora lanzan el subproceso vía `asyncio.create_subprocess_exec` (`_launch_delivery_worker`, modos `dir`/`r2`) en vez de correr in-process; eliminados `_run_delivery` y `_run_delivery_from_r2`. Mismo polling `GET /upload-delivery/{run_id}` → UI intacta.
- **Verificado E2E**: fixture .zip a R2 → `process-from-storage` → subproceso OS separado (`run_delivery_worker`, confirmado por `ps`), event loop del backend responde en 0,11s mientras corre, progreso (legacy_ingest/legacy_intelligence) reportado por el subproceso vía el mismo polling. Limpieza total tras la prueba. **NO** desplegado.
- **Env vars producción (soporte)**: las 4 claves R2 del `.env` de preview NO se copian solas a producción; hay que añadirlas manualmente en la pantalla de Deploy (env vars) antes de "Deploy Now" (o post-deploy desde Home). Son secretos user-managed, no auto-gestionados como MONGO_URL.


## 2026-06 — Ingesta Iberinform por STREAMING desde Cloudflare R2 (sin disco) ✅ (solo PREVIEW)
- **Problema**: las entregas reales pesan ~9,8 GB (futuras decenas de GB) y no caben por un POST de navegador ni en el disco persistente de 9,8 GB del pod. Emergent no ofrece object storage nativo (confirmado con soporte), así que se usa un bucket propio en Cloudflare R2.
- **Nuevo** `services/data_layer/ingestion/r2_delivery.py`: cliente boto3 para el endpoint S3-compatible de R2 (credenciales por env R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME); `S3RangeReader` (fichero seekable respaldado por HTTP Range GETs, ventana 8 MB → memory-bounded) para que `zipfile` lea el directorio central y cada miembro sin bajar el zip entero; `ZipDelivery` (abre el zip por streaming, resuelve miembros aunque estén anidados, descompresión al vuelo miembro a miembro); `list_zip_deliveries()`.
- **`iberinform_tab_ingest.py`**: abstracción `TabSource` (PathTabSource disco = comportamiento idéntico de siempre / ZipTabSource = miembro-zip por streaming). Las 7 `ingest_*_file()` ahora consumen un `TabSource` (retrocompatibles: aceptan ruta str). Nuevo `ingest_tab_delivery(delivery)` espejo de `ingest_tab_directory` para R2. Sin materializar zip ni .tab descomprimidos en disco.
- **`iberinform_processor.py`** (legacy companies_master + Sector/Geo): `process_real_iberinform_tab_directory(delivery=…)` lee GENERALES/BALANCES por streaming desde R2 cuando recibe `delivery`. **`bootstrap.py`**: `run_bootstrap_tab(delivery=…)` conmuta la ingesta a streaming (todo lo demás, aguas abajo, lee de norm_* — sin cambios).
- **`iberinform_admin.py`**: `GET /storage-deliveries` (lista .zip del bucket) + `POST /process-from-storage?object_key=<key>` (Daniel sube el zip a R2 con rclone/aws-cli y llama con la key). Mismo modelo de progreso en `iberinform_delivery_runs` y mismo polling `GET /upload-delivery/{run_id}` (UI intacta). Corre en background con el mismo flujo de 3 fases que `_run_delivery` (legacy + intelligence + moderno), ambas mitades alimentadas por streaming.
- **FIX preexistente de Fase 0 descubierto y corregido** (`services/data_layer/master/merge.py`): `merge_provenance` no incluía los 5 campos nuevos de Fase 0 en `PROVENANCE_FIELDS` (`domicilio`, `sit_mercantil`, `audited`, `balance_model`, `last_balance_year`), así que `master_builder.py` daba `KeyError` en `canonical(prov["domicilio"])` en cuanto un campo llegaba a None. Nunca había aflorado porque el rebuild de master con estos campos era la tarea pendiente de Fase 0 — habría bloqueado la reingesta real de 25k. Añadidos a `PROVENANCE_FIELDS`.
- **Verificado E2E** (fixture .zip subido a R2, ingerido por streaming, luego borrado + limpieza total): R2 range-read + zipfile OK; legacy (companies_master) y moderno (master_companies) ingeridos por streaming; `norm_financials.ratios` con códigos TRADUCIDOS (SF021/22/23…) y EAV completo; `rebuild_master` completó **24.993** empresas SIN KeyError (fix domicilio validado sobre datos reales + campos `registry.*` proyectados); ficha de la empresa test → periodos medios POSITIVOS (45/60/30 desde -45/-60/-30). Bonus: `RATIO_NAME_TO_CODE` validado contra la muestra real → los 28 nombres únicos del `Datos_RATIOS.tab` real mapean 100%.
- **Efecto colateral (beneficioso)**: la prueba disparó un `rebuild_master(scope=full)` real que reconstruyó los 24.993 master_companies poblando ya los campos `registry.*` de Fase 0 (era una tarea pendiente). No destructivo (upsert, master_ids estables). **NO** desplegado.


## 2026-06 — FIX `RATIO_NAME_TO_CODE` en `iberinform_tab_ingest.py` (previo a re-ingesta 25k) ✅ (solo PREVIEW)
- **Bug silencioso**: la entrega real de 25.000 empresas trae en `Datos_RATIOS.tab` los nombres de ratio en inglés descriptivo ("Interest coverage", "Working capital"…), NO los códigos cortos (SF021, SF022…) que se asumieron del fixture de una sola empresa. Sin traducir, `ingest_ratios_file()` poblaría `norm_financials.ratios` con claves no localizables por la UI de Fase 5 (`iberinform_ratios.py` mapea por código) → rompería en silencio la tarjeta de ratios.
- **Cambio (traslado de fix del checkout local de Daniel, no estaba en /app)**: dict `RATIO_NAME_TO_CODE` (28 entradas nombre EN → código, Tier 1-4) tras `_ACCOUNT_CODES`; en `ingest_ratios_file()`, `canon_code = RATIO_NAME_TO_CODE.get(code, code)` antes de guardar y se usa `canon_code` como clave. Ratios no mapeados se conservan tal cual (regla "guardar todo").
- **Verificado**: `py_compile` OK; los 28 nombres EN traducen a código; nombre no mapeado ("Some Brand New Ratio") se conserva; 26/28 códigos casan con la UI de Fase 5 (SF019/SF024 son Tier 4, excluidos de exposición a propósito pero almacenados). **NO** desplegado. Es el último fix antes de que Daniel lance la re-ingesta real de 25k.


## 2026-06 — FIX Atlas "Query Targeting" en `routes/procurement.py` (cache + estimated_document_count) ✅ (solo PREVIEW)
- **Bug**: alerta real de Atlas (`Arroba-pro`, scanned/returned 7.100,7) por `count_documents({})` sin índice repetido cada 5-10 min en `/status`, `/overview` (pública) y `/validation-report` — cada uno un COLLSCAN completo de 678k+ contratos (`public_procurement_contracts`).
- **Cambio (traslado de un fix hecho en el checkout local de Daniel, no estaba en /app)**: `_total_contracts()` usa `estimated_document_count()` (metadatos, sin escaneo) con fallback a `count_documents({})`; cache en memoria con TTL por ruta (status 60s, overview/validation-report 600s) vía `_cache_get`/`_cache_set`; `_invalidate_procurement_caches()` llamado al final de `/sync` y `/sync-placsp`. Los conteos FILTRADOS internos (matched/pending/agregados) NO se tocan.
- **Verificado**: `py_compile` OK; único `count_documents({})` restante = fallback interno de `_total_contracts()` (más 3 en comentarios); smoke E2E → `/overview`, `/status`, `/validation-report` devuelven total 678.125 y conteos filtrados intactos. **NO** desplegado (Daniel dispara el deploy).
- **FIX taxonomía tolerante a conectores + alias "publicidad" (`search.py`/`registry.py`)**: verificado que YA estaba aplicado en /app (parte del pack Fase 0-6), SIN drift — `_strip_stopwords` + `resolve_label` (literal + sin conectores) y los 3 alias de S03 ("agencias/agencia/empresas de publicidad") coinciden con la versión de Daniel. No requirió cambios.


## 2026-06 — FIX signo periodos medios en `iberinform_ratios.py` (Fase 5) ✅ (solo PREVIEW)
- **Bug**: los ratios de "periodo medio" (días) que dependen de cuentas de coste (aprovisionamientos 40400, guardadas en negativo en BD) salían negativos en el módulo nuevo de Fase 5 `services/engines/financial/iberinform_ratios.py`, que hace passthrough de los 28 ratios oficiales de Iberinform sin normalizar signo. Misma raíz que el fix que Daniel aplicó en `ratios_library.py` (ratios propios de arroba).
- **Cambio**: whitelist `POSITIVE_PERIOD_CODES = {"SF021","SF022","SF023"}` (cobro/pago/aprovisionamiento); `curate()` aplica `abs(val)` SOLO a esos tres. Alcance = opción (a) confirmada por Daniel (SF021 incluido por robustez aunque divida por ingresos). NO se tocan márgenes (REN005/006/007), ROA/ROE (REN001/003), variación de ventas (REN010) ni fondo de maniobra (PRO001) — pueden ser legítimamente negativos.
- **NO** se documenta/expone "proveedores prepagados" en tooltips (instrucción explícita). **NO** se despliega a producción — solo preview.
- **Verificado**: unit `curate()` con negativos → SF021/22/23 = 45/60/30 positivos, resto intacto; smoke E2E ficha real Servier (`mc_36c100bcee4a`, inyección temporal + restauración de BD) → avg_collection=45, avg_payment=60, avg_supply=30, net_margin=-3.2 (correcto). Doc: `memory/PENDING_FIXES/FIX_SIGNO_PERIODOS_MEDIOS_IBERINFORM.md`.
- **Nota datos**: 0 docs con `ratios_source:"iberinform"` en BD todavía → re-ingesta .tab de 25k sigue pendiente; el fix ya está listo para cuando se ingeste.


## 2026-08-14 — REQ-004b: scoping por sector en skills/search (sector + financiero) ✅⚠️
- **Aditivo**: `SearchFilters` +campo `master_company_ids: List[str]`; `_build_candidate_query` restringe con `master_company_id: {$in: ids}` (verbatim del zip). Beta resuelve el sector con `company-taxonomy/search` y pasa esos ids junto a los rangos numéricos → intersección ids ∩ numérico.
- **⚠️ PUENTE DE IDS añadido (desviación necesaria del zip)**: los `company_ids` de taxonomía son `master_id` canónico (`mc_...`), pero `skills/search` lee la colección legacy `companies_master` cuyo `master_company_id` es un **UUID distinto**. Aplicar el zip tal cual daría SIEMPRE 0 resultados. En `search_companies` traduzco `mc_* → cif_normalized (master_companies) → master_company_id UUID (companies_master)` antes de construir la query; ids que no resuelven → centinela `__no_match__` (devuelve 0, nunca todo el universo). Acepta también ids legacy UUID directos.
- **Validado (preview, curl)**: `pytest` 9/9; scope-only 60 ids taxonomía → 60; "agencias de marketing" ∩ revenue≥1M → 14 (WARNER CHAPPELL 20M…); **ejemplo exacto del REQ** "agencias de marketing + EBITDA>1M + <100 empleados" → 7 (WARNER CHAPPELL 5.4M/18emp, PACICON 1.16M/29…); id inexistente → 0.
- **Archivos**: `routes/skills.py` (+campo), `services/skills_search.py` (`_build_candidate_query` +scope, `search_companies` +puente de ids). Solo código → requiere REDEPLOY (sin migración de datos).


## 2026-08-14 — Backfill EBITDA + histórico a companies_master (activa ebitda del REQ-004) ✅⚠️
- Script NUEVO `scripts/backfill_financials_to_companies_master.py` (aditivo, idempotente): `$set financials` en `companies_master` copiando de la canónica `master_companies` por `cif_normalized`. No borra `revenue_latest`/`employees_latest` ni nada.
- **Ejecutado en PREVIEW y en PROD Atlas** (dry-run→apply): `companies_master.financials.latest.ebitda` 0 → **9.742**, `financials.history` 0 → **13.464**, `revenue_latest` intacto (24.992). Índices creados en ambos: `financials.latest.{revenue,ebitda,employees}`.
- **Verificado (preview)**: `skills/search` con `ebitda_min>1M` → **total 237**, `summary.ebitda`/`ebitda_margin` ya NO salen null. ✅
- **⚠️ TECHO DE DATO — `growth_min` sigue ~vacío**: el histórico ingerido es de **un solo año** para casi todas (dist. master_companies: 11.528 con 0 años, 13.462 con 1 año, **solo 2 con ≥2 años**), tanto en preview como en prod. `growth` necesita ≥2 años → devuelve ~0. **No es bug**: para activarlo hace falta ingerir histórico multi-año.
- **⚠️ CALIDAD DE DATO**: algunos `ebitda` de la canónica son implausibles (ebitda>revenue → margin>100%, p.ej. CONSILIUM 1.18). Se copia tal cual; problema preexistente de parsing financiero, no del backfill.
- **Idempotencia**: total para los 9.742 con ebitda (se saltan en re-run); los 3.722 con solo-history se re-escriben idénticos (inofensivo).
- **Estado filtros REQ-004 tras redeploy**: revenue/employees/province/**ebitda** funcionales; growth limitado por el techo de dato.


## 2026-08-14 — REQ-004: filtro financiero en skills/search (screener numérico) ✅⚠️
- **Aplicado por DIFF, aditivo** (nada borrado). `POST /api/v1/skills/search` amplía `SearchFilters` con campos opcionales `revenue_min/max`, `ebitda_min/max`, `employees_min/max`, `growth_min` (fracción), `province` (no toca cnae/category/tags/has_domain).
- `services/skills_search.py`: `_num_clauses` empuja los predicados a Mongo (`$or` sobre `financials.latest.*` y shape legacy `*_latest`); `_build_candidate_query` combina numérico + léxico bajo `$and` (screen puro → sin `$or` léxico ni `domain`, orden por revenue desc, `SCREEN_CAP=2000`); `_passes_filters` añade guardas numéricos (métrica desconocida NO pasa); `growth` se calcula de `financials.history` si falta; cada fila emite `summary` (revenue, ebitda, ebitda_margin, growth_pct, employees, year, signal_score, signal_badge, city) y el bloque emite `total/page/page_size`. `signal_badge` snake_case ES (`alto_crecimiento`/`riesgo`).
- **Tests**: `tests/test_skills_search_financial_filter.py` → **9/9 verdes** (incluye "8 k€ NO pasa >50M"). Integración (preview): screen revenue≥50M → 25 resultados, todos ≥50M, contrato Beta `{master_company_id,name,sector,cif,score,summary}` + total/page/page_size; léxico "holding" preservado (+summary); combinado "holding"+rev≥100M → solo ADEO/SANTUSA.
- **⚠️ LÍMITE DE DATOS (no es bug de código)**: `skills/search` consulta la colección LEGACY `companies_master`, que es plana: **24.992 con `revenue_latest`/`employees_latest`, pero 0 con `ebitda` y 0 con `financials.history`**. Por tanto **`revenue_min/max`, `employees_min/max`, `province` FUNCIONAN**, pero **`ebitda_*` y `growth_min` devuelven vacío** (y `summary.ebitda/margin/growth_pct/signal_badge` salen null) hasta que: (a) se backfillee ebitda/history en `companies_master`, o (b) `skills/search` lea de la canónica `master_companies` (9.742 con ebitda, 13.464 con history) — cambio mayor, fuera del alcance de REQ-004. El código ya soporta ambos shapes vía `$or`+accessors: en cuanto el dato exista, filtra solo.
- **Archivos**: `services/skills_search.py`, `routes/skills.py` (+campos), `tests/test_skills_search_financial_filter.py`.


## 2026-08-14 — F5 Taxonomía: search "todas por sector" enriquecido con summary + resolve_label mejorado ✅
- **`GET /api/v1/company-taxonomy/search`** ahora devuelve **filas enriquecidas con `summary`** (mismos campos que /search: revenue, ebitda, margin, growth, signal_score/badge, valuation, arroba_score, employees, city, activity_label, updated_at) + **`count` total real** + **`limit`/`offset` (paginación de servidor)** + `resolved` (nodo/dimensión que casó). Mantiene `company_ids` por compatibilidad. `search_by_taxonomy` construye las filas con 1 query de básicos + `build_summaries` (2 queries) → **sin N+1** (independiente del nº de filas).
- **Nuevo `POST /api/v1/company-taxonomy/summary`** {master_ids:[...]} → fichas-resumen en lote (para pintar cualquier tabla sin N+1).
- **`resolve_label` — cobertura mejorada** con aliases curados por nodo (`registry.NODE_ALIASES`) + override determinista (frase con límite de palabra, más largo primero) que se comprueba ANTES del difuso. Corrige: "agencias de marketing" → **S03** (antes caía en la categoría genérica "Agencias"); bonus: "agencias de viajes" → Viajes y turismo, "laboratorio farmacéutico" → Industria farmacéutica (eje correcto). Tolera relleno ("busca … en madrid"). Aliases también expuestos en los nodos (`build_nodes` → `aliases`).
- **Validado (preview, curl)**: `?q=agencias de marketing` → resolved S03, count **2302**, filas con summary, `offset` server-side OK; cobertura de las 5 expresiones: marketing(S03,2302)·dental(233)·fiscal(147)·transporte(S10,2403)·hoteles(905), todas con `summary`. `POST /summary` OK (SERVIER arroba 81).
- **Archivos**: `services/taxonomy/registry.py` (NODE_ALIASES + build_nodes), `services/taxonomy/search.py` (override + search_by_taxonomy enriquecido + offset), `routes/company_taxonomy.py` (offset, resolved, POST /summary).
- **PROD**: lee de `company_classifications` (225k en prod) + `master_companies` + `signals` → funciona tras redeploy, sin migración de datos.


## 2026-08-14 — Cachés de búsqueda semántica (query-embedding LRU + resultados TTL) ✅
- `services/engines/semantic/cache.py`: `_LRU` genérico (thread-safe). `query_embedding_cache` (LRU 4096, sin TTL) evita re-llamar a OpenAI en consultas repetidas; `result_cache` (LRU 2048, TTL 60s) sirve respuestas populares al instante.
- `engine.search` usa el caché de query-embeddings; la ruta `/search` usa el caché de resultados (guarda la respuesta YA enriquecida con `summary`). Respuesta añade flag `cached`.
- Medido en preview: 1ª (cold) 1.73s → 2ª idéntica **4.5ms** (result-cache) → misma query distinto `limit` **11ms** (embedding-cache, sin llamada OpenAI). Cubre ítems 4 y 5 del REQ de arquitectura de búsqueda.


## 2026-08-14 — Buscador semántico → Atlas Vector Search ($vectorSearch/HNSW) con fallback in-memory ✅
- **Problema**: en prod la búsqueda tardaba >2 min porque el código desplegado cargaba todo el universo de embeddings y calculaba coseno en Python por request (+OOM del worker).
- **Tier/soporte**: cluster prod = MongoDB **8.0.29**, `getSearchIndexes()` responde (Atlas Search/Vector Search **disponible**); `hostInfo` restringido → tier compartido, pero soporta Vector Search igualmente.
- **Índice creado en PROD Atlas**: `semantic_vec` (tipo `vectorSearch`, `path=embedding.vector`, `numDimensions=512`, `similarity=cosine`, `filter=cnae_section`). Estado READY/queryable. Creado con el usuario de app (`createSearchIndex` permitido).
- **Backend nuevo (auto-detección)**: `vector_search.py` reescrito — usa **Atlas `$vectorSearch`** (coseno dentro de Atlas, `numCandidates` ~20×limit, filtro `cnae_section`, exclusión de self por over-fetch) cuando está disponible; **cae a la matriz numpy en memoria** (memory-safe) donde no lo está (Mongo local de preview). `warm()` prueba Atlas al arrancar y, si responde, **NO carga el índice en memoria** (evita el OOM en prod). `current_backend()` reporta `atlas-vectorsearch-v1` / `inmemory-cosine-v2`.
- **Mismo contrato** `/search` y `/similar` (shape idéntico). Nota: el score de Atlas para coseno es `(1+cos)/2 ∈ [0,1]`, el in-memory es coseno crudo — el ranking es idéntico.
- **Latencia medida contra prod** (pool caliente): `$vectorSearch` **p50 ~118ms** (p95 ~121ms); embedding OpenAI ~356ms → **~474ms por búsqueda end-to-end** (vs >2 min). Validado por el propio código: search, similar (self excluido), filtro de sección J → todo correcto.
- **Preview** (Mongo local, sin $vectorSearch): usa fallback in-memory (warm log: `inmemory-cosine-v2, 25868 vectors`), "agencias de viajes" → agencias reales. ✅
- **Archivos**: `services/engines/semantic/vector_search.py` (reescrito: dispatcher Atlas+in-memory, `warm`, `current_backend`), `engine.py` (`VS.current_backend()`), `routes/semantic_intelligence.py` (catalog backend), `server.py` (warm probe).
- **ACCIÓN REQUERIDA → REDEPLOY de prod** para activar el path Atlas. El índice `semantic_vec` YA existe en el Atlas de prod, así que tras el redeploy el backend lo autodetecta y lo usa (sin OOM, sin carga en memoria). No hay que recrear índice ni re-embeddear.


## 2026-08-14 — Re-embed semántico de PROD + fix de memoria del índice (evita OOM) ✅⚠️
- **Re-embed PROD ejecutado** (autorizado): `scripts/reembed_semantic_openai.py --force` contra el Atlas de producción (`MONGO_URL`/`DB_NAME` de prod inline, `OPENAI_API_KEY` del `.env`; NO se tocó el `.env` de preview). Resultado: **25.868/25.868 fichas en `text-embedding-3-small`, 0 legacy** (antes solo 3 pilotos openai → por eso prod devolvía siempre IUSTIME/COPISA/SERVIER). 282s.
- **Búsqueda verificada (preview, mismos datos que prod)**: "agencias de viajes" → VIAJES MARKETING, JULIATOURS, GIRATUR, VILLAR Y LORO (agencias reales, sección N/M). Relevancia correcta.
- **⚠️ INCIDENCIA PROD (breve, auto-recuperada)**: al lanzar la búsqueda de verificación contra prod, el worker devolvió **520 en todos los endpoints** ~15s y se reinició solo. Causa: el código DESPLEGADO en prod construía el índice en memoria materializando TODO el universo como lista Python (pico ~350-400MB) → **OOM del worker** al cargar 25.868 vectores.
- **FIX de memoria (en preview, pendiente de redeploy)**: `vector_search._ensure_index` ahora **preasigna UNA matriz `float32` [N,D] (53MB) y la llena fila a fila desde un cursor en streaming** (`persistence.iter_embeddings`/`count_embeddings`) → **RSS pico del proceso 221MB** (medido contra Atlas prod). Además **warm-up en background al arrancar** (`server.py` → `vector_search.reload()`) para no pagar carga en frío en la primera `/search`.
- **Archivos**: `services/engines/semantic/vector_search.py` (cargador seguro + warm), `persistence.py` (`iter_embeddings`, `count_embeddings`), `server.py` (warm-up en `_run_startup_init`).
- **ACCIÓN REQUERIDA**: **REDEPLOY de prod** para aplicar el fix de memoria. Hasta entonces, NO ejecutar búsquedas semánticas en prod (cada una provoca un blip de ~15s auto-recuperado). Tras el redeploy, prod servirá las agencias reales sin caerse. Los DATOS de prod ya están correctos (no requieren re-embed de nuevo).


## 2026-08-14 — `summary` enriquecido en cada SearchHit de search + resolve (tabla sin N+1) ✅
- **Motivo (arroba.com página de resultados)**: pintar la tabla con una sola llamada. `search` y `resolve` ahora devuelven, por hit, un objeto `summary` con: `revenue`, `ebitda`, `ebitda_margin`, `growth_pct` (YoY), `signal_score` (0-100), `signal_badge` (enum), `valuation` {low,mid,high,currency,basis}, `employees`, `arroba_score` (0-100 explicable), `city`, `activity_label`, `updated_at` (+ `arroba_score_detail` con componentes, `market_position_pct`).
- **Sin N+1**: nuevo `services/company_card.py::build_summaries(master_ids)` usa **2 queries en lote** (`master_companies $in` + `signals $in activas`) + **1 carga de revenues por sección CNAE distinta** (cacheada 600s) → todo lo demás en memoria. Reutiliza `SE._score` (score-v1 desde `signals.dimensions`), `FE.financial_quality` (puro) y los múltiplos de `skills_valuation`.
- **signal_badge** (precedencia M&A): `riesgo` (financial.net_loss/negative_equity/quality_low | risk.*) > `buscando_financiacion` (capital.*) > `comprando` (ownership.consolidator) > `alto_crecimiento` (growth.* | market.outperforms_peers | financial.margin_strong) > `estable`. `null` si la empresa no tiene señales.
- **valuation**: rango por múltiplos de sección — `EV = EBITDA × EV/EBITDA` (si EBITDA>0), si no `EV = revenue × EV/Revenue`; `{low, mid, high, currency:"EUR", basis}`.
- **arroba_score** (0-100, determinista, explicable): media ponderada re-normalizada sobre componentes disponibles — financial_quality 40% · growth 20% · market_position (percentil sectorial) 20% · signals 20%. Guarda `components` + `confidence` (suma de pesos disponibles) + `partial`. Si faltan cuentas, calcula con lo que haya y baja confianza; si no hay nada fiable → `null` (la tabla pinta "—").
- **Archivos**: `services/company_card.py` (nuevo); `routes/semantic_intelligence.py` (search enriquece), `routes/company_intelligence.py` (resolve enriquece + `CompanyResolveMatch.summary`), `routes/engine_schemas.py` (`SearchHit.summary`).
- **Validado (preview, curl local + URL externa)**: SERVIER resolve → revenue 164M, ebitda 18.5M, margin 11.3%, growth +11.7%, signal 62/**comprando**, valuation ev_ebitda 111–166M, arroba **81** (conf 1.0); empresas sin cuentas → nulls honestos + arroba parcial (conf 0.2-0.8); `basis` conmuta ev_ebitda/ev_revenue. Los 12 campos presentes.
- **PROD**: lee de `master_companies` + `signals` (ya poblados en prod) → **funciona nada más redeployar el código, sin migración de datos** (a diferencia del re-embed semántico).


## 2026-08-14 — Semantic search: buscador global NL con embeddings reales + `cif` en resultados ✅
- **Motivo (Beta/arroba.com)**: `semantic-intelligence/search` daba resultados poco fiables (backend `hashing-tf-v1` → "laboratorio farmacéutico" traía empresas de educación) y no devolvía `cif`, imposibilitando abrir la ficha (que navega por CIF).
- **Causa doble detectada**: (1) embedding sin semántica (bolsa de palabras por hashing); (2) **bug de pool**: en búsqueda global (sin `cnae_section`) `top_k` solo puntuaba un slice ARBITRARIO de 500 fichas (`find().limit(500)` sin orden), no las 25.868.
- **Solución (Opción A1)**: proveedor de embeddings **OpenAI `text-embedding-3-small` (512-d, L2-normalizado)** vía `OPENAI_API_KEY` (clave del usuario en `backend/.env`; la clave Emergent NO soporta embeddings). Fallback automático a local `hashing-tf-v1` si no hay key.
  - `services/engines/semantic/embeddings.py`: nuevo `OpenAIEmbeddingProvider` (+`embed_many`) y selección de proveedor por env.
  - `services/engines/semantic/vector_search.py`: reescrito a **`inmemory-cosine-v2`** — carga TODOS los vectores del modelo activo en una matriz numpy cacheada (TTL 300s) y escanea el universo completo; filtra por `embedding.model` activo → degradación segura a vacío si el modelo cambia y aún no se re-embeddeó.
  - `persistence.all_embeddings(model)`: streamer de todo el universo por modelo.
  - `engine.search`/`build_profile`: embedding de query/doc vía `asyncio.to_thread` (no bloquea el loop).
  - `SearchHit`: **añadido `cif`** (schema + runtime; las rutas usan `responses=` doc-only → nada se recorta).
  - `scripts/reembed_semantic_openai.py`: job batch idempotente (BATCH=128, reintentos con backoff, `--force`).
- **Re-embed en PREVIEW**: 25.868 fichas re-embeddadas en 117s (~220/s). Coste medido ~2,06M tokens ≈ $0,04.
- **Validación (preview, curl)**: relevancia correcta en NL — "laboratorio farmacéutico"→farma (Servier, Antibióticos Alcalá), "construcción de carreteras"→sección F (COPISA), "asesoría fiscal"→M, "clínica dental"→Q, "transporte y logística"→H; `/similar` de Servier→otras farma (0.85); `cif` presente en todos; `/catalog` refleja `openai / text-embedding-3-small / inmemory-cosine-v2`.
- **⚠️ ACCIÓN REQUERIDA EN PROD tras redeploy**: los 25.868 `semantic_profiles` de prod siguen con vectores `hashing-tf-v1`; hasta correr `python scripts/reembed_semantic_openai.py` contra el Atlas de prod (con `OPENAI_API_KEY` en secretos), **la búsqueda en prod devolverá vacío** (degradación segura por filtro de modelo). El re-embed de prod es una operación de datos independiente del deploy de código.


## 2026-08-10 (incidente prod) — 520 por OOM del pod + master_id divergente
- **520 en prod durante el seed**: el paso `balances` de `prod_seed_eav` carga 555k filas en memoria → satura el pod pequeño de prod → Cloudflare 520 (~45s) → el pod reinicia → mata el subproceso a mitad (run3 quedó congelado en step=balances). Los balances YA estaban sembrados de runs previos (cashflow=246), así que re-ejecutarlos era innecesario y peligroso.
- **FIX**: (1) endpoint `/reingest-eav` acepta `balances: bool = Query(True)` → `balances=false` salta el paso pesado. (2) `_backfill_ratios` reescrito a STREAMING (un doc + buffer de 500 ops, sin cargar todos los accounts en memoria) → seguro en pods pequeños. Verificado en preview con `balances=false`: **1.3s**, seen=13.481, ratios_backfilled=13.452, master_current_ratio=13.044.
- **master_id divergente (incidente reportado por PM)**: intel.arroba.com devuelve `mc_36c100bcee4a` para Servier de forma CONSISTENTE (8/8 llamadas) = una sola instancia/Atlas. PREVIEW también da `mc_36c100bcee4a` → master_id es DETERMINISTA. Beta ve `mc_908b00949ee2` → **Beta NO consume intel.arroba.com**; lee de un Intel/Atlas DISTINTO y más ANTIGUO (resolver anterior). Canónico = intel.arroba.com (master_total=24.992, service key sha256[:8]=2ba91e0d válida). Acción de consolidación (ops/Beta): apuntar `AGENCY_TOOL_BASE_URL` de Beta a https://intel.arroba.com. NO borrar nada aún.
- PENDIENTE: 1 redeploy más (fix balances=false) → luego `POST /reingest-eav?ownership=false&listed=true&balances=false` en prod (ligero, sin OOM) → percentiles poblados.


## 2026-08-10 (fix seed) — Backfill ligero de ratios (rebuild_master era inviable en Atlas)
- Diagnóstico: `rebuild_master` (full o con cif_list de 13k) NO escribe ni un lote en la Atlas de prod (0 flushes en >8 min) — reescribe el doc entero de 25k empresas con 13 índices. Los VALORES por-empresa ya salían (analyze lee norm directo: NCR cash_flow ok, current_ratio 2.07), pero los PERCENTILES quedaban null (`with_balance_liquidity`=0).
- **FIX en `scripts/prod_seed_eav.py`**: sustituido `rebuild_master` por `_backfill_ratios` — un solo cursor sobre `norm_financials` (con balance) + `bulk_write` de `$set financials.latest.ratios` (campo NO indexado) en lotes de 1000. Verificado en preview: **3.9s**, `ratios_backfilled=13.447`, `master_current_ratio=13.044`, NCR percentil=50.
- **Invalidación de caché**: `analyze_cache` usa `data_version = updated_at|signals_updated_at|last_enriched_at`. El backfill ahora bumpea `updated_at` en cada empresa → cache_key cambia → analyze recomputa fresco (resuelve el riesgo de servir respuestas cacheadas viejas tras el seed).
- El endpoint `/reingest-eav` y su subproceso aislado siguen igual. PENDIENTE: **1 redeploy más** para llevar este fix a prod; luego re-ejecutar el seed (los subprocesos lentos antiguos mueren al reiniciar el backend en el deploy).
- VERIFICADO en prod (antes del fix): master_total=24.992, NCR B28031458 resolved=true (financials+cash_flow+governance+signals), cashflow_years=246, is_listed=1 → prod apunta al Atlas correcto con las 25k; NO hace falta ingesta completa.


## 2026-08-10 (deploy) — Siembra de PRODUCCIÓN ejecutada
- Deploy a `intel.arroba.com` confirmado (código nuevo: `/coverage/check` da JSON). Lanzado `POST /api/v1/admin/iberinform/reingest-eav` en prod.
- **Core sembrado y VERIFICADO en prod**: balances EAV (cashflow_years 5→246), is_listed (0→1), y por-empresa: NCR B28031458 cash_flow presente + current_ratio 2.07; PROCOLUIDE A81921611 st_debt=1.395.128,55/lt=2.905.096,59/fin=4.300.225,14 + current_ratio 1,76; A28354132 is_listed=true (BME). **Señal de éxito del usuario CUMPLIDA.**
- ⚠️ **`rebuild_master` (percentiles sectoriales) se arrastró en Atlas**: pasé `cif_list` de 13.451 CIFs → `$in` gigante patológicamente lento en Atlas (0 lotes escritos en ~9 min; en local fue 8s). `with_balance_liquidity` quedó en 0. La API en vivo de prod se mantuvo sana (subproceso aislado OK).
- **FIX** en `scripts/prod_seed_eav.py`: rebuild ahora `scope="full"` (escaneo secuencial, sin `$in` gigante) + `create_index` en cif_normalized/src_cif/name_key. Verificado en preview: seed completo en **10.5s**, rebuild 24.992, current_ratio 13.044. **PENDIENTE: redeploy + re-ejecutar el seed en prod** (el redeploy reinicia el backend y mata el subproceso lento antiguo).


## 2026-08-10 (P0) — Desajuste de ENTORNO: preview(local) ≠ producción(Atlas)
- **Diagnóstico**: preview usa MongoDB LOCAL (`localhost:27017`, `arroba_agency_tool`); producción (`intel.arroba.com`) es despliegue separado con código antiguo + otra base (Atlas). Beta consume producción → no ve nada del trabajo de datos hecho en preview. Prueba: rankings coinciden (misma base de empresas/revenue) pero cash_flow/current_ratio/st_debt/is_listed = null (falta re-ingesta EAV) y `/coverage/check` devuelve HTML del SPA (código no desplegado).
- **NUEVO endpoint de siembra idempotente**: `POST /api/v1/admin/iberinform/reingest-eav` (+ `GET .../reingest-eav/{run_id}`) en `routes/iberinform_admin.py`. Corre en **SUBPROCESO AISLADO** (`scripts/prod_seed_eav.py`) → NO bloquea el event loop (verificado: health ~3ms durante ejecución; ~8s en preview). Re-ingiere balances EAV completo + ownership + marca is_listed(BME) + rebuild master de las empresas con balance. Úsalo UNA vez tras el redeploy para sembrar la base de producción.
  - IMPORTANTE: la 1ª versión usaba `asyncio.create_task` in-process y tumbó el backend (rebuild de 13k bloquea el loop). Corregido a subproceso aislado.
- Ruta de datos: `SAMPLE_DIR = /app/data/muestra_25000` (los 10 `.tab` están versionados en git → viajan al deploy).
- Handoff de resolución para Beta/PM: `/app/frontend/public/PARA_BETA_ENTORNO_RESOLUCION.md`.
- Login admin: la respuesta de `/api/v1/auth/login` usa la clave **`token`** (no `access_token`).


## 2026-08-10 (cont.) — Estabilidad enriquecimiento + is_listed + ownership idempotente
- **Estabilidad (a)**: causa raíz de la caída de la API = `uvicorn --reload` vigila `/app/backend` (incluido `scripts/`); ejecutar scripts ahí disparaba un reload que se colgaba en el scraper síncrono de CNMV del arranque. Solución: runners AISLADOS en `/app/tools_runtime/` (fuera del árbol vigilado) con `PYTHONDONTWRITEBYTECODE=1` + throttling (concurrencia 4, lotes con pausas). Verificado: API en 200 (3ms) mientras corre el enriquecimiento.
- **Enriquecimiento web PARADO por decisión del usuario**: rendimiento marginal (ok≈0,2% sobre URLs adivinadas por url_discovery; las descripciones reales ~2.942 vienen de las URLs de Iberinform). Sin LLM.
- **(b) multi-ejercicio EAV: BLOQUEADO POR DATOS** — `Datos_BALANCES.tab` tiene 1 año/empresa (snapshot, no histórico). El usuario no tiene el histórico por ahora. `evolution`/CAGR quedan pendientes de datos.
- **(c) ownership: DATA-LIMITED** — `Datos_ACCIONISTAS.tab` = 628 filas/318 empresas (ya todo ingerido, idempotente re-verificado). Se expandirá al subir una entrega completa por `POST /api/v1/admin/iberinform/upload-delivery` (zip con todos los .tab).
- **(d) is_listed: cableado** desde `bme_companies` (`tools_runtime/mark_listed_from_bme.py`), expuesto en `/api/v2/company-intelligence/identity` (`is_listed`/`listed_market`) y contado en `/api/v1/company/coverage.listed_companies`. Solape actual: 1 (A28354132 INNOVATIVE SOLUTIONS ECOSYSTEM, con financials → CIF demo de cotizada para Beta).
- Runners nuevos (aislados): `tools_runtime/web_enrich_throttled.py`, `tools_runtime/mark_listed_from_bme.py`, `tools_runtime/reingest_ownership.py`.


## 2026-08-10 — B5 EAV completo re-ingerido + armonización contrato B-2 (Beta Fase 0) ✅
- **Causa raíz B5 encontrada y resuelta**: la ingesta 2026-07-22 corrió con una versión antigua de `ingest_balances_file` (filtro `_ACCOUNT_CODES`, código muerto ahora) que solo guardaba ~6 códigos canónicos por empresa-año. El código EAV completo ya existía pero **nunca se re-ejecutó**. Re-ejecutada sobre las ~25k en Atlas (555.550 filas, ~3s balances + ~10s rebuild master). Validado primero sobre muestra de 500.
  - `norm_financials` con `current_assets`(12000): 8 → **13.430**; `current_liabilities`(32000): 8 → **13.123**; cash-flow OCF(61500): 5 → **246**.
  - `master.financials.latest.ratios.current_ratio`: 0 → **13.044**. Ratios de liquidez/working-capital + percentil sectorial y desglose de deuda (st/lt/financial_debt) ahora activos en el contrato. Cash flow (EFE) solo en cuentas normales (246); PYMEs abreviadas → `cash_flow:null`+nota (honesto).
- **Armonización de contrato para Beta**:
  - `routes/company_intelligence.py`: añadido `objeto_social` (alias de `corporate_purpose`) a la respuesta de `POST /api/v2/company-intelligence/identity` + a `data_coverage`.
  - Confirmado (sin cambios): `benchmark`/`methodology`/`scenarios` ya salen en `POST /api/v1/financial-intelligence/valuation`; señales canónicas = `GET /api/v1/company/{id}/signals`.
- **NUEVO endpoint de cobertura** (`routes/company_ficha.py`, X-API-Key): `GET /api/v1/company/coverage` (agregado) + `POST /api/v1/company/coverage/check` (pre-flight por lote hasta 100 CIFs). Permite a Beta pre-filtrar CIFs y evitar 404s.
- **Diagnóstico 404 de Beta**: los 4 CIFs (Iberdrola A28017895, Planeta A08363419, Technip B65076193, micro B95758389) **NO están en el master** (gap de cobertura de la muestra 25k; no incluye cotizadas). NO es bug de lookup ni de variante de CIF. La ficha es multi-empresa (funciona para las 24.992). `is_listed` no poblado en ningún registro (sin fuente de cotizadas en la entrega).
- **5 CIFs demo entregados** a Beta (ver test_credentials.md). Handoff publicado en `/app/frontend/public/PARA_BETA_B2_FASE0_RESPUESTA.md` (accesible en `{preview}/PARA_BETA_B2_FASE0_RESPUESTA.md`).
- **Web enrichment** (`description` ~4%): batch corrido (+335 descripciones, +19 tech tags); url_discovery encontró ~3.900 URLs. **PAUSADO**: los jobs en background saturaban el pool de Atlas y tumbaban la API en vivo (health timeout). Retomar de forma controlada bajo demanda.
- Scripts nuevos: `scripts/reingest_balances_sample.py`, `scripts/reingest_balances_full.py`, `scripts/beta_diagnostic.py`.


## 2026-07-23 — v16 desplegada y verificada en Emergent Preview ✅
- `arroba_agency_tool_v16.zip` (v13 fix ciclo de vida de señales + v14 fix category/severity y pestaña Señales + v15 auditoría de fuentes/DIRCE/stats + documentación de esta capa) subida y desplegada por Neo sobre "preview-arroba-app".
- **Testing agent**: backend 19/20 (el único punto es un bug de aserción del propio test — busca `real_companies` en la raíz cuando la respuesta lo anida bajo `iberinform`; el dato servido es correcto: `real=24992, synthetic=0`), frontend 100%, 0 errores de consola en las 5 pantallas nuevas/tocadas (Oportunidades, Señales, DIRCE, y regresión de Watchlist/Fragmentación/Roll-up/Control-Synergy).
- **Pasos post-deploy ejecutados** (por orden, ninguno requirió código nuevo): `POST /api/v1/signal-intelligence/migrate-dedupe` (9 grupos de duplicados fusionados, 9 documentos borrados — limpia el residuo del bug de identidad de señales de v13); `GET /api/v1/signal-intelligence/stats/view` confirmado (`total_signals=66050`, `total_opportunities=160`: 159 `ownership.consolidator` + 1 `opportunity.succession_signal`); scheduler de PLACSP confirmado arrancando en logs junto a BORME/DataComex/Watchlist/CNMV-BME.
- **Regresión verificada**: fragmentation, ratios/catalog, rollup-thesis, watchlist, control-synergy, iberinform/stats, data-providers/health, auth negativa (X-API-Key y JWT) → todo correcto. `companies_master`/`master_companies`/`iberinform_companies` = 24.992 en los tres.
- **Nota operativa de Neo** (no bloqueante): mover los ficheros de test de integración fuera de `/app/backend/` (o usar `--reload-exclude tests/`) — uvicorn `--reload` vigila ese árbol y recarga al crearlos ahí.
- **Pendiente** (sin código nuevo): sincronizar DIRCE/INE para poblar la pantalla de Demografía Empresarial (renderiza correctamente, en estado vacío hasta ese sync).
- Detalle completo: `STRATEGIC_INTELLIGENCE_LAYER_REPORT.md` §18.

## 2026-07-23 — Documentación formal de la Capa de Inteligencia Estratégica + Definición del Copilot ✅ SOLO DOCUMENTACIÓN
- **Nuevo documento** `memory/STRATEGIC_INTELLIGENCE_LAYER_REPORT.md`: cierra un hueco de documentación — Q1–Q7 (quick wins), E1/E2/E6/E7 (evoluciones) y T3 + Control & Synergy Score (transformacional), construidos en sesiones previas sobre el esquema moderno (`master_companies`/`master_id`), no estaban documentados en `memory/` del propio repo (solo en memoria de sesión). Cubre también la ingesta real de las 25.000 empresas Iberinform (doble esquema, fix del resolver de identidad), la auditoría completa de fuentes de datos (CNMV/BME/PLACSP/DataComex/Banco de España/scheduler/DIRCE) y el fix de fondo del ciclo de vida de señales (identidad ya no depende de `source_version`).
- **Nuevo documento** `memory/ARROBA_COPILOT_DEFINITION_v1.md`: define qué es el Arroba Copilot (se construye en arroba.com, per `ARROBA_INTEGRATION_PACK_v1.md` §1.6), qué capacidades ya cubre la plataforma (analizar/valorar/proponer/ejecutar, vía los motores existentes), el gap real de "predecir" (requiere un motor nuevo `forecast-intelligence-v1`, no construido), el split de memoria/aprendizaje entre arroba.com y Agency Tool (`recommendation_memory`/`recommendation_feedback`/`strategic_theses.lifecycle` ya existen como semilla), y una propuesta de endpoint agregador "Copilot Context" (no implementada).
- **Actualización aditiva de contratos existentes** (sin romper compatibilidad — adiciones D10): `SIGNAL_INTELLIGENCE_ENGINE_CONTRACT.md` (§6.1 nueva: `/signals`, `/signals/view`, `/stats`, `/stats/view`, `/signal/{id}/view`, `/history/view`, `/migrate-dedupe`; corrección de la fórmula de `signal_id` — ya no incluye `source_version`) e `INTELLIGENCE_API_REFERENCE.md` (§2 Signal Intelligence actualizada con los mismos endpoints).
- **`PRD.md`**: nueva entrada "Sprint 9" en `## Latest changes (Julio 2026)` resumiendo todo lo anterior, con estado explícito: verificado (mongomock + `py_compile` + esbuild), **pendiente de empaquetar y desplegar** por instrucción de Daniel de acumular trabajo verificado y desplegar en un único paso cuando él lo indique.
- Sin cambios de código ni de comportamiento en este commit — solo documentación de trabajo ya implementado y verificado en sesiones anteriores.

## 2026-07-12 — Smoke Test Público Oficial de Integración (artefacto permanente) ✅
- Creado `memory/SMOKE_TEST_PUBLIC_PRODUCTION.md` (documento de gobierno) + `backend/tools/smoke_test_public.py` (script ejecutable, exit 0=PASS/1=FAIL, apto para gate de CI/despliegue).
- Verifica en <2 min el flujo canónico Arroba (resolve→identity→analyze) sobre CIF `A87803862`, solo con Base URL pública + X-API-Key: HTTP 200, identidad, financials L2, histórico real, data_source, explainability, master_id y compatibilidad `arroba.v2`.
- **Regla:** antes de cada despliegue de Arroba o del Intelligence Engine debe ejecutarse; FAIL = regresión de integración → no se despliega.
- **Ejecución 2026-07-12 contra producción: PASS (18/18).** F0.2 desbloqueado; contrato congelado durante F0.2.


## 2026-07-12 — Desbloqueo integración Arroba F0.2 · Resolución pública + caso canónico ✅
- **Identificador oficial = CIF** (contratos agnósticos: aceptan CIF o master_id en `identifier`). Documentado en `ARROBA_V2_INTEGRATION_GUIDE.md`.
- **Endpoint público de resolución** `POST /api/v2/company-intelligence/resolve` (solo X-API-Key): CIF→master_id (cif_exact) y Nombre→master_id (name_exact/name_partial). Sin JWT, sin /master/*, sin Mongo. Modelos `CompanyResolve*` (nombres únicos para no colisionar con `master.py::ResolveRequest` — evita romper el freeze v1).
- **Caso canónico F0.2 verificado:** CIF `A87803862` (TOTALENERGIES) → identity completa + financial-analyze con L2 real (revenue 933M, EBITDA 36,5M, net_income 25M), histórico real 3 años (2024/2023/2022, sin interpolar) y `explainability.data_source` trazable a Iberinform.
- **Contrato v2 re-congelado:** 55 paths (añade `/resolve`), 94 schemas. `arroba.v1` sigue byte-idéntico (53 paths). Freeze test v2 actualizado (55). 10 golden tests verdes.
- **Verificado:** testing_agent backend 100% (resolve CIF/nombre/401/422, caso canónico agnóstico CIF↔master_id, regresión contratos). Report: `/app/test_reports/iteration_33.json`.


## 2026-07-12 — Desbloqueo Data Layer · Bootstrap reproducible + dataset canónico ✅
- **Diagnóstico:** NO hay bug de mapeo raw→master (norm_financials→master.financials: 0 pérdidas). El 404 "para todas" es por **BD de producción vacía** (despliegue independiente). Cobertura financiera 374/1000 = cobertura real de la fuente.
- **Track A — Bootstrap reproducible:** `services/data_layer/bootstrap.py` reconstruye TODO el Data Layer desde la fuente oficial (`tests/fixtures/iberinform_sample`, real) sin pasos manuales: ingestión→master(+ER+financieros)→ownership→signals canónicas→índice semántico canónico→verificación→set canónico. 3 vías: self-healing al arranque (`AUTO_BOOTSTRAP_DATA_LAYER=1` si Master vacío), endpoint `POST /api/v1/data-layer/bootstrap` (JWT), y CLI `python -m services.data_layer.bootstrap`. Probado desde BD vacía: 1000 empresas, 2443 señales, 998 perfiles, ~15s.
- **Track B — Dataset canónico:** `select_canonical_set(50)` (data-driven, ≥2 ejercicios reales) → `db.canonical_validation_set` + `GET /api/v1/data-layer/canonical-set`. Empresas reales (TOTALENERGIES, SCANIA HISPANIA…). Cadena pública completa validada (identidad+financieros+histórico real+señales+semántica+estrategia).
- **Histórico:** solo ejercicios reales ingeridos; sin interpolar/estimar. Serie expuesta vía `evolution`.
- **Endpoints nuevos:** `POST /api/v1/data-layer/bootstrap`, `GET /bootstrap/{run_id}`, `GET /bootstrap`, `GET /canonical-set` (todos JWT). Startup self-healing hook `_auto_bootstrap_data_layer_if_empty()`.
- **Verificado:** testing_agent 20/20 (incl. regresión contratos congelados v1+v2). Informe: `DATA_LAYER_UNBLOCK_REPORT_v1.md`.


## 2026-07-12 — Sprint V2.0 · Contrato `arroba.v2` (V2-01 tipado DTOs + V2-02 Company/Identity) ✅ ADITIVA
- **V2-01 (tipado):** los 53 endpoints de los 6 motores tienen DTO de respuesta explícito en OpenAPI vía `responses={200:{"model":...}}` (NUNCA `response_model`). Runtime intacto (los DTO documentan, no filtran; `extra="allow"`). Nuevos DTOs en `routes/engine_schemas.py`.
- **V2-02 (Company/Identity):** `POST /api/v2/company-intelligence/identity` (auth `X-API-Key`, `capability_version=company-intelligence-v2`) → `CompanyIdentityResponse` proyectada del Master Record (añade `capital_social`, `domain`, `employees_total`). Alimenta COMP-1001/1002/1003. Router registrado en `server.py`.
- **`arroba.v1` congelado byte-idéntico:** `_build_arroba_openapi()` strippea las respuestas tipadas y filtra `components` al set del snapshot v1 → hash canónico idéntico, freeze tests verdes.
- **Nuevo contrato v2:** `_build_arroba_v2_openapi()` + `GET /api/v1/openapi/arroba.v2.json` (54 paths, 91 schemas) + `/api/docs/arroba/v2`. Snapshot congelado `contracts/arroba.v2.json` + freeze test `tests/golden/test_arroba_v2_contract_freeze.py`.
- **Verificado:** matriz contrato↔runtime **53/53 MATCH** (`tools/validate_matrix.py`), **10/10 golden tests**, testing_agent backend **22/22 (100%)**. SDK tipado auto-generable confirmado (OpenAPI 3.1 válido; `datamodel-code-generator` → 91 clases). Informe: `memory/ARROBA_V2_SPRINT_V2.0_REPORT.md`.


## 2026-07-12 — Utilidad AI Chat (OpenAI gpt-5.5) ✅ ADITIVA
- **Backend** `routes/ai_chat.py` (prefijo `/api/ai-chat`, fuera de `arroba.v1`): `POST /message` (gpt-5.5 vía `emergentintegrations` LlmChat con **OPENAI_API_KEY** propia del usuario), `GET /history/{session_id}`, `GET /sessions`, `DELETE /session/{session_id}`. Historial persistido en `ai_chat_messages`; memoria por `session_id`.
- **Frontend** `pages/AIChatPage.jsx` + ruta `/ai-chat` + ítem de menú HOME→AI Chat. UI request/response (no streaming: la lib instalada v0.1.0 solo soporta `send_message`).
- **Verificado:** backend por curl (respuesta real, memoria, historial) + testing_agent frontend **100% PASS**. No toca el contrato público ni otros motores. `OPENAI_API_KEY` guardada como secreto en `backend/.env`.

## 2026-07-04 — Cierre de Agency Tool como proveedor + Runbook de rotación de API Keys ✅
- **Producción confirmada:** `https://agencias.wearebudadvisors.com` (dominio custom; contrato v1 desplegado y verificado: `/api/v1/openapi/arroba.v1.json`, `/api/docs/arroba`, `/api/v1/health` → 200). Documentos de handoff/certificación actualizados con la URL de producción.
- **Runbook operativo** `memory/API_KEY_ROTATION_RUNBOOK.md`: rotación de `ARROBA_SERVICE_API_KEY` sin downtime (solape clave nueva/antigua en `db.api_keys`, migración del consumidor, revocación) + variante simple, verificación post-rotación y buenas prácticas. No bloquea la integración.
- **Hito:** Agency Tool queda **cerrado como proveedor de servicios** (contrato `arroba.v1` congelado). Nuevo desarrollo se realiza en arroba.com como consumidor. Se volverá a Agency Tool solo para incidencias, ampliaciones o publicar contrato `v2`.

## 2026-07-04 — CI gate del contrato de arroba.com (freeze en cada push) ✅
- **GitHub Actions** `.github/workflows/arroba-contract-freeze.yml`: en cada `push`/`pull_request` a main/master construye el contrato de arroba **en proceso** (sin servidor ni MongoDB; conexión Motor lazy) y lo compara por hash canónico con `backend/contracts/arroba.v1.json`.
- **Test offline añadido** `test_arroba_contract_matches_code_offline` en `tests/golden/test_arroba_contract_freeze.py` (4 tests en total; el subset de CI = 3, excluye el que requiere servidor vivo). Cualquier deriva de la superficie pública de los 6 motores **falla el CI** → obliga a `v2` deliberado; v1 no se puede romper en silencio.
- ⚠️ Para **bloquear el merge** hay que activar Branch Protection en GitHub exigiendo el check "Arroba Public Contract Freeze". Universo canónico 6.261 intacto.

## 2026-07-04 — Snapshot congelado + freeze test del contrato de arroba.com ✅
- **Endpoint versionado oficial** `GET /api/v1/openapi/arroba.v1.json` (fuente que consume arroba.com) + `GET /api/docs/arroba` (Swagger UI).
- **Snapshot físico congelado** `backend/contracts/arroba.v1.json` (referencia documental / comparación de versiones), **idéntico** al endpoint. `sha256(canonical)=0a266fff…f187f41`. README con política de versionado en `backend/contracts/README.md`.
- **Freeze test** `tests/golden/test_arroba_contract_freeze.py` (3 tests, read-only, no toca colecciones canónicas): verifica que endpoint↔snapshot son idénticos (hash canónico) y que solo exponen los 6 motores. Cualquier deriva de la superficie pública falla el test → obliga a un `v2` deliberado sin romper v1.
- **Handoff completo** para arroba.com: `memory/ARROBA_ONBOARDING_HANDOFF.md` (URL base, auth, OpenAPI, generación de cliente, pasos, ejemplos, límites). Universo canónico 6.261 intacto; ningún endpoint/schema de motor modificado.

## 2026-07-04 — Contrato OpenAPI filtrado para arroba.com (desacople externo/interno) ✅
- **Añadido `GET /api/v1/openapi/arroba.json`**: contrato público filtrado (`arroba-integration-contract-v1`) con **solo los 6 motores** (Financial 3, Signal 7, Semantic 6, Recommendation 11, Strategy 13, Transaction 13 = **53 rutas**), incluye `components`/schemas; sin rutas administrativas ni de Valuo. `GET /api/docs/arroba` = Swagger UI del contrato filtrado.
- **Full spec interno intacto** en `/api/v1/openapi.json` + `/api/docs` + `/api/redoc` (496 rutas). Cambio derivado/config; ningún endpoint ni schema de motor modificado. Verificado en vivo (`200`, 0 fugas), backend sano, universo 6.261 intacto. Ver `ARROBA_INTEGRATION_READINESS_CERT.md` (Atención A).

## 2026-07-04 — Punto A · OpenAPI expuesto bajo `/api/...` (mejora operativa) ✅
- **Solo configuración, sin cambios de contrato.** Reubicados los endpoints integrados de FastAPI: `openapi_url=/api/v1/openapi.json`, `docs_url=/api/docs`, `redoc_url=/api/redoc`. Antes iban fuera de `/api` y el ingress los enrutaba al frontend (devolvían HTML de la SPA).
- **Resultado:** `GET /api/v1/openapi.json` (OpenAPI 3.1.0, 496 rutas, coincidente con la implementación), `GET /api/docs` (Swagger UI) y `GET /api/redoc` accesibles públicamente → arroba.com ya puede autodescargar el contrato. Verificado en vivo (`200`); backend sano; universo canónico 6.261 intacto; ningún endpoint ni schema de motor modificado. `ARROBA_INTEGRATION_READINESS_CERT.md` (Atención A → RESUELTO).

## 2026-07-04 — Recuperación del universo canónico (proyección M3-2b re-ejecutada) ✅
- **Solo datos, cero cambios de código/contrato.** Re-ejecutada `legacy_projection.project_and_build` (4 batches, 5.261 proyectados) → `master_companies` **1.000 → 6.261**. Bridge re-medido `erb_c0c480261423`: **cobertura 98,13 %** (5.257 enlazadas / 5.357; 23 conflictos, 4 ambiguas, 73 huérfanas, 27 revisión manual); overlap CIF legacy **99,02 %**.
- **Validación de contrato:** Golden 111 + Smoke 203 = **314/314 verde**; endpoint público `financial-intelligence/analyze` y entidad proyectada `mc_d178502397b0` verificados en vivo con `engine_version` intacto. Ningún endpoint ni schema modificado.
- **Causa raíz documentada:** app y suite de tests comparten `test_database`; `test_jobs.py` borra `norm_company` + smoke tests hacen `rebuild_master(full)` → resetean el universo a ~1.000 en preview. En producción no ocurre (tests no corren contra BD productiva). Ver `ARROBA_INTEGRATION_READINESS_CERT.md` (Atención B, RESUELTO).

## 2026-07-04 — Contrato de Integración v1.0 + Certificación de readiness · arroba.com 📄
- **Documento oficial** `memory/ARROBA_INTEGRATION_CONTRACT_v1.md` (`arroba-integration-contract-v1`): fuente única de verdad para que arroba.com consuma la inteligencia SIN conocer la implementación interna. Sin código.
- Cubre las 11 secciones solicitadas: arquitectura por capas (responsabilidad/owner/entradas/salidas), inventario de 26 entidades, inventario de colecciones (claves/índices/cardinalidad/estado), contrato API completo (endpoints de los 6 motores + Master, auth `X-API-Key`, códigos de error, paginación, límites 600/min, versión), matriz de consumo por bloque de arroba, schema completo por endpoint, estado de implementación (🟢🟡🟠🔴), estrategia de sincronización, roadmap (actual/siguiente/futuro), contrato de estabilidad (congelado/aditivo/ruptura) y matriz final obligatoria.
- Basado 100% en auditoría del código real (rutas, modelos de request, colecciones, contratos congelados `*_ENGINE_CONTRACT.md`). No se modificó ningún endpoint ni comportamiento.

## 2026-07-04 — Sprint 8.6 · M3 Fase 2b · Ingesta & Cobertura del Master Record ✅
- **Proyección legacy→canónica** `services/data_layer/master/legacy_projection.py` (`project_and_build`): proyecta identidades legacy ausentes a `norm_company` (etiquetadas `source='companies_master_projection'`, `projection_batch`) y reconstruye vía `rebuild_master(scope='cif_list')`. Preserva invariantes de `master_builder`; **reversible por batch** (`rollback_projection`).
- **Requisitos respetados**: `companies_master` intacto (solo lectura), sin cambio en producción, motor canónico NO activado, sin migrar tráfico, sin borrar datos, sin matcher fuzzy, sin reanudar M2.
- **Resultado**: universo canónico 1.000→**6.259** (5.259 proyectados, 2 batches). Bridge re-ejecutado (`erb_202d8224d594`): **cobertura 0 % → 98,17 %** (5.255 enlazadas / 5.353; 21 conflictos, 4 ambiguas, 73 huérfanas, 25 revisión manual, 0 duplicados). Overlap por CIF: legacy 99,02 %. **Objetivo ≥95 % superado.**
- **Recomendación**: bloqueante de cobertura RESUELTO. **NO activar `canonical`** hasta resolver los 25 casos de revisión manual + huérfanas y aprobar nuevo informe. M2 queda desbloqueado para retomarse. Ver `M3_PHASE2B_REPORT.md`.

## 2026-06-26 — Sprint 8.5 · M3 Fase 2 · Entity Bridge & Master Record Quality Tool ✅
- **Herramienta permanente** `services/data_layer/master/entity_bridge.py` (+ rutas admin `/api/v1/master/bridge/*`): construye el bridge canónico `master_company_id`↔`master_id` en `entity_xref` (origin='er_bridge') y mide calidad. **Idempotente, auditable, reversible** (rollback por run_id), histórico en `er_bridge_runs`, clasificación por entidad en `er_bridge_results`.
- **Requisitos respetados**: legacy nunca modificado, sin cambio en producción, motor canónico NO activado, sin migrar tráfico, sin eliminar datos.
- **Medición**: 5350 legacy vs 1000 canónicos → **cobertura 0 %** (100% huérfanos; datasets disjuntos por cif/domain/name). Golden suite 106→**111 verde**. Detector de conflictos/ambigüedades/duplicados implementado y probado.
- **Recomendación**: **NO activar `canonical`** (orfanaría el 100% de Valuo.pro). Prerrequisito: ampliar la ingesta canónica al universo real y re-ejecutar el bridge hasta cobertura objetivo. `M3_PHASE2_BRIDGE_REPORT.md`.

## 2026-06-26 — Sprint 8.4 · M3 (Entity Resolution) Fase 1 ✅ (motor canónico + red de seguridad, sin migrar)
- **Contrato CONGELADO** `entity-resolution-v1` (DER1–DER9 aprobadas). `ENTITY_RESOLUTION_CONTRACT.md`.
- **Motor canónico unificado**: `services/data_layer/master/identity_resolver.py` — `resolve_identity` (shape legacy-compatible), `deterministic_master_id` (DER5), `link_legacy_master` (DER3 bridge legacy↔canónico en `entity_xref`), umbrales congelados DER4, auditoría append-only DER6.
- **Provider de convivencia** `services/entity_resolution_provider.py` (flag interno `ENTITY_RESOLUTION_SOURCE`, default `legacy`), cableado en `valuo_integration`/`master`/`procurement` vía alias (call sites intactos). Contrato público único (DER7); rollback inmediato.
- **Red de seguridad**: snapshot-diff de `resolve_entity` (cif_exact/domain_exact/discovered) + guards del provider. Golden suite 96 → **106 tests verde**. Smoke **203/203** (cero regresión en ruta Valuo.pro).
- **NO** se retira legacy, **NO** se migra tráfico, **NO** backfill masivo (→ M3-fase-2, DER8). Default legacy = byte-identical.

## 2026-06-26 — Sprint 8.3 · M2 inicio → DETENIDA EN VALIDACIÓN (bloqueante de cobertura) ⛔
- **Infraestructura de convivencia interna (contrato público único)**: flag `MASTER_RECORD_SOURCE` (default `legacy`), `services/intelligence_engine/master_provider.py` (legacy byte-identical / canónico con fallback transparente), cableado en `enrich_company`. Sin `?source=` público; rollback inmediato; el canónico nunca causa `master_not_found`.
- **Golden dataset ampliado**: 9→**14 empresas** / 18→**28 snapshots** con casos límite (micro/pyme/holding/incompletos/sin_web/baja_calidad/discovered). Golden suite 82 → **96 tests verde**. Smoke **203/203** (cero regresión en ruta crítica de Valuo.pro).
- **BLOQUEANTE**: `companies_master` (5338) y `master_companies` (1000) son **DISJUNTOS** (overlap `cif_normalized`=0; resolución canónica 0/14). Paridad estructuralmente imposible → legacy NO retirado, tráfico NO migrado. Ver `MASTER_SOURCE_PARITY_REPORT.md`.
- **Re-secuenciación recomendada**: M2 depende de cobertura del Master canónico ⇒ priorizar **M3 (Entity Resolution)** + **M2-pre (backfill/linkage)** antes de reanudar M2. Infra de M2 lista y desactivada, sin riesgo.

## 2026-06-26 — Sprint 8.2b · Preparación M2 (snapshot-diff + golden dataset) 🟡
- **Red de paridad para M2**: golden dataset congelado de 9 empresas × {valuo, arroba} = **18 snapshots** (`tests/golden/data/enrich_golden_snapshots.json`); generador `tests/golden/gen_enrich_golden.py`; util `enrich_snapshot_util.py` (normalización order-insensitive); test `test_enrich_snapshot_diff.py` (paridad byte-level de `fields`/`sources_with_data`/`found_map`/`engine_version`).
- **Suite golden: 62 → 82 tests** (todas verdes, idempotentes). **Sin cambios de código de producción** (solo harness de prueba).
- Propósito: detectar cualquier deriva de cálculo cuando M2 cambie el origen de datos interno (`companies_master` → `master_companies`) sin tocar el contrato externo.

## 2026-06-26 — Sprint 8.2 · M1 migración piloto (relocalización Signal legacy) ✅
- **Componente migrado**: `services/signal_engine.py` (legacy master-signals: `signal_score`, `signals[]`, `signal_similarity` sobre `companies_master`) → **relocalizado byte-for-byte** a `services/engines/signal/master_signals.py` (md5 idéntico).
- **Implementación retirada**: ninguna (fase CONVIVENCIA). `services/signal_engine.py` permanece como **shim** que re-exporta `compute_signals/rebuild_signals/signal_similarity`. Retirada diferida.
- **Consumidores migrados a la ruta canónica**: `routes/data_layer.py` (`rebuild_signals`), `services/skills_recommend.py` (`signal_similarity`).
- **Impacto**: 🟢 nulo en Valuo.pro y arroba.com; `rebuild-signals` (Console) y `skills/recommend` (arroba) con contrato idéntico.
- **Riesgo real observado**: BAJO/nulo. Sin cambios de contrato, sin regresiones.
- **Validación**: Golden 62/62 (incl. paridad shim↔canónico), Smoke 203/203, snapshot determinista (`signal_score=71`) congelado.
- **Lección aprendida**: sin equivalente funcional, "migrar" = **relocalizar + shim** (consolidar ubicación), no sustituir lógica. La sustitución semántica (consumir entidades canónicas del `engines/signal.engine`) queda como trabajo futuro con su propio contrato.

## 2026-06-26 — Sprint 8.1 · Golden Contract Tests (red de seguridad)
- Suite black-box `/app/backend/tests/golden/` congelando 19 endpoints 🔴 Legacy crítico (47 tests). Sin cambios de código de producción.

## 2026-06-26 — Sprint 8 · Auditoría final + plan de migración
- `AGENCY_TOOL_AUDIT_FINAL.md`, `LEGACY_MIGRATION_PLAN.md`, `INTELLIGENCE_API_REFERENCE.md`, `PLATFORM_GOVERNANCE_AND_CONSUMER_AUDIT.md`. 0 componentes retirables.

## 2026-06-26 — Sprint 7 · Transaction OS + Transaction Intelligence Engine
- `transaction-os-v1` / `transaction-intelligence-v1` (DTX1–DTX13). Cima del DAG. Smoke 203/203.
