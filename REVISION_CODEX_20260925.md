# Revisión Codex · Intel · 25-09-2026

Este ZIP conserva íntegra la entrega corregida de Emergent y añade protección de concurrencia al flujo de solicitudes y NDA.

## Cambios

- Índice único `(listing_id, buyer_id)` con nombre explícito para impedir solicitudes duplicadas bajo concurrencia.
- Los cambios de estado `pending → awaiting_buyer_nda/rejected`, `awaiting_buyer_nda → nda_signed` y retirada se actualizan de forma condicional por el estado esperado.
- Si dos acciones compiten, la segunda recibe un error claro y debe actualizar la pantalla; el pipeline solo se sincroniza después de confirmar el cambio.
- Las inserciones duplicadas se traducen a una validación de dominio, sin exponer errores de Mongo.

## Validación

- `py_compile` de `server.py` y `my_space_requests.py`: OK.
- Tests dirigidos de solicitudes y endurecimiento: 20/20 OK.
- Suite unitaria seleccionada de Mi espacio, valoración y entrega: 51 tests OK.
- Las 20 pruebas `test_sector_intelligence_v2.py` requieren el Preview remoto configurado por el propio test y no se ejecutaron contra producción desde este entorno.

## Preflight de despliegue

Antes del primer arranque, comprobar que no existan duplicados históricos en `my_space_requests` para la misma pareja `listing_id + buyer_id`. En una instalación nueva no habrá ninguno. Si los hubiera, resolverlos conservando la solicitud vigente antes de crear `uniq_listing_buyer`.
