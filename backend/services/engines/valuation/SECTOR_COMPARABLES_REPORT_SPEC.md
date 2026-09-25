# Comparables sectoriales y posicionamiento en el informe de valoración

## Objetivo

Añadir a la valoración de Arroba una lectura sectorial explicativa y reproducible. Esta capa no sustituye al DCF, a las cotizadas ni a las operaciones privadas. Ayuda a justificar los supuestos, medir la posición relativa de la compañía y explicar por qué su múltiplo puede situarse por encima o por debajo de la referencia central.

## Principio financiero

Intel mantiene separados:

- Enterprise Value: valor del negocio operativo.
- Equity Value: Enterprise Value menos deuda financiera, más caja y otros ajustes identificados.
- Referencias sectoriales: evidencia para normalizar parámetros y explicar posición relativa.
- Múltiplos de mercado: referencias de valoración observables.

No se sumarán automáticamente todos los activos y pasivos al valor operativo. Los activos y pasivos operativos ya contribuyen a la generación de flujos; incorporarlos de nuevo puede duplicar su efecto. Solo se aplicarán ajustes patrimoniales identificados y financieramente justificados.

## Cohorte sectorial

La cohorte se construye con el universo empresarial y las cuentas normalizadas. La selección debe registrar:

1. actividad o arquetipo;
2. CNAE y nivel de agregación empleado;
3. tramo de tamaño por ingresos y, cuando resulte útil, empleados;
4. geografía;
5. ejercicio y fecha de corte;
6. población inicial y observaciones válidas;
7. duplicados, ejercicios anómalos y extremos excluidos;
8. versión del snapshot.

La salida publica P25, mediana y P75 solo cuando la muestra supera los mínimos de calidad. Una cohorte insuficiente amplía su nivel de agregación de forma trazable.

## Indicadores comparativos

### Crecimiento y escala

- ingresos;
- crecimiento interanual;
- CAGR de ingresos;
- cuota aproximada dentro de la cohorte cuando la cobertura lo permita;
- percentil y posición por ingresos.

### Rentabilidad

- margen EBITDA;
- margen EBIT;
- margen antes de impuestos;
- ROIC o retorno sobre capital empleado;
- conversión de EBITDA a caja cuando exista información suficiente.

### Solvencia y estructura financiera

- deuda financiera neta / EBITDA;
- patrimonio neto / activos;
- liquidez corriente;
- cobertura de intereses;
- capital circulante / ingresos.

### Productividad

- ingresos por empleado;
- EBITDA por empleado;
- coste medio de personal;
- valor añadido por empleado, cuando la definición sea homogénea.

### Inversión

- capex / ingresos;
- activos fijos / ingresos;
- intensidad de capital.

## Posición relativa

Para cada indicador Intel entregará:

- valor de la empresa;
- P25, mediana y P75 de la cohorte;
- percentil de la empresa;
- tamaño de muestra;
- ejercicio y fecha de corte;
- interpretación favorable, neutral o a validar;
- dirección económica del indicador, porque un percentil alto no siempre es positivo.

Cuando existan varios ejercicios, se mostrará la evolución del percentil y no solo la posición actual.

## Grupos de pares

No habrá una única lista universal. Intel podrá formar grupos de pares por finalidad:

- pares por escala: ingresos semejantes;
- pares por rentabilidad: EBITDA o margen semejante;
- pares por productividad: empleados e ingresos por empleado;
- pares de valoración: actividad, tamaño, crecimiento y margen comparables.

Cada tabla indicará el criterio de selección. Los nombres de proveedores de datos no aparecerán en el documento entregado; sí quedarán registrados internamente en la trazabilidad.

## Impacto en la valoración

La capa sectorial tendrá tres usos:

1. contrastar los supuestos del DCF;
2. justificar ajustes al múltiplo observado en cotizadas;
3. explicar los factores que sitúan a la empresa por encima o por debajo de la mediana.

No generará por sí sola un valor mediante un múltiplo fijo. El impacto deberá ser trazable y estar acotado por las reglas sectoriales.

## Nuevas páginas del PDF

### Posicionamiento sectorial

Tabla empresa frente a P25, mediana y P75 para crecimiento, margen, retorno, apalancamiento y productividad. Se acompañará de una narrativa automática sobre fortalezas y aspectos a validar.

### Evolución de la posición

Gráfico de percentiles por ejercicio para ingresos, rentabilidad y productividad. Permitirá distinguir una mejora puntual de una tendencia sostenida.

### Grupo de pares

Tabla de compañías semejantes con criterio de selección, ejercicio, ingresos, margen y métrica relevante. Las exclusiones y la fecha de la muestra quedarán disponibles en el anexo de trazabilidad.

### Puente del múltiplo

Gráfico desde el múltiplo central de cotizadas hasta el múltiplo privado aplicado, mostrando por separado los ajustes por tamaño, crecimiento, margen, recurrencia y riesgos acreditados. Los datos ausentes permanecerán neutrales.

## Contrato Intel-Beta propuesto

```json
{
  "sector_positioning": {
    "cohort": {
      "label": "string",
      "cnae_scope": "string",
      "size_band": "string",
      "geography": "string",
      "as_of": "date",
      "sample_size": 0,
      "snapshot_version": "string"
    },
    "metrics": [
      {
        "metric": "ebitda_margin",
        "company_value": 0.0,
        "p25": 0.0,
        "median": 0.0,
        "p75": 0.0,
        "percentile": 0,
        "direction": "higher_is_better",
        "interpretation": "string"
      }
    ],
    "rankings": [],
    "peer_groups": [],
    "multiple_bridge": []
  }
}
```

Beta se limita a representar esta estructura. La selección de cohorte, el cálculo de percentiles, las clasificaciones, los ajustes y la narrativa pertenecen a Intel.

## Controles obligatorios

- No publicar rankings con cobertura insuficiente.
- No comparar ejercicios distintos sin indicarlo.
- No presentar cuota de mercado si el universo no ofrece cobertura razonablemente completa.
- No confundir percentil con posición ordinal.
- No usar la media cuando los extremos distorsionen la distribución; la referencia central será la mediana.
- No convertir una referencia sectorial en un múltiplo de valoración sin explicar el puente.
- Conservar muestra, exclusiones, fecha y versión para reproducibilidad.
