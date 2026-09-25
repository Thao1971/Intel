# Informe de validación del motor de valoración

**Estado:** PASSED
**Cesta:** valuation-validation-basket-v1
**Fecha de referencia:** 2025-12-31

## Resultados por compañía

| Sector | Compañía | EV motor (M€) | Rango manual (M€) | Regresión | Resultado |
|---|---|---:|---:|---:|---|
| inmobiliario | MERLIN PROPERTIES, SOCIMI, S.A. | 2,351.86 | 2,200–2,600 | 0.00% | OK |
| medios | ATRESMEDIA CORP. DE MEDIOS DE COM. S.A. | 1,642.51 | 1,500–1,800 | 0.00% | OK |
| industria | ACERINOX, S.A. | 6,002.71 | 5,500–6,500 | 0.00% | OK |
| distribucion | DIA-DISTRIBUIDORA INT. DE ALIMENT. S.A. | 1,599.71 | 1,450–1,750 | 0.00% | OK |
| servicios | PROSEGUR, CIA. DE SEGURIDAD, S.A. | 1,944.26 | 1,750–2,150 | 0.00% | OK |
| software | INDRA SISTEMAS, S.A., SERIE A | 7,762.60 | 7,200–8,300 | 0.00% | OK |

## Casos extremos

- missing_debt_blocks_equity: OK
- negative_range_is_rejected: OK
- weights_sum_to_one: OK

## Criterio de promoción

Una versión puede promoverse si cubre los seis sectores, permanece dentro de los rangos manuales congelados, no supera una desviación del 0,5 % frente a la línea base y mantiene los controles de coherencia financiera. La cesta debe versionarse para cambiar una línea base.
