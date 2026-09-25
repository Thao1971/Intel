# Contrato de valoración avanzada Intel–Beta

**Motor:** `arroba-advanced-valuation-v1`  
**Cálculo:** `POST /api/v1/valuations/advanced/calculate`  
**Resultado:** `GET /api/v1/valuations/advanced/{run_id}`  
**Informe:** `GET /api/v1/valuations/advanced/{run_id}/pdf`

Intel es el único calculador. Beta captura y presenta datos, ofrece una
previsualización reactiva y envía las entradas revisadas. El resultado definitivo,
los escenarios, la sensibilidad, la conciliación y el PDF proceden de Intel.

## Entradas

- Identificador, objetivo, fecha y perímetro.
- Correcciones a las cuentas mediante rutas `año.bloque.campo`.
- Ajustes de normalización del EBITDA con concepto, importe, sentido y evidencia.
- Factores de calidad ya soportados y contexto complementario.
- Hipótesis de proyección a cinco años.
- Componentes editables del WACC.
- Pesos propuestos por método.
- Deuda financiera y caja para el puente EV–Equity.

El motor reaplica el múltiplo de mercado a los ingresos o EBITDA revisados,
recalcula el DCF, normaliza los pesos entre los métodos disponibles y genera el
paquete canónico `intel-beta-valuation-v1`. Los métodos sin evidencia se excluyen.

## Persistencia y acceso

Cada ejecución se guarda en `valuation_advanced_runs` con un `run_id` aleatorio,
la petición completa, el paquete resultante, fecha, empresa y propietario. La
pasarela autenticada debe eliminar cualquier cabecera `X-Arroba-User-Id` del
navegador y crearla desde la sesión validada. Intel compara ese propietario tanto
para leer el resultado como para descargar el PDF y responde 404 si no coincide.

La clave de servicio permanece en el servidor de la pasarela. No se incluye en
JavaScript, ZIP, variables `NEXT_PUBLIC_*` ni registros.
