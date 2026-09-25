# Runbook de calibración sectorial con Iberinform

## 1. Objetivo

Sustituir las semillas provisionales por distribuciones observadas de empresas españolas,
con reproducibilidad, control de calidad y trazabilidad.

## 2. Unidad de cohorte

~~~text
arquetipo × división o grupo CNAE × tamaño × fecha de corte
~~~

Fallback:

1. Grupo CNAE + tamaño + España.
2. División CNAE + tamaño + España.
3. División CNAE + España.
4. Arquetipo + tamaño + España.
5. Arquetipo + España.
6. Referencia europea cotizada.
7. Semilla general de Arroba.

Cada fallback queda registrado y reduce la confianza.

## 3. Muestra mínima propuesta

| Uso | Empresas |
|---|---:|
| Mediana orientativa | 20 |
| P25/P75 publicados | 40 |
| Segmentación adicional | 80 |
| Alta confianza | 150 |

Estos umbrales se validarán estudiando estabilidad interanual y dispersión.

## 4. Selección

Incluir empresas con CNAE resoluble, ejercicio y moneda identificados, ingresos positivos,
cuentas dentro de ventana y campos necesarios para cada métrica.

Excluir o separar cuentas duplicadas, periodos anómalos no anualizados, moneda no
normalizada, sociedades inactivas, holdings, financieras dentro del FCFF industrial,
errores no resolubles y denominadores nulos. Un mal resultado económico válido no es motivo
de exclusión.

## 5. Normalización

1. Homogeneizar moneda.
2. Anualizar solo con regla explícita.
3. Normalizar signos de amortización y capex.
4. Elegir cuentas individuales o consolidadas conforme a política.
5. No mezclar bases en una misma serie.
6. Calcular por empresa y ejercicio antes de agregar.
7. Obtener una mediana temporal por empresa para que todas pesen una vez.

## 6. Métricas

~~~text
crecimiento = CAGR de ingresos
margen EBIT = EBIT / ingresos
amortización / ventas = abs(amortización) / ingresos
capex / ventas = abs(capex) / ingresos
NWC operativo / ventas = (clientes + inventarios - proveedores) / ingresos
~~~

Si falta NWC operativo se calcula aparte la aproximación activo corriente menos pasivo
corriente. Ambas definiciones no se mezclan en un mismo percentil.

## 7. Extremos

1. Validar datos y signos.
2. Inspeccionar distribución.
3. Winsorizar por métrica dentro de cohorte.
4. Empezar con P5/P95.
5. Conservar original y ajustado.
6. Publicar cantidad y porcentaje afectados.

No se elimina un extremo solo para reducir dispersión.

## 8. Estadísticos

Para cada parámetro: P25, mediana, P75, empresas, observaciones, fechas, dispersión,
porcentaje winsorizado, definición, fuente, fecha de cálculo y versión del pipeline.

## 9. WACC

1. Seleccionar comparables cotizados por arquetipo.
2. Obtener beta, capitalización, deuda, caja y coste de deuda.
3. Desapalancar betas.
4. Calcular beta robusta sectorial.
5. Reapalancar con estructura objetivo.
6. Incorporar tipo sin riesgo y prima de mercado fechados.
7. Estimar coste de deuda y efecto fiscal.
8. Aplicar ajuste de tamaño explícito.
9. Evitar duplicar riesgos ya incluidos en escenarios.
10. Guardar fuentes y comparables incluidos y excluidos.

## 10. Crecimiento terminal

Debe ser menor que WACC, compatible con madurez, geografía y moneda, y no prolongar
crecimientos históricos extraordinarios.

## 11. Validación antes de publicar

1. Comparar con la versión anterior.
2. Revalorar una cesta estable.
3. Investigar cambios materiales.
4. Verificar que mayor WACC reduce valor.
5. Verificar que mayor g aumenta valor cuando WACC es mayor que g.
6. Revisar concentración del valor terminal.
7. Medir cobertura por CNAE y tamaño.
8. Revisar una muestra de cada arquetipo.
9. Ejecutar regresión automatizada.
10. Obtener aprobación de negocio.

## 12. Versionado

Formato recomendado: sector-rules-AAAA-MM-DD-vN.

Cada snapshot almacena versión, fechas, arquetipo, CNAE, tamaño, parámetros, muestra,
definición, población inicial y final, exclusiones, fuente y versión del pipeline. Las
versiones publicadas son inmutables.

## 13. Promoción

~~~text
provisional_policy_seed
→ candidate_iberinform
→ reviewed_iberinform
→ calibrated_iberinform
~~~

Solo calibrated_iberinform puede elevar la preparación más allá de screen_grade.

## 14. Cadencia

- Iberinform: trimestral o después de una carga material.
- WACC y mercado: mensual, o antes si cambia materialmente.
- CNAE–arquetipo: al incorporar actividades.
- Revisión integral: anual.
- Hotfix: nueva versión y nota de impacto.

## 15. Entregables por ejecución

- Snapshot versionado.
- Cobertura.
- Exclusiones.
- Comparación con versión anterior.
- Pruebas de regresión.
- Valoraciones antes/después.
- Registro de aprobación.


## 16. Implementación operativa

El pipeline está implementado en calibration.py y calibration_job.py. La entrada procede de
master_companies y norm_financials. Se procesa en lotes configurables para evitar cargar el
universo completo en memoria.

Por cada empresa se calcula primero una única observación temporal por métrica. Después se
agrega a cuatro niveles cuando resultan aplicables:

1. Arquetipo y tamaño.
2. Arquetipo sin tamaño.
3. División CNAE y tamaño.
4. División CNAE sin tamaño.

La muestra por métrica es determinística: la selección depende de un hash de CIF y métrica,
por lo que el mismo universo y fecha producen el mismo resultado aunque cambie el orden de
lectura. sample_size conserva el total de observaciones válidas; sampled_observations indica
cuántas se usaron para los percentiles.

### Ejecución segura

La ejecución predeterminada es una previsualización de solo lectura. El argumento --publish
crea candidatos inmutables, pero no los activa. La promoción a reviewed_iberinform y
calibrated_iberinform requerirá un proceso separado con revisión de negocio.

Antes de una ejecución completa se debe realizar:

1. Preview de 10.000 empresas.
2. Revisión de cobertura y exclusiones.
3. Revisión de distribuciones por arquetipo.
4. Ejecución completa sin publish.
5. Comparación frente a semillas.
6. Publicación de candidatos.
7. Revisión y aprobación.
8. Activación mediante una versión posterior y explícita.

## 17. Revisión, activación y consumo

Una ejecución publicada continúa siendo candidata y no afecta a ninguna valoración. La
promoción exige dos comandos separados y un aprobador identificable:

~~~bash
python -m scripts.promote_valuation_calibration RUN_ID review \
  --approver "Nombre" --notes "Revisión de cobertura y distribuciones"
python -m scripts.promote_valuation_calibration RUN_ID activate \
  --approver "Nombre" --ruleset-version sector-rules-AAAA-MM-DD-v1
~~~

La activación solo incorpora cohortes con P25, mediana y P75 publicables. La versión anterior
se conserva como inactiva y nunca se modifica. El resolver aplica este orden:

1. división CNAE y tamaño;
2. división CNAE sin tamaño;
3. arquetipo y tamaño;
4. arquetipo sin tamaño;
5. semilla de política por parámetro no calibrado.

Cada parámetro incluye cohorte, tamaño de muestra, versión y fuente. WACC y crecimiento
terminal no se obtienen de las cuentas Iberinform: continúan en sus motores de mercado y
política correspondientes. Las valoraciones nuevas consultan la versión activa; una
calibración parcial conserva explícitamente las semillas de los parámetros sin muestra.
