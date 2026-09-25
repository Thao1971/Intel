# contracts/ — Contratos públicos congelados (Agency Tool → arroba.com)

Snapshots documentales versionados del contrato de integración que consume arroba.com.

## Archivos
- **`arroba.v1.json`** — snapshot **congelado** del contrato público v1 (`arroba-integration-contract-v1`).
  - Contiene **solo los 6 motores** (Financial, Signal, Semantic, Recommendation, Strategy, Transaction) = **53 rutas** + `components`/schemas.
  - Es **idéntico** a lo que sirve el endpoint en vivo `GET /api/v1/openapi/arroba.v1.json`.
  - `sha256(canonical)` de referencia: `0a266fff6d73ca579b8fe05dd28169c0b9bbaf27bb917a7f001ad2833f187f41`.

## Fuente de verdad vs. referencia documental
- **Fuente que consume arroba.com:** el **endpoint** `GET /api/v1/openapi/arroba.v1.json` (siempre en vivo).
- **Referencia documental / comparación de versiones:** este **snapshot** `arroba.v1.json`.
- Ambos DEBEN ser idénticos. Lo garantiza el test `tests/golden/test_arroba_contract_freeze.py`
  (compara el hash canónico del endpoint en vivo contra el snapshot).

## Política de versionado (obligatoria)
- **v1 está congelada.** Cualquier cambio en la superficie pública de los 6 motores hace que el test de
  freeze **falle** → señal de que NO puede colarse un cambio silencioso.
- Cambios **aditivos compatibles** (nuevo endpoint, nuevo campo opcional, nuevo tipo en enum abierto):
  permitidos, pero requieren **regenerar deliberadamente** el snapshot v1 y documentarlo.
- Cambios **incompatibles** (eliminar/renombrar campo o endpoint, cambiar tipo/semántica/errores/auth):
  **prohibido en v1**. Se crea **`arroba.v2.json`** + endpoint `GET /api/v1/openapi/arroba.v2.json`,
  conviviendo con v1 hasta que arroba.com valide y migre.

## Regenerar el snapshot (solo en un bump deliberado de versión)
```bash
BASE=<base_url>
curl -s "$BASE/api/v1/openapi/arroba.v1.json" -o backend/contracts/arroba.v1.json
```

## Contrato especializado de valoración Intel–Beta

- **`intel-beta-valuation.v1.schema.json`** — esquema JSON congelado del paquete de valoración.
- **`INTEL_BETA_VALUATION_CONTRACT.md`** — reglas funcionales y de consumo por Beta.
- **Endpoint:** `POST /api/v2/financial-intelligence/valuation`.

Este contrato especializado puede evolucionar sin alterar el contrato general congelado de
los seis motores. Los cambios incompatibles requieren una nueva versión del archivo y de
`contract_version`.
