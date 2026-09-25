# Guía financiera de valoración, fuentes y gobierno del dato

**Documento de referencia de arroba**  
**Versión:** 1.0 · **Fecha:** 22 de septiembre de 2026 · **Propietario:** Equipo de valoración y datos financieros

## 1. Finalidad y principio de trazabilidad

Esta guía describe cómo arroba construye una valoración y cómo se mantiene cada dato que interviene en ella. Su objetivo es que un analista pueda responder, para cualquier resultado: **qué se ha calculado, con qué fecha, a partir de qué fuente, con qué regla y qué limitación conserva**.

El motor estima primero el **Enterprise Value (EV)** —el valor del negocio operativo— y calcula el **Equity Value** solo cuando conoce deuda financiera y caja. Nunca se supone que una deuda ausente sea cero.

```text
Equity Value = Enterprise Value − Deuda financiera + Caja disponible ± ajustes identificados
```

Una valoración es *screen grade* cuando conserva algún input provisional, una fuente no actualizada o una muestra insuficiente. Esa señal debe acompañar al rango; no se elimina al exportar un PDF.

## 2. Arquitectura financiera y responsabilidades

| Capa | Contenido | Fuente de verdad | Responsable | Evidencia conservada |
|---|---|---|---|---|
| Cuentas de la empresa | balance, PyG, deuda, caja, intereses, circulante y capex | Iberinform, normalizado en arroba | Datos financieros | ejercicio, campos origen, fecha de carga y transformaciones |
| Universo empresarial | CNAE, tamaño, actividad y estado | Iberinform | Datos empresariales | identificador, CNAE, fecha de corte y versión de clasificación |
| Mercado público español | comparables y múltiplos observados | snapshot de cotizadas versionado | Valoración | muestra incluida, exclusiones, fecha y URL de cada observación |
| Mercado público internacional | referencias Europa y EE. UU. e histórico | archivos anuales de Damodaran | Valoración | archivo origen, fecha, región, subindustrias y cálculo |
| Mercado privado | múltiplos de transacciones cuando hay muestra comparable | referencia privada versionada; futura fuente transaccional | M&A / Valoración | fecha, geografía, sector, rango, tamaño y calidad de muestra |
| Datos macro | tipo sin riesgo, prima de mercado y riesgo país | BCE y Damodaran | Riesgo / Valoración | serie, URL, fecha de observación y estado |
| Motor de valoración | DCF, WACC, múltiplos, puente EV–Equity y conciliación | código y snapshots versionados de arroba | Producto / Ingeniería | versión del motor, inputs, advertencias y resultados |

La interfaz muestra resultados; las fuentes, snapshots, reglas y cálculos residen en el back office de arroba. Ningún texto comercial sustituye la trazabilidad de la fuente.

## 3. Registro de fuentes y actualización

| Datos | Fuente y URL | Uso | Cadencia | Regla si falla o falta |
|---|---|---|---|---|
| Cuentas, identificadores, CNAE y universo empresarial | Iberinform, mediante la integración contratada | históricos, cohortes y datos de empresa | carga inicial y actualización trimestral; antes si hay carga material | conservar última observación válida, marcar antigüedad y no inventar campos |
| Curva libre de riesgo EUR | [BCE — curva AAA euro a 10 años](https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y) | componente Rf del WACC | diaria hábil, tras la actualización nocturna | conservar última observación; registrar fallo y advertir si supera 45 días |
| Metodología curva BCE | [BCE — Yield curves methodology](https://data.ecb.europa.eu/methodology/yield-curves) | documentación de serie y vencimiento | revisión anual o ante cambio de metodología | revisión por Riesgo |
| ERP y prima de riesgo país | [Damodaran — country risk premium](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ctryprem.html) | coste de equity | mensual y cuando se publique una nueva tabla | conservar última captura fechada; advertir si supera 550 días |
| Betas globales | [Damodaran — global betas](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/BetasGlobal.html) | contraste de betas y calibración | mensual / al actualizar la muestra | no sustituir una beta observada por una media sin indicarlo |
| Datos sectoriales internacionales | [Damodaran — data current](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datacurrent.html) y [archivos históricos](https://pages.stern.nyu.edu/adamodar/New_Home_Page/dataarchived.html) | múltiplos Europa y EE. UU., series 2020–2025 | anual | conservar la última versión y etiquetar su fecha de corte |
| Cotizadas españolas | snapshot de cotizadas almacenado en arroba, con URL de origen por compañía | múltiplos de comparables españoles | al cargar un nuevo snapshot, al menos anual | no mezclar snapshots sin crear una nueva versión; publicar muestra y exclusiones |
| Operaciones privadas | referencia transaccional versionada en arroba; futura fuente M&A contratada | contraste de múltiplos privados | cuando exista una nueva muestra, mínimo semestral | no fabricar múltiplo privado; usar cotizadas ajustadas y bajar confianza |
| Tipos, spreads y condiciones bancarias | datos de empresa observados y publicaciones de Banco de España cuando sean necesarias | coste de deuda y contraste macro | con cada ejercicio de empresa; revisión mensual de mercado | usar Rf + spread provisional, identificado como semilla |

### Regla de captura

Cada carga debe incluir: fecha de descarga, fecha efectiva del dato, URL o referencia contractual, responsable, versión de fichero o pipeline, población inicial/final, reglas de exclusión y hash o identificador de snapshot cuando aplique. Los snapshots publicados son inmutables; una actualización crea una nueva versión, nunca modifica silenciosamente la anterior.

## 4. Datos financieros de empresa y normalización

La fuente operativa es Iberinform. Arroba normaliza las cuentas antes de calcular ratios. Cada normalización conserva el campo de origen, ejercicio, moneda y regla aplicada.

| Magnitud | Definición operativa | Uso | Control principal |
|---|---|---|---|
| Ingresos | cifra de negocio del ejercicio | crecimiento, EV/Ventas, márgenes | positivos, moneda y ejercicio identificados |
| EBITDA | EBIT + amortizaciones; sujeto a validación de signos | EV/EBITDA y capacidad de caja | no usar si falta una de las partidas críticas |
| EBIT | resultado operativo antes de intereses e impuestos | FCFF, margen y EV/EBIT | separar extraordinarios cuando estén identificados |
| Capex | inversiones con salida de caja | FCFF | normalizar signo; diferenciar mantenimiento/crecimiento si se dispone |
| Circulante operativo | clientes + existencias − proveedores | FCFF | no mezclar con activo corriente − pasivo corriente; usar esta aproximación solo si se declara |
| Deuda financiera | deuda bancaria, préstamos, bonos y otras obligaciones financieras | puente EV–Equity y WACC | deuda conocida no equivale a deuda estimada |
| Caja | efectivo y equivalentes disponibles | puente EV–Equity | comprobar que corresponde al mismo ejercicio que la deuda |
| Gastos financieros | intereses y gastos de financiación | coste de deuda observado | usar valor absoluto y validar coherencia con deuda |

Reglas de calidad: no se mezclan cuentas individuales y consolidadas dentro de una misma serie; se anualizan periodos incompletos solo con una regla explícita; los valores extremos se investigan antes de winsorizar; una pérdida económica válida no se excluye por ser negativa.

## 5. Definiciones de valor y puente financiero

```text
Enterprise Value (EV)  = valor de las operaciones, antes de la financiación
Deuda neta             = deuda financiera − caja
Equity Value           = EV − deuda neta
```

Si falta deuda o caja, el motor puede mostrar EV pero **no calcula Equity Value**. Si ambos importes son cero y están informados, son valores conocidos y el puente es válido. Ajustes de minoritarios, activos no operativos, litigios u otros conceptos solo se incorporan si están identificados y documentados.

## 6. DCF: descuento de flujos de caja

El DCF estima el valor presente de la caja disponible para todos los financiadores.

```text
FCFF = EBIT × (1 − tipo fiscal)
       + amortizaciones
       − capex
       − incremento de circulante operativo

EV = Σ FCFF_t / (1 + WACC)^t + Valor terminal / (1 + WACC)^n
Valor terminal = FCFF_(n+1) / (WACC − g)
```

### Reglas de proyección

1. Las cuentas históricas son el punto de partida, no una extrapolación automática.
2. Ingresos, margen, capex y circulante se evalúan frente a la historia de la empresa, su tamaño, su arquetipo y la evidencia sectorial disponible.
3. El impuesto se normaliza para reflejar una carga sostenible; no se replica necesariamente el tipo efectivo de un año atípico.
4. El crecimiento terminal `g` debe ser inferior al WACC y compatible con una empresa madura en euros.
5. Se presentan casos conservador, base y optimista, junto con sensibilidad WACC–g.
6. Se publica el peso del valor terminal y se advierte cuando domine el resultado.

## 7. WACC, intereses y coste de la deuda

El WACC descuenta FCFF porque combina la rentabilidad exigida por accionistas y acreedores.

```text
WACC = Ke × E/(D+E) + Kd × (1−T) × D/(D+E)
Ke   = Rf + β apalancada × ERP + prima país + prima tamaño
```

| Componente | Cálculo y fuente | Regla de actualización / control |
|---|---|---|
| Rf | curva BCE AAA EUR spot 10 años | captura diaria hábil; avisar con más de 45 días |
| ERP | prima de mercado maduro Damodaran | captura mensual; avisar con más de 550 días |
| Prima país | prima de riesgo España Damodaran | captura mensual; avisar con más de 550 días |
| Beta | mediana de betas desapalancadas de comparables, después reapalancada a estructura objetivo | mínimo 5 comparables válidos; beta positiva y ≤ 4 |
| Estructura objetivo | mediana `D / (D + capitalización)` de comparables | mínimo 5 comparables válidos; deuda objetivo entre 0% y 80% |
| Prima de tamaño | tabla explícita por tamaño | es provisional hasta calibración; nunca se oculta dentro de la beta |
| Kd observado | `abs(gastos financieros) / deuda financiera` | aceptar solo entre 0% y 30%; usar deuda media cuando esté disponible |
| Kd sin observación | `Rf + spread por tamaño` | semilla explícita; debe rebajarse la confianza |
| Tipo fiscal T | tipo normalizado de 25% salvo evidencia que justifique otro | validar entre 0% y 100% |

La fórmula de desapalancamiento y reapalancamiento es:

```text
β desapalancada = β apalancada / (1 + (1−T) × D/E)
β objetivo      = β desapalancada × (1 + (1−T) × D/E objetivo)
```

El coste de deuda observado no es una cotización de mercado: es una aproximación basada en los intereses y la deuda del ejercicio. Si los intereses o la deuda no existen, arroba no afirma que conozca el coste real de financiación; utiliza la referencia `Rf + spread` como política provisional y lo muestra como tal.

## 8. Múltiplos de mercado

### 8.1 Cotizadas

Los múltiplos se calculan sobre EV para mantener independencia de la estructura financiera:

```text
EV/EBITDA = Enterprise Value / EBITDA
EV/EBIT   = Enterprise Value / EBIT
EV/Ventas = Enterprise Value / ingresos
```

PER y precio/valor contable son contrastes de equity y se usan cuando el sector y la calidad de los datos lo hacen apropiado. La estadística principal es la **mediana**, acompañada de P25, P75, tamaño de muestra, compañías incluidas y exclusiones. Se excluyen denominadores no positivos, datos incompletos y extremos según la política versionada; no se elimina una empresa por presentar malos resultados válidos.

### 8.2 Operaciones privadas

Las transacciones privadas son una capa distinta: reflejan precio pagado, control, sinergias, estructura de operación y condiciones de mercado. No se promedian automáticamente con cotizadas. Para una compañía concreta, la conciliación pondera ambos métodos por recencia, comparabilidad, tamaño de muestra y calidad de evidencia.

Cuando no existe una muestra privada suficiente, se usa la referencia pública con ajuste explícito por tamaño y se reduce la confianza. Un descuento por falta de liquidez se reserva para intereses minoritarios de equity; no se aplica automáticamente al EV.

### 8.3 Valor contable

El valor contable puede ser un contraste patrimonial para sectores intensivos en activos o negocios donde los activos sean determinantes. No debe convertirse por defecto en “un tercer múltiplo EV”: representa una lectura patrimonial distinta, con una conciliación y limitaciones propias.

## 9. Conciliación de métodos y rango final

El resultado no es la media aritmética de todos los métodos disponibles. Arroba puede combinar:

1. DCF, cuando hay cuentas y proyecciones defendibles.
2. Cotizadas comparables, cuando la muestra es suficiente y comparable.
3. Operaciones privadas, cuando hay evidencia transaccional reciente y comparable.
4. Valor patrimonial, cuando los activos tienen relevancia económica.

Cada método recibe peso según calidad del dato, similitud con la empresa, recencia, cobertura y estabilidad. El resultado conserva los métodos excluidos, la razón de exclusión, rango P25–P75 o sensibilidad y un valor central. La conciliación explica de forma narrativa por qué un método recibe más o menos peso.

## 10. Gobierno de sectores y calibración Iberinform

Las reglas sectoriales se calibran por:

```text
arquetipo × CNAE × tamaño × fecha de corte
```

La jerarquía de respaldo es: cohorte específica; CNAE y tamaño; CNAE; arquetipo y tamaño; arquetipo; referencia europea cotizada; semilla de arroba. Cada salto de jerarquía reduce la confianza.

Para cada cohorte se calculan P25, mediana y P75 de crecimiento, margen EBIT, amortización/ventas, capex/ventas y circulante/ventas. Las empresas se deduplican, se normalizan signos y moneda, se conservan las exclusiones, y una empresa recibe un único peso por métrica y ejercicio conforme a la política. La promoción sigue este orden:

```text
provisional_policy_seed → candidate_iberinform → reviewed_iberinform → calibrated_iberinform
```

Solo un snapshot `calibrated_iberinform` puede elevar la preparación más allá de *screen grade*. Las calibraciones se revisan trimestralmente, antes de cargas materiales y de forma integral anual.

## 11. Controles, excepciones y revisión

| Control | Regla |
|---|---|
| Coherencia de puente | sin deuda y caja conocidas, no hay Equity Value |
| WACC | pesos suman 100%, deuda objetivo 0%–80%, `WACC > g` |
| Coste de deuda | observado solo entre 0% y 30% |
| Comparables | muestra, inclusiones, exclusiones y fecha siempre identificadas |
| Histórico | no mezclar años, regiones ni metodologías en una misma serie |
| Actualización | toda recarga genera snapshot y nota de impacto frente a versión anterior |
| Regresión | cesta estable: inmobiliario, medios, industria, distribución, servicios y software |
| Casos extremos | comprobar deuda ausente, rangos negativos, denominadores nulos y concentración de terminal value |
| Aprobación | cambios materiales requieren revisión de negocio antes de promoción |

Un error de fuente, una fecha ausente o un input provisional no se corrige sustituyéndolo silenciosamente por un número. Se conserva el último valor válido, se registra el incidente y se comunica la limitación en el resultado.

## 12. Salida para cliente, PDF y auditoría

Toda valoración debe poder producir estos bloques:

- fecha de valoración y ejercicio de cuentas;
- descripción de empresa, actividad, CNAE y tamaño;
- métodos aplicados y métodos excluidos;
- EV, Equity Value cuando proceda, rango y valor central;
- puente EV–Equity;
- WACC desglosado: Rf, ERP, prima país, beta, tamaño, Kd, fiscalidad y estructura;
- comparables, percentiles, transacciones privadas y ajustes;
- supuestos de DCF y sensibilidad;
- fuentes, URLs, fechas, versiones y advertencias;
- nivel de confianza y limitaciones.

El PDF explica el método en lenguaje financiero. La ficha de auditoría conserva además los identificadores técnicos de snapshot, reglas de inclusión, campos fuente y versión del motor.

## 13. Checklist antes de publicar una valoración

1. ¿Las cuentas, moneda y ejercicio están identificados?
2. ¿Deuda y caja están completas antes de mostrar Equity Value?
3. ¿Cada input de WACC tiene fuente, fecha, URL y estado?
4. ¿Rf, ERP y prima país están dentro de su ventana de actualización?
5. ¿La beta y estructura objetivo proceden de comparables válidos o están marcadas como semilla?
6. ¿Los múltiplos informan muestra, fecha, percentiles y exclusiones?
7. ¿Las operaciones privadas son comparables y recientes, o se han excluido explícitamente?
8. ¿`WACC > g` y la sensibilidad se ha generado?
9. ¿Se muestra la confianza y todas las advertencias materiales?
10. ¿El resultado conserva versión de motor y snapshots de datos para reproducirlo?

## 14. Documentos vinculados

- [Metodología financiera](FINANCIAL_METHODOLOGY.md)
- [Metodología WACC](WACC_METHODOLOGY.md)
- [Runbook de calibración](CALIBRATION_RUNBOOK.md)
- [Especificación de comparables sectoriales](SECTOR_COMPARABLES_REPORT_SPEC.md)
- [Estándar narrativo del informe](VALUATION_REPORT_STANDARD.md)
- [Guía de entrega a Emergent](../../../../EMERGENT_VALUATION_DELIVERY.md)

---

**Nota de uso:** esta guía describe la metodología y sus controles; no constituye una recomendación de inversión, una opinión de valoración independiente ni asesoramiento legal, fiscal o contable.
