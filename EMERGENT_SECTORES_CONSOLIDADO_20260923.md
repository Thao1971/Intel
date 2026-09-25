# Entrega consolidada Intel · Sectores

Añade al ZIP de valoración ya auditado:

- motores públicos `sector-market`: crecimiento, BORME mensual, operaciones M&A y organismos públicos;
- ranking precomputado de sectores ARROBA/CNAE;
- registro del router en `backend/server.py`;
- contrato OpenAPI actualizado;
- agregados de contratación pública precomputados: ninguna ficha recorre `public_procurement_contracts`.

## Despliegue obligatorio

1. Desplegar este ZIP en Preview.
2. Ejecutar una vez, con sesión admin: `POST /api/v1/public/sector-market/aggregates/rebuild`.
3. Validar `GET /api/v1/public/sector-market/ranking?lens=arroba&metric=size`.
4. Validar los cuatro endpoints con un CNAE real, por ejemplo `6201`.
5. Confirmar que `sector_aggregates`, `sector_aggregates_meta` y `sector_top_buyers` están pobladas.
6. Programar el rebuild nocturno o tras actualizar las fuentes.
7. Desplegar Beta después de Intel.

No incorpora proxies Beta ni duplica el screener ya incluido en la entrega base.
