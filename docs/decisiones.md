# Decisiones técnicas

Registro breve de decisiones de diseño y su motivo.

## 001 · REST Admin API para la fase 1 (2026-10-13)

- **Decisión:** usar la REST Admin API (`/admin/api/2026-10/orders.json`).
- **Motivo:** requisito inicial del proyecto; sigue funcionando para apps propias.
- **Consecuencia:** REST es *legacy* desde 2024-10. Se aisló en `shopify/client.py` y
  `shopify/orders.py` para poder migrar a GraphQL sin tocar el resto del pipeline.

## 002 · Autenticación con Client Credentials (2026-10-13)

- **Decisión:** soportar Client Credentials (Dev Dashboard) como modo principal y el
  token estático `shpat_` como alternativa.
- **Motivo:** desde el 1-ene-2026 Shopify no permite crear custom apps legacy. Los tokens
  de Client Credentials expiran en ~24 h, lo que reduce el impacto de una filtración.

## 003 · Zona raw en JSON Lines + manifiesto (2026-10-13)

- **Decisión:** guardar los pedidos sin transformar, uno por línea, con un manifiesto por corrida.
- **Motivo:** conservar la respuesta original permite reprocesar las fases 2 y 3 sin volver
  a llamar a Shopify. El manifiesto documenta la ventana y el conteo esperado.
