# Metodología WACC de Arroba

## 1. Finalidad

El WACC representa la rentabilidad exigida por quienes financian el negocio. Se utiliza para
descontar el FCFF porque este flujo está disponible para acreedores y accionistas.

La versión actual es arroba-wacc-v1. El resultado permanece screen_grade mientras contenga
semillas provisionales.

## 2. Fórmula

~~~text
WACC = Ke × E/(D+E) + Kd × (1-T) × D/(D+E)
~~~

Donde Ke es coste de los fondos propios, Kd coste de deuda antes de impuestos, T tipo fiscal,
D deuda objetivo y E fondos propios objetivo.

## 3. Coste de los fondos propios

~~~text
Ke = Rf + beta_apalancada × ERP + prima_país + prima_tamaño
~~~

### Tipo sin riesgo

Debe proceder de una curva en euros, con fecha y vencimiento coherente con la duración del
negocio. La fuente prevista es la curva publicada por el BCE. La semilla inicial del 2,50%
no es una observación BCE y está identificada como arroba_policy_seed.

Referencia: https://data.ecb.europa.eu/methodology/yield-curves

### Prima de mercado

La referencia inicial es 5,89%, procedente del conjunto global de betas y primas de
Damodaran de enero de 2026. Debe almacenarse con fuente y fecha y actualizarse cuando cambie
la captura de mercado.

Referencias:

- https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/BetasGlobal.html
- https://pages.stern.nyu.edu/adamodar/New_Home_Page/datacurrent.html

### Beta

Para cada comparable:

~~~text
Beta desapalancada = Beta apalancada / (1 + (1-T) × D/E)
~~~

La beta sectorial es la mediana de las betas desapalancadas válidas. Se requieren al menos
cinco comparables para considerarla observada. Después se reapalanca:

~~~text
Beta apalancada objetivo = Beta desapalancada × (1 + (1-T) × D/E objetivo)
~~~

Hasta conectar la muestra de cotizadas, Intel utiliza betas semilla por arquetipo. La de
publicidad, 0,98, coincide con la referencia global publicada por Damodaran en enero de
2026; el resto se mantiene explícitamente como política provisional de Arroba.

### Prima de tamaño

La versión inicial añade:

| Tamaño | Prima |
|---|---:|
| Micro | 2,50% |
| Pequeña | 1,50% |
| Mediana | 0,75% |
| Grande | 0,00% |
| Desconocida | 1,50% |

Estas primas son semillas y deberán calibrarse con evidencia de mercado. Se muestran como
componente independiente para evitar ocultarlas dentro de beta o ERP.

## 4. Coste de deuda

Cuando existen deuda e intereses financieros:

~~~text
Kd observado = abs(gastos financieros) / deuda financiera
~~~

Solo se acepta un resultado entre 0% y 30%. Es una aproximación basada en saldo final; una
versión posterior utilizará deuda media cuando exista.

Si no puede observarse, se utiliza:

~~~text
Kd = Rf + spread de crédito por tamaño
~~~

| Tamaño | Spread provisional |
|---|---:|
| Micro | 4,50% |
| Pequeña | 3,50% |
| Mediana | 2,50% |
| Grande | 1,80% |
| Desconocida | 3,50% |

El coste después de impuestos es Kd × (1-T).

Las condiciones bancarias pueden cambiar durante el año. El Banco de España señaló en julio
de 2026 un endurecimiento de la oferta de crédito y aumentos de tipos declarados por empresas,
por lo que el componente de deuda debe fecharse y actualizarse.

## 5. Estructura de capital

La estructura objetivo debe proceder de la mediana de comparables:

~~~text
Peso deuda = Deuda / (Deuda + Capitalización)
Peso equity = 1 - Peso deuda
~~~

Hasta disponer de al menos cinco comparables válidos se utilizan pesos semilla por
arquetipo. La estructura contable concreta de la empresa se muestra en el puente a equity,
pero no se adopta automáticamente como estructura objetivo de largo plazo.

## 6. Tipo fiscal

La versión inicial emplea 25% como tipo normalizado. No se utiliza necesariamente el tipo
efectivo de un único año, que puede estar distorsionado por pérdidas o deducciones.

## 7. Jerarquía

1. Inputs explícitos revisados.
2. Comparables públicos observados.
3. Coste de deuda observado en Iberinform.
4. Datos de mercado externos fechados.
5. Semillas sectoriales y de tamaño de Arroba.

Cada componente conserva valor, fuente, fecha, fórmula y estado.

## 8. Estados

- screen_grade: existe al menos un componente provisional.
- reviewed_market_inputs: todos los componentes materiales están fechados y revisados.
- unavailable: faltan elementos esenciales o no superan validación.

## 9. Controles

- Pesos de deuda y equity suman 100%.
- Deuda objetivo entre 0% y 80%.
- Tipo fiscal entre 0% y 100%.
- Coste de deuda observado entre 0% y 30%.
- Beta y muestra de comparables identificables.
- Fuente y fecha de cada input.
- WACC superior al crecimiento terminal.
- Sensibilidad del DCF alrededor del WACC.

## 10. Salida

El bloque wacc_analysis contiene WACC, coste de equity, coste de deuda, betas, primas,
estructura objetivo, fuentes, fecha, advertencias y estado de preparación. El DCF adopta ese
WACC y conserva el bloque completo para Beta y el PDF.

## 11. Limitaciones actuales

- Tipo sin riesgo todavía provisional.
- Prima país todavía provisional.
- Betas y estructuras objetivo pendientes del universo de cotizadas.
- Prima de tamaño pendiente de calibración.
- Coste de deuda observado usa deuda de cierre.
- No se modelan rating sintético ni spreads por cobertura de intereses.

## 12. Captura automática BCE

Intel usa la serie oficial YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y: curva AAA de la zona euro,
tipo spot a diez años, frecuencia diaria hábil y unidad porcentaje anual.

El scheduler ejecuta refresh_ecb_risk_free después de la actualización nocturna. Cada
observación se guarda de forma idempotente por serie y fecha en valuation_market_snapshots.
La última captura verificada durante el desarrollo es 17 de septiembre de 2026, 3,487506%.

Si la captura diaria falla, Intel conserva la última observación almacenada, registra el
fallo en intelligence_sync_log y no sustituye silenciosamente el dato por cero.

## 13. Fuentes de cotizadas

MarketScreener aporta la muestra nominal española y sus múltiplos. Damodaran aporta
referencias sectoriales regionales. Capital IQ queda excluido de la arquitectura operativa.
La muestra española disponible no contiene beta, capitalización ni deuda financiera, por lo
que no se usa para estimar beta o estructura objetivo. Hasta disponer de una fuente pública
reproducible con esos campos, el WACC conserva y declara las semillas sectoriales.

## Inputs fechados y controles de calidad

El WACC separa el ERP de mercado maduro del riesgo país español. La referencia de enero de
2026 utiliza 4,23% de ERP maduro y 1,55% de prima de riesgo país para España, ambos con
fuente y fecha Damodaran. Las observaciones posteriores se almacenan como
`ERP.MATURE_MARKET` y `CRP.ESP` en `valuation_market_snapshots`; el motor toma siempre la
última fecha disponible.

Una beta cotizada solo se acepta cuando es positiva y no supera 4, la capitalización es
positiva, la deuda no es negativa y el peso de deuda no supera 90%. Se exigen al menos cinco
comparables válidos para sustituir la semilla sectorial. La ausencia de muestra, los campos
faltantes y cada exclusión se muestran explícitamente. El tipo sin riesgo genera advertencia
a partir de 45 días; ERP y prima país, a partir de 550 días.

El Excel español de MarketScreener disponible contiene múltiplos, pero no betas ni estructura
de capital. Por ello no se utiliza para estimar beta o apalancamiento. La sustitución de esas semillas requerirá una fuente pública reproducible con beta,
capitalización y deuda financiera trazables; no se presupone Capital IQ.
