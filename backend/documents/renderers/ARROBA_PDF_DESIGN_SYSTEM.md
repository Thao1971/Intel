# Sistema visual de Arroba para informes PDF

Este documento fija el sistema visual que deben utilizar los informes financieros generados por Intel. La referencia funcional es el sistema de diseño de Arroba aplicado a la valoración avanzada.

## Tipografía

- Interfaz, títulos, encabezados, texto y explicaciones: Space Grotesk.
- Cifras, importes, porcentajes, múltiplos, códigos y numeración: JetBrains Mono.
- Esta regla sigue la referencia canónica `arroba-design-system.html`: Space Grotesk es la única fuente de interfaz.
- Los archivos tipográficos se incluyen en `backend/documents/renderers/assets/fonts` y quedan embebidos en el PDF.

## Colores

| Token | Valor | Uso |
|---|---|---|
| Fondo | `#FAFAF8` | Fondo general de páginas |
| Superficie | `#FFFFFF` | Tablas y tarjetas |
| Superficie secundaria | `#F4F4F0` | Filas alternas y bloques KPI |
| Borde | `#E8E8E2` | Divisiones suaves |
| Borde fuerte | `#D4D4CC` | Separadores destacados |
| Texto | `#0C0C0E` | Titulares y valores |
| Texto secundario | `#636360` | Narrativa |
| Texto sutil | `#ADADAA` | Metadatos y notas |
| Rojo Arroba | `#E8001D` | Marca, secciones y valor central |
| Verde | `#1A8A4A` | Factores favorables |
| Ámbar | `#D97708` | Riesgos y cautelas |
| Azul | `#2164E3` | Información y series de mercado |
| Oscuro secundario | `#20202A` | Portada y superficies oscuras |

## Jerarquía

- Portada oscura con franja roja, wordmark Arroba, gran cifra central y monograma gráfico.
- Cada sección comienza con número rojo y título en Space Grotesk.
- El encabezado interior muestra wordmark, tipo de informe y compañía.
- Las cifras usan tipografía monoespaciada para facilitar comparación vertical.
- Las tablas emplean encabezado oscuro, superficie blanca y filas alternas en superficie secundaria.
- Los colores verde, ámbar y azul tienen significado financiero y no se usan como decoración arbitraria.

## Principios

1. Priorizar lectura financiera y jerarquía sobre ornamentación.
2. Mantener fondos cálidos y bordes de bajo contraste.
3. Reservar el rojo para marca, navegación visual y conclusiones centrales.
4. No introducir nombres de proveedores en documentos entregables.
5. No alterar una cifra para mejorar la composición.
6. Mantener el diseño reproducible mediante el generador, sin edición manual posterior.


## Reglas de formato financiero

- Moneda: `X.XXX M€`; miles con punto y decimales con coma.
- Fechas: `DD/MM/AAAA`.
- Valores ausentes: guion largo.
- Rojo Arroba reservado para marca, navegación y contenido generado; no comunica por sí solo un peligro.
- Verde para crecimiento o lectura favorable; ámbar para cautela; azul para información y referencias de mercado.
- Escala de espaciado: 4, 8, 12, 16, 20, 24, 28 y 32.
- Radios equivalentes del producto: 5 para badges, 12 para KPI y 14 para tarjetas; en PDF se aproximan con geometría compatible con ReportLab.
