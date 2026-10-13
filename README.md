# Mi agente de viajes (Streamlit)

Chat con un agente (Claude) + ruta + mapa, con una carpeta por viaje.

## Cómo correrlo
```bash
pip install -r requirements.txt
streamlit run app.py
```
1. Abre el menú lateral (⚙️ Ajustes), pon el **nombre** de tu agente y pega tu clave de Anthropic
   (o créala en `.streamlit/secrets.toml`, copiando `secrets.toml.example`).
2. Crea tu primera carpeta de viaje (ej. "Madrid"). Se guarda en `viajes/madrid/`.

## Pantallas
Diseño inspirado en una plantilla de viajes: encabezado con título centrado, pestañas de texto, carrusel de destacados, "Recomendados",
barra de navegación flotante abajo (Inicio · Ruta · Mapa · Chat) y pantalla de detalle con hoja blanca sobre el paisaje.

- **Descubrir**: los 51 países de `data/Countries.xlsx`, cada uno con su paisaje animado (Fuji con pétalos para Japón, torre, Alpes, castillos...).
  Filtra por *Todos / Mis países / Europa / Asia*, por zona (Europa occidental, norte, sur, este, Balcanes y Turquía, Cáucaso) o busca por nombre.
  **Ver ficha** abre transporte, tarjetas y pases (turista y residente), formas de pago y precios típicos, en moneda local
  (Japón se muestra en dólares con los yenes entre paréntesis). La ficha se consulta en la web una vez y se guarda en `viajes/_fichas/`;
  los precios que no se encuentran se marcan como aprox.
- **Ruta**: tabla de paradas (ciudad, país, fechas, hotel). Importa/descarga Excel. Lugares guardados con total de gasto.
- **Mapa**: paradas, lugares y rutas del agente; botones para abrir la ruta en Google Maps (sin API ni costo).
- **Chat**: el agente puede buscar en la web (precios, transporte, dónde comer), ver el clima, convertir moneda,
  dibujar rutas y guardar lugares/paradas/notas en tu carpeta.

## Controlar el gasto
- La API de Anthropic se cobra aparte de tu suscripción: fija un **límite mensual** en console.anthropic.com.
- Ajustes: modelo (Haiku es el más barato), búsquedas web por respuesta y por ficha de país, y memoria del chat.
- Google Maps: la app solo genera enlaces, **no usa la API de Google**, así que no hay cobro por ahí.

## "Que no se atonte"
- 🧹 Nueva conversación: vacía el chat (ruta, lugares y notas se conservan).
- 📝 Resumir y limpiar: guarda un resumen en `notas.md` y vacía el chat.
- La memoria del chat solo envía tus últimos N mensajes.

## Carpetas
```
viajes/madrid/ trip.json · ruta.csv · lugares.json · notas.md · ultima_ruta.json
```
Todo se guarda en disco local. En Streamlit Community Cloud los archivos se borran al reiniciar;
para usarla desde el celular en la nube hay que cambiar `storage.py` por una versión que guarde en Google Drive
(siguiente etapa).
