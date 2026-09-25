# Texto estándar para informes y PDF de valoración

Este documento define los textos que deben aparecer en las entregas de valoración. El
generador del informe debe incluir únicamente los métodos realmente calculados y sustituir
los campos entre llaves por información procedente de Intel.

## 1. Resumen de metodología

> La valoración de **{{company_name}}** se ha realizado a fecha de
> **{{valuation_date}}** utilizando la información financiera disponible de
> **{{financial_source}}**, correspondiente a los ejercicios **{{input_years}}**. El análisis
> estima por separado el valor del negocio operativo —Enterprise Value— y el valor atribuible
> a los accionistas —Equity Value— después de considerar la deuda financiera y la caja
> disponibles.
>
> Se han utilizado los métodos **{{methods_used}}**. La selección de cada método responde a
> la naturaleza de la actividad, la información disponible y la calidad de las referencias
> comparables. Los métodos sin información suficiente se han excluido de la conclusión y se
> identifican expresamente en el informe.

## 2. Descripción del DCF — incluir solo si está disponible

> El método de descuento de flujos de caja estima el valor actual de la caja que el negocio
> podría generar en el futuro. La proyección parte de la evolución histórica de los ingresos,
> el margen operativo, las amortizaciones, la inversión y las necesidades de capital
> circulante de la compañía.
>
> Los parámetros históricos se han contrastado con referencias correspondientes al
> arquetipo **{{archetype}}** y al tramo de tamaño **{{size_band}}**. Cuando han coexistido
> datos propios y referencias sectoriales, se ha dado mayor peso a la trayectoria de la
> compañía, utilizando el sector como elemento de normalización y control.
>
> Los flujos previstos se han descontado mediante un WACC de **{{wacc_percent}}**, que
> representa el coste estimado de los recursos financieros y el riesgo del negocio. Al final
> del periodo explícito de **{{projection_years}} años** se ha calculado un valor terminal con
> un crecimiento sostenible de **{{terminal_growth_percent}}**. Dado que el valor terminal
> puede representar una parte relevante del resultado, el informe presenta una matriz de
> sensibilidad frente a variaciones del WACC y del crecimiento terminal.
>
> Se muestran escenarios conservador, base y optimista. Estos escenarios no constituyen
> previsiones cerradas; permiten observar cómo cambia la valoración ante distintas
> combinaciones coherentes de crecimiento, rentabilidad y riesgo.

### Nota cuando la regla sectorial sea provisional

> Las bandas sectoriales utilizadas en esta versión son referencias provisionales de Arroba
> y todavía no representan percentiles observados sobre una cohorte completa de Iberinform.
> Por este motivo, el resultado se clasifica como **valoración orientativa o screen-grade** y
> su nivel de confianza incorpora una penalización específica.

### Nota cuando la regla esté calibrada

> Las referencias sectoriales proceden de una cohorte de **{{sample_size}} empresas** de
> Iberinform, con fecha de corte **{{calibration_cutoff}}**. Se han utilizado los percentiles
> 25, 50 y 75 después de aplicar los controles de calidad y tratamiento de extremos descritos
> en la metodología.

## 3. Descripción de cotizadas — incluir solo si está disponible

> El método de compañías cotizadas comparables contrasta la compañía con empresas que operan
> en actividades semejantes y para las que existen valoraciones observables en el mercado.
> La selección ha tenido en cuenta actividad, tamaño, crecimiento, márgenes, intensidad de
> capital, geografía y estructura financiera.
>
> Se ha aplicado el múltiplo **{{trading_multiple_name}}** de
> **{{trading_multiple_value}}x** a **{{trading_metric}}**, obteniendo una referencia de
> Enterprise Value. La mediana se ha utilizado como referencia central para reducir la
> influencia de observaciones extremas.
>
> Dado que una compañía privada presenta diferencias de liquidez, escala, acceso al capital y
> transparencia frente a una cotizada, el resultado se interpreta como referencia de mercado
> y no como precio directamente observable de la empresa analizada.

## 4. Descripción de operaciones privadas — incluir solo si está disponible

> El método de operaciones comparables analiza precios pagados en adquisiciones de compañías
> semejantes. Se han considerado **{{transactions_count}} operaciones**, realizadas entre
> **{{transactions_period}}**, atendiendo a actividad, tamaño, geografía, fecha, porcentaje
> adquirido y disponibilidad de información financiera.
>
> Se ha utilizado el múltiplo **{{transaction_multiple_name}}** con una mediana de
> **{{transaction_multiple_value}}x**. Este método puede incorporar primas de control y
> expectativas de sinergias presentes en operaciones reales. Por ello se contrasta con el
> DCF y con cotizadas antes de formular la conclusión.

### Texto mientras TTR no esté conectado

> No se ha incorporado una valoración por operaciones privadas comparables porque todavía no
> se dispone de una muestra suficiente, homogénea y trazable. Este método no ha influido en
> el rango final.

## 5. Múltiplo EV/EBITDA

> El múltiplo EV/EBITDA relaciona el valor del negocio operativo con el EBITDA normalizado.
> Se utiliza cuando la compañía presenta EBITDA positivo y existen referencias comparables
> suficientes. El EBITDA empleado corresponde a **{{ebitda_basis}}** y asciende a
> **{{ebitda_value}}**.
>
> El múltiplo aplicado es **{{ev_ebitda_multiple}}x**, dando lugar a un Enterprise Value de
> **{{enterprise_value}}** antes de considerar deuda y caja.

## 6. Múltiplo EV/Ingresos

> Ante la ausencia de un EBITDA positivo o normalizado, se ha utilizado el múltiplo
> EV/Ingresos como referencia secundaria. Este método no distingue por sí solo entre empresas
> con diferente rentabilidad, por lo que recibe una confianza inferior y debe interpretarse
> junto con los márgenes y perspectivas de la compañía.

## 7. Valor en libros

> El patrimonio neto contable se presenta como referencia patrimonial debido a la
> insuficiencia de información para aplicar métodos basados en beneficios o flujos. El valor
> en libros no refleja necesariamente la capacidad de generación futura ni el valor de los
> activos intangibles y, por ello, no debe equipararse automáticamente al valor de mercado.

## 8. Puente entre valor empresa y valor del accionista

### Cuando se conocen deuda y caja

> El Enterprise Value obtenido se ha convertido en Equity Value restando la deuda financiera
> de **{{financial_debt}}** y sumando la caja de **{{cash}}**. El ajuste neto aplicado asciende
> a **{{net_debt}}**.

### Cuando falta deuda o caja

> No se dispone de información suficiente sobre la deuda financiera y/o la caja de la compañía. En
> consecuencia, no se ha calculado un Equity Value concluyente a partir del DCF. El
> Enterprise Value puede seguir utilizándose como referencia del negocio operativo, pero el
> valor atribuible al accionista dependerá de la deuda financiera real en la fecha de
> valoración.

## 9. Conciliación y conclusión

> Los diferentes métodos ofrecen perspectivas complementarias. El DCF refleja la capacidad
> futura de generación de caja; las cotizadas reflejan la valoración actual del mercado
> público; y las operaciones privadas, cuando están disponibles, reflejan precios pagados por
> el control de empresas comparables.
>
> Considerando la calidad de los datos, la comparabilidad de las muestras y la sensibilidad
> de los principales supuestos, se estima un rango de Enterprise Value de
> **{{ev_range_low}} a {{ev_range_high}}**, con una referencia central de
> **{{ev_central}}**.
>
> El rango de Equity Value se sitúa entre **{{equity_range_low}} y
> {{equity_range_high}}**, con una referencia central de **{{equity_central}}**,
> sujeto a los ajustes de deuda, caja y demás partidas detalladas en el informe.

Si no se puede calcular Equity Value, eliminar el último párrafo y utilizar:

> La información disponible permite estimar el valor del negocio operativo, pero no permite
> concluir el valor atribuible a los accionistas hasta disponer de un detalle fiable de deuda
> financiera, caja y otros ajustes del balance.

## 10. Tabla obligatoria de métodos

| Método | Estado | Resultado central | Peso o relevancia | Calidad |
|---|---|---:|---:|---|
| DCF | {{dcf_status}} | {{dcf_value}} | {{dcf_weight}} | {{dcf_confidence}} |
| Cotizadas comparables | {{trading_status}} | {{trading_value}} | {{trading_weight}} | {{trading_confidence}} |
| Operaciones privadas | {{transactions_status}} | {{transactions_value}} | {{transactions_weight}} | {{transactions_confidence}} |
| Valor en libros | {{book_status}} | {{book_value}} | Referencia | {{book_confidence}} |

Un método no disponible debe mostrar “No aplicado” y el motivo. No debe recibir peso cero de
forma silenciosa.

## 11. Tabla obligatoria de supuestos DCF

| Parámetro | Valor | Fuente | Justificación |
|---|---:|---|---|
| Crecimiento de ingresos | {{revenue_growth}} | {{revenue_growth_source}} | {{revenue_growth_reason}} |
| Margen EBIT | {{ebit_margin}} | {{ebit_margin_source}} | {{ebit_margin_reason}} |
| Capex/ventas | {{capex_ratio}} | {{capex_source}} | {{capex_reason}} |
| Capital circulante/ventas | {{nwc_ratio}} | {{nwc_source}} | {{nwc_reason}} |
| Tipo impositivo | {{tax_rate}} | {{tax_source}} | {{tax_reason}} |
| WACC | {{wacc}} | {{wacc_source}} | {{wacc_reason}} |
| Crecimiento terminal | {{terminal_growth}} | {{terminal_growth_source}} | {{terminal_growth_reason}} |

## 12. Fuentes y fecha

> La valoración utiliza información disponible a **{{valuation_date}}**. Las cuentas
> financieras proceden de **{{financial_source}}**. Las referencias de mercado proceden de
> **{{market_sources}}** y tienen fecha **{{market_data_date}}**. Las reglas y cálculos han
> sido ejecutados por Intel, motor de inteligencia financiera de Arroba, versión
> **{{engine_version}}**, con reglas **{{ruleset_version}}**.

## 13. Limitaciones y alcance — incluir siempre

> Esta valoración constituye una estimación financiera basada en la información disponible,
> en referencias de mercado y en hipótesis consideradas razonables a la fecha del análisis.
> No representa una oferta de compra o venta, un precio garantizado, una auditoría, una due
> diligence completa, una opinión legal o fiscal ni una fairness opinion.
>
> El precio finalmente alcanzado en una transacción puede diferir por la existencia de primas
> de control, sinergias, estructura de pago, financiación, fiscalidad, garantías, competencia
> entre compradores, evolución del mercado y hechos posteriores a la fecha de valoración.
>
> Las cifras históricas dependen de la información suministrada por las fuentes identificadas.
> Arroba aplica controles de coherencia y normalización, pero no sustituye la verificación
> independiente de las cuentas ni la revisión de documentación contractual, fiscal y legal.

## 14. Explicación corta para la primera página

> **Cómo se ha calculado el valor.** Se ha estimado el valor del negocio utilizando
> **{{short_methods}}**. El análisis parte de las cuentas históricas de la compañía, contrasta
> su crecimiento y rentabilidad con referencias sectoriales y evalúa su capacidad futura de
> generar caja. El resultado se presenta como un rango porque depende de la evolución del
> negocio, del riesgo y de las condiciones de mercado. Para llegar al valor del accionista se
> ajusta el valor del negocio por deuda financiera y caja.

## 15. Explicación para lector no financiero

> La valoración responde a dos preguntas. Primero, cuánto vale la actividad de la compañía
> por la caja que puede generar y por cómo valora el mercado a negocios semejantes. Segundo,
> cuánto de ese valor corresponde realmente a los accionistas después de pagar la deuda y
> considerar la caja disponible. Se presentan varios escenarios porque el futuro no puede
> resumirse de forma fiable en una única cifra.

## 16. Reglas editoriales obligatorias

1. No afirmar que una cifra procede de Iberinform si es una semilla de Arroba.
2. No llamar transacción comparable a una referencia sin operación identificable.
3. No mostrar Equity Value como concluyente si falta deuda financiera.
4. No ocultar métodos excluidos ni el motivo.
5. No mezclar Enterprise Value y Equity Value.
6. Mostrar siempre fecha, moneda, fuente y versión.
7. Diferenciar dato histórico, supuesto, cálculo y referencia de mercado.
8. Mostrar rango y sensibilidad, no solo el punto central.
9. Identificar screen-grade de forma visible.
10. Adaptar el texto al método realmente aplicado.

## 17. Texto obligatorio para el ajuste de cotizadas a empresa privada

> La valoración parte de un múltiplo observado en compañías cotizadas comparables y lo
> adapta a las características de la compañía analizada. El informe muestra por separado
> el múltiplo público, cada ajuste aplicado y el múltiplo privado resultante. El tamaño se
> ajusta conforme a la política sectorial de Arroba. La auditoría se obtiene de Iberinform;
> la recurrencia de ingresos, la concentración de clientes y la dependencia de persona
> clave solo se consideran cuando existe evidencia explícita de due diligence. Un dato no
> disponible permanece neutral y se identifica como tal.
>
> No se aplica un descuento por falta de liquidez al Enterprise Value. Si se valora una
> participación minoritaria, cualquier descuento de liquidez deberá analizarse de forma
> separada, justificarse y aplicarse sobre el Equity Value correspondiente.
