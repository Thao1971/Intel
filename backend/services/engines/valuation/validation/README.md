# Validación del motor de valoración

Esta carpeta cierra el punto 9 con una cesta estable y versionada de seis compañías españolas reales. Cada caso conserva sector, múltiplo cotizado observado a 31/12/2025, ajuste de comparabilidad privada, indicación DCF y un rango de valoración manual congelado.

La prueba exige:

- cobertura de inmobiliario, medios, industria, distribución, servicios y software;
- valor conciliado dentro del rango manual;
- desviación máxima del 0,5 % frente a la línea base de la versión;
- pesos que suman uno;
- ausencia de Equity Value cuando falta deuda;
- rechazo de rangos negativos.

La cesta es un control de regresión y coherencia. No actualiza precios ni sustituye una valoración independiente. Para promover una nueva versión del motor se debe revisar y versionar explícitamente la línea base, nunca sobrescribirla de forma silenciosa.

Ejecutar desde `backend`:

```bash
python -m services.engines.valuation.validation.validation_runner
pytest services/engines/valuation/validation -q
```
