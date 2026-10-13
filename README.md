# My Travel Agent (Streamlit)

Chat with an agent + route + map, with one folder per trip.

## Screens
Design inspired by a travel app template: centered title header, text tabs, featured carousel, "Recomendados" (Recommended) grid,
a floating bottom navigation bar (Inicio · Ruta · Mapa · Chat) and a detail screen with a white sheet over the landscape.

- **Discover (Descubrir)**: the 51 countries in `data/Countries.xlsx`, each with its own animated landscape (Mount Fuji with petals for Japan, tower, Alps, castles...).
  Filter by *All / My countries / Europe / Asia*, by zone (Western Europe, Northern, Southern, Eastern, Balkans and Turkey, Caucasus) or search by name.
  **Ver ficha** (View card) opens transport, cards and passes (tourist and resident), payment methods and typical prices, in local currency
  (Japan is shown in US dollars with yen in parentheses). The country card is researched on the web once and saved in `viajes/_fichas/`;
  prices that cannot be found are marked as approximate.
- **Route (Ruta)**: table of stops (city, country, dates, hotel). Import/download Excel. Saved places with total spending.
- **Map (Mapa)**: stops, places and the agent's routes; buttons to open the route in Google Maps (no API, no cost).
- **Chat**: the agent can search the web (prices, transport, where to eat), check the weather, convert currency,
  draw routes and save places/stops/notes in your folder.

## Controlling costs
- The Anthropic API is billed separately from your subscription: set a **monthly spend limit** at console.anthropic.com.
- Settings: model (Haiku is the cheapest), web searches per answer and per country card, and chat memory.
- Google Maps: the app only generates links and **does not use the Google API**, so there are no charges from that side.

## Keeping the chat sharp
-  New conversation: clears the chat (route, places and notes are kept).
- Summarize and clear): saves a summary in `notas.md` and clears the chat.
- Chat memory only sends your last N messages.

## Folders
Everything is saved to local disk. On Streamlit Community Cloud, files are deleted on restart;
to use it from your phone in the cloud, `storage.py` has to be replaced with a version that saves to Google Drive
(next stage).
