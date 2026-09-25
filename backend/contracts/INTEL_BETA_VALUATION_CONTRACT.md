# Contrato de valoración Intel–Beta

**Versión:** `intel-beta-valuation-v1`  
**Esquema:** `backend/contracts/intel-beta-valuation.v1.schema.json`  
**Endpoint:** `POST /api/v2/financial-intelligence/valuation`

Intel calcula y entrega el paquete completo. Beta debe limitarse a formatear cifras, textos y
gráficos; no recalcula pesos, rangos, escenarios, confianza, múltiplos, WACC ni el puente de
Enterprise Value a Equity Value.

## Estructura

| Bloque | Contenido |
|---|---|
| `summary` | Fecha, moneda, EV y Equity Value centrales y sus rangos |
| `methods` | Métodos aplicados, pesos y métodos excluidos con el motivo |
| `scenarios` | Rango conciliado, escenarios DCF y escenarios por múltiplos |
| `assumptions` | Hipótesis DCF, WACC, regla sectorial y puente de deuda neta |
| `comparables` | Referencia pública, ajuste a empresa privada, peers y TTR |
| `sensitivity` | Matriz WACC–crecimiento terminal |
| `confidence` | Puntuación, grado, número de métodos y regla de ponderación |
| `warnings` | Advertencias que Beta debe mostrar sin reinterpretarlas |
| `methodology_narrative` | Explicaciones financieras preparadas por Intel |
| `sources_and_versions` | Fuentes, linaje, reglas y versiones de los motores |

## Reglas de consumo

1. `contract_version` se valida antes de representar el resultado.
2. `status=unavailable` no se transforma en una cifra estimada en Beta.
3. `equity_value_available=false` impide mostrar Equity Value como conclusión.
4. Solo `methods.applied` participa en el rango final. Los elementos de `methods.excluded`
   se muestran con su motivo cuando el documento incluya la tabla metodológica.
5. Las cifras monetarias llegan en unidades completas de `summary.currency`.
6. Los textos y advertencias proceden de Intel y se adaptan únicamente en presentación.
7. Los campos nuevos serán aditivos durante la vigencia de v1. Un cambio de significado,
   tipo o campo obligatorio exige una nueva versión del contrato.

El esquema JSON está congelado por una prueba automática. Un cambio accidental en el DTO
hace fallar la validación y obliga a versionar o regenerar deliberadamente el contrato.
