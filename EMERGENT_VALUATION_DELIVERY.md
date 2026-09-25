# Entrega de valoración — Intel

Intel contiene el motor de valoración, cuentas normalizadas, DCF, WACC, comparables, conciliación, referencias sectoriales y generación del PDF.

La valoración avanzada se calcula con `POST /api/v1/valuations/advanced/calculate`.
Intel acepta las entradas revisadas, recalcula el paquete canónico, guarda la
ejecución en `valuation_advanced_runs` y permite recuperarla o descargar su PDF
mediante `/api/v1/valuations/advanced/{run_id}`.

## Despliegue

1. Conectar `MONGO_URL` y `DB_NAME` a la base productiva con `master_companies` y `norm_financials` de Iberinform.
2. Definir un `JWT_SECRET` fuerte y `AUTO_BOOTSTRAP_DATA_LAYER=0`.
3. Instalar `backend/requirements.txt`.
4. Ejecutar desde `backend`: `PYTHONPATH=. python -m services.engines.valuation.validation.validation_runner`.
5. Arrancar y comprobar `/api/v1/health/deep`.
6. Con `Authorization` válida, comprobar intake, catálogo de mercado y PDF.
7. Crear la clave de servicio que Emergent guardará exclusivamente en la pasarela de Beta.

Las referencias públicas y privadas permanecen como evidencias separadas. La conciliación asigna pesos según comparabilidad, recencia y calidad; no crea un promedio artificial.

## Analizar empresas

Intel expone el screener multi-criterio en `/api/v2/company-intelligence/screen`, `/screen/count` y `/screen/signals`. Filtra directamente `master_companies`; requiere los índices creados idempotentemente por el motor.
