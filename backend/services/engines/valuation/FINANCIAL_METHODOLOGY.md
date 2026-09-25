# Metodología financiera de valoración de compañías

## 1. Qué se está valorando

La valoración distingue dos conceptos:

- **Valor de empresa o Enterprise Value:** valor del negocio operativo con independencia de
  cómo esté financiado.
- **Valor de los fondos propios o Equity Value:** importe atribuible a los accionistas una vez
  considerada la deuda financiera neta y, cuando proceda, otros ajustes del balance.

La relación básica es:

~~~text
Valor de los fondos propios
= Valor de empresa
- Deuda financiera
+ Caja disponible
± Otros ajustes
~~~

Esta diferencia es esencial. Dos empresas con el mismo negocio operativo pueden tener un
valor muy distinto para el accionista si presentan niveles de endeudamiento diferentes.

## 2. Principio general

Arroba no pretende obtener el valor de una compañía mediante una única fórmula. Se utilizan
los métodos que permiten los datos disponibles y se comparan sus resultados.

Los tres enfoques previstos para la valoración y el screening financiero son:

1. Método de descuento de flujos de caja.
2. Múltiplos de compañías cotizadas comparables.
3. Múltiplos de operaciones privadas comparables.

Mientras las operaciones privadas de TTR no estén disponibles, la valoración se apoya en
DCF, comparables cotizados disponibles y referencias sectoriales identificadas como
provisionales. Si un método no dispone de información suficiente, se excluye y se explica.

## 3. Descuento de flujos de caja

### Qué responde

El DCF estima cuánto vale hoy la capacidad futura de la empresa para generar caja. Su lógica
es que un comprador adquiere los flujos futuros del negocio, no únicamente sus resultados
históricos.

### Punto de partida

Se emplean las cuentas históricas procedentes de Iberinform para analizar:

- evolución de ingresos;
- rentabilidad operativa;
- amortizaciones;
- inversión;
- necesidades de capital circulante;
- deuda financiera;
- caja.

El modelo parte de magnitudes operativas normalizadas. Una partida extraordinaria no debería
convertirse automáticamente en una expectativa permanente.

### Proyección de ingresos

La evolución histórica constituye el primer indicador, pero no se extrapola sin límites.
Se combina con el comportamiento razonable del sector, el tamaño de la compañía y su grado
de madurez.

Una empresa puede crecer más que su sector durante un periodo, pero el modelo evita asumir
que esa diferencia continuará indefinidamente.

### Margen operativo

El margen EBIT representa el resultado generado por la actividad antes de intereses e
impuestos. Se utiliza porque permite valorar el negocio independientemente de su estructura
de financiación.

Se considera:

- margen histórico de la compañía;
- estabilidad del margen;
- posición frente al sector;
- posibles ejercicios extraordinarios;
- margen sostenible a medio plazo.

### Impuestos

Se calcula el impuesto operativo sobre el EBIT. El modelo utiliza un tipo normalizado para
aproximar la carga fiscal sostenible. El tipo efectivo de un ejercicio puede estar
distorsionado por pérdidas, deducciones o efectos no recurrentes.

### Inversión y amortización

La amortización es un gasto contable sin salida de caja en el ejercicio, por lo que se suma
al resultado operativo después de impuestos.

El capex representa la inversión necesaria para mantener y desarrollar los activos. Se
resta porque supone una salida real de caja. Cuando no se puede separar inversión de
mantenimiento y crecimiento, se utiliza la mejor referencia histórica y sectorial
disponible y se identifica esta limitación.

### Capital circulante

El crecimiento suele requerir financiar clientes, inventarios y otras partidas operativas.
El aumento del capital circulante consume caja; una reducción la libera.

La referencia preferida es:

~~~text
Clientes + Inventarios - Proveedores
~~~

Si no están todos los componentes, puede utilizarse como aproximación el activo corriente
menos el pasivo corriente. El informe debe indicar cuál de las dos definiciones se ha usado.

### Flujo de caja libre

El flujo de caja libre para la empresa se calcula como:

~~~text
EBIT después de impuestos
+ Amortizaciones
- Inversión
- Incremento del capital circulante
= Flujo de caja libre para la empresa
~~~

Es la caja generada por el negocio disponible para remunerar conjuntamente a acreedores y
accionistas.

### Tasa de descuento

Los flujos futuros valen menos que la misma cantidad disponible hoy. Se descuentan mediante
el WACC, que representa el coste medio ponderado de los recursos financieros de la empresa.

El WACC combina:

- coste de los fondos propios;
- coste de la deuda;
- proporción razonable de deuda y capital;
- efecto fiscal de la deuda;
- riesgo del sector;
- tamaño y características de la empresa.

Mientras no exista una calibración completa con datos de mercado y comparables, el WACC
sectorial se identifica como referencia provisional.

### Valor terminal

No resulta razonable proyectar cada ejercicio indefinidamente. Tras el periodo explícito se
calcula un valor terminal suponiendo que la empresa alcanza una situación estable.

El crecimiento terminal debe ser inferior al WACC y compatible con una empresa madura y con
la economía en la que opera. Una parte elevada del valor total puede proceder del valor
terminal; por eso se muestra una sensibilidad específica.

### Escenarios

Se calculan tres escenarios:

- **Conservador:** menor crecimiento y margen, y mayor tasa de descuento.
- **Base:** hipótesis centrales.
- **Optimista:** mejor evolución operativa y menor percepción de riesgo.

No representan una predicción exacta. Muestran cómo cambia el valor bajo combinaciones
coherentes de hipótesis.

## 4. Compañías cotizadas comparables

### Qué responde

Este método estima cuánto pagaría el mercado por una empresa si se valorase de forma similar
a compañías cotizadas con un negocio comparable.

Los múltiplos principales son:

- EV/EBITDA.
- EV/EBIT.
- EV/Ingresos.
- Precio/beneficio cuando resulte adecuado.
- Precio/valor contable para determinados sectores.

### Selección de comparables

La comparabilidad no se determina solo por el CNAE. Deben considerarse:

- actividad y modelo de ingresos;
- geografía;
- tamaño;
- crecimiento;
- márgenes;
- intensidad de capital;
- recurrencia;
- endeudamiento;
- exposición cíclica.

La mediana suele ser más representativa que la media porque reduce la influencia de valores
extremos.

### Ajuste por condición privada

Una empresa no cotizada no tiene la misma liquidez, acceso a capital, escala ni transparencia
que una cotizada. La comparación debe interpretarse teniendo en cuenta estas diferencias.
Cualquier descuento o ajuste debe mostrarse de forma separada y justificada.

### Aplicación

~~~text
Valor de empresa = Magnitud financiera × Múltiplo seleccionado
~~~

Por ejemplo:

~~~text
Valor de empresa = EBITDA normalizado × EV/EBITDA
~~~

Después se realiza el puente de deuda y caja para obtener el valor de los fondos propios.

## 5. Operaciones privadas comparables

Este método utilizará transacciones reales en las que se hayan adquirido compañías
semejantes. Refleja precios pagados por el control, condiciones de mercado y posibles
sinergias.

Para cada operación deben conocerse, en la medida de lo posible:

- fecha;
- comprador y objetivo;
- porcentaje adquirido;
- valor empresa o valor de la operación;
- EBITDA, EBIT o ingresos de referencia;
- sector, geografía y tamaño;
- condiciones o circunstancias especiales.

Los múltiplos históricos deben ajustarse por antigüedad, ciclo de mercado y calidad de la
información. No se utilizará este método hasta disponer de una muestra suficiente y
trazable, previsiblemente mediante TTR.

## 6. Valor en libros

El patrimonio neto contable puede utilizarse como referencia cuando faltan beneficios o
ingresos adecuados para otros métodos. No representa necesariamente el valor económico del
negocio, porque no recoge bien intangibles, capacidad futura de generación de caja o valor
de mercado de los activos.

En empresas intensivas en activos puede ser un contraste útil. En servicios, tecnología,
medios o negocios con intangibles suele tener menor relevancia.

## 7. Elección del método principal

La selección depende del tipo de compañía:

| Situación | Método con mayor relevancia |
|---|---|
| Negocio estable con previsiones razonables | DCF |
| EBITDA positivo y comparables sólidos | EV/EBITDA |
| Negocio de crecimiento sin EBITDA normalizado | EV/Ingresos, con cautela |
| Empresa intensiva en activos | NAV o valor patrimonial ajustado |
| Inmobiliaria patrimonialista | NAV y capitalización de rentas |
| Promotora | Valor por proyectos y suelo |
| Concesión | DCF por activo y vencimiento |
| Banco o aseguradora | Métodos de capital propio |
| Holding | Suma de partes |
| Empresa con pérdidas estructurales | Escenarios de recuperación y financiación |

## 8. Conciliación de resultados

Los métodos no tienen por qué producir el mismo valor. Cada uno responde a una pregunta
distinta:

- DCF: valor de la caja futura bajo determinadas hipótesis.
- Cotizadas: valoración observada actualmente en mercados públicos.
- Transacciones: precio pagado en operaciones reales.
- Valor contable: referencia patrimonial.

La conclusión debe explicar la dispersión, no ocultarla. La ponderación depende de calidad,
actualidad, comparabilidad y suficiencia de la información.

No se debe aplicar una media mecánica si uno de los métodos tiene datos débiles. Un método
provisional puede mostrarse como contraste sin influir en la conclusión central.

## 9. Rango de valoración

La valoración se presenta como rango porque depende de variables futuras y de mercado. El
punto central corresponde al escenario base o a la referencia considerada más representativa.

El extremo inferior recoge un desarrollo más prudente o múltiplos inferiores. El superior
refleja una ejecución favorable dentro de parámetros razonables.

El rango no es un intervalo estadístico ni una garantía sobre el precio de una transacción.

## 10. Parámetros sectoriales

Los parámetros sectoriales evitan proyectar una compañía de forma aislada. Sirven para
contrastar crecimiento, márgenes, inversión, circulante, riesgo y estructura financiera.

La empresa sigue teniendo prioridad. En la versión actual:

~~~text
70% histórico de la empresa + 30% mediana sectorial
~~~

El resultado se mantiene dentro de P25 y P75 del sector. Mientras los percentiles no hayan
sido calculados sobre cohortes reales de Iberinform, se identifican como semillas
provisionales y reducen la confianza.

## 11. Calidad y confianza

El nivel de confianza considera:

- ejercicios disponibles;
- deuda y caja conocidas;
- procedencia de los supuestos;
- tamaño de las muestras comparables;
- antigüedad de la información;
- uso de referencias provisionales;
- coherencia entre métodos.

La confianza mide la solidez de la evidencia utilizada, no la probabilidad matemática de
alcanzar el valor estimado.

## 12. Interpretación correcta

La valoración es una estimación financiera basada en información disponible y supuestos
razonados a una fecha determinada. No representa:

- una oferta de compra o venta;
- un precio garantizado;
- una auditoría;
- una due diligence completa;
- una opinión legal o fiscal;
- una fairness opinion;
- una certificación independiente del valor.

El valor final de una operación puede variar por control, sinergias, estructura, fiscalidad,
financiación, competencia entre compradores, garantías y condiciones contractuales.
