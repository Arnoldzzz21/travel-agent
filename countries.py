"""Catálogo de países: lee data/Countries.xlsx y lo enriquece (nombre en español, bandera, región, emoji)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

EXCEL_PATH = Path(__file__).parent / "data" / "Countries.xlsx"

# nombre en inglés (como en el Excel) -> (nombre ES, ISO2, región, emoji flotante)
_INFO = {
    "Japan": ("Japón", "JP", "Asia", "🗻"),
    "Albania": ("Albania", "AL", "Europa", "🏔️"),
    "Andorra": ("Andorra", "AD", "Europa", "⛷️"),
    "Armenia": ("Armenia", "AM", "Asia", "🏔️"),
    "Austria": ("Austria", "AT", "Europa", "🎻"),
    "Azerbaijan": ("Azerbaiyán", "AZ", "Asia", "🔥"),
    "Belarus": ("Bielorrusia", "BY", "Europa", "🌲"),
    "Belgium": ("Bélgica", "BE", "Europa", "🧇"),
    "Bosnia and Herzegovina": ("Bosnia y Herzegovina", "BA", "Europa", "🌉"),
    "Bulgaria": ("Bulgaria", "BG", "Europa", "🌹"),
    "Croatia": ("Croacia", "HR", "Europa", "🏝️"),
    "Cyprus": ("Chipre", "CY", "Europa", "🏛️"),
    "Czech Republic": ("Chequia", "CZ", "Europa", "🏰"),
    "Denmark": ("Dinamarca", "DK", "Europa", "🧜"),
    "Estonia": ("Estonia", "EE", "Europa", "🏰"),
    "Finland": ("Finlandia", "FI", "Europa", "🌌"),
    "France": ("Francia", "FR", "Europa", "🗼"),
    "Georgia (country)": ("Georgia", "GE", "Asia", "🍷"),
    "Germany": ("Alemania", "DE", "Europa", "🥨"),
    "Greece": ("Grecia", "GR", "Europa", "🏛️"),
    "Hungary": ("Hungría", "HU", "Europa", "🌉"),
    "Iceland": ("Islandia", "IS", "Europa", "🌋"),
    "Ireland": ("Irlanda", "IE", "Europa", "☘️"),
    "Italy": ("Italia", "IT", "Europa", "🍕"),
    "Kazakhstan": ("Kazajistán", "KZ", "Asia", "🦅"),
    "Latvia": ("Letonia", "LV", "Europa", "🏰"),
    "Liechtenstein": ("Liechtenstein", "LI", "Europa", "🏔️"),
    "Lithuania": ("Lituania", "LT", "Europa", "🏰"),
    "Luxembourg": ("Luxemburgo", "LU", "Europa", "🏰"),
    "Malta": ("Malta", "MT", "Europa", "⛵"),
    "Moldova": ("Moldavia", "MD", "Europa", "🍇"),
    "Monaco": ("Mónaco", "MC", "Europa", "🏎️"),
    "Montenegro": ("Montenegro", "ME", "Europa", "⛰️"),
    "Netherlands": ("Países Bajos", "NL", "Europa", "🌷"),
    "North Macedonia": ("Macedonia del Norte", "MK", "Europa", "🏔️"),
    "Norway": ("Noruega", "NO", "Europa", "🌌"),
    "Poland": ("Polonia", "PL", "Europa", "🏰"),
    "Portugal": ("Portugal", "PT", "Europa", "🚋"),
    "Romania": ("Rumania", "RO", "Europa", "🏰"),
    "Russia": ("Rusia", "RU", "Europa", "❄️"),
    "San Marino": ("San Marino", "SM", "Europa", "🏰"),
    "Serbia": ("Serbia", "RS", "Europa", "🏰"),
    "Slovakia": ("Eslovaquia", "SK", "Europa", "🏰"),
    "Slovenia": ("Eslovenia", "SI", "Europa", "🌉"),
    "Spain": ("España", "ES", "Europa", "💃"),
    "Sweden": ("Suecia", "SE", "Europa", "🦌"),
    "Switzerland": ("Suiza", "CH", "Europa", "🧀"),
    "Turkey": ("Turquía", "TR", "Europa", "🎈"),
    "Ukraine": ("Ucrania", "UA", "Europa", "🌻"),
    "United Kingdom": ("Reino Unido", "GB", "Europa", "🎡"),
    "Vatican City": ("Ciudad del Vaticano", "VA", "Europa", "⛪"),
}


SUBREGIONS = {
    "Europa occidental": ["AT", "BE", "FR", "DE", "LI", "LU", "MC", "NL", "CH", "IE", "GB"],
    "Europa del norte": ["DK", "EE", "FI", "IS", "LV", "LT", "NO", "SE"],
    "Europa del sur": ["AD", "ES", "IT", "MT", "PT", "SM", "VA", "GR", "CY"],
    "Balcanes y Turquía": ["AL", "BA", "BG", "HR", "ME", "MK", "RS", "SI", "TR"],
    "Europa del este": ["BY", "CZ", "HU", "MD", "PL", "RO", "RU", "SK", "UA"],
    "Cáucaso y Asia central": ["AM", "AZ", "GE", "KZ"],
    "Japón": ["JP"],
}
_SUB_OF = {iso: name for name, isos in SUBREGIONS.items() for iso in isos}

# Moneda local (referencia para el agente; él debe verificar la vigente).
CURRENCY = {
    "JP": "JPY", "AL": "ALL", "AD": "EUR", "AM": "AMD", "AT": "EUR", "AZ": "AZN", "BY": "BYN", "BE": "EUR",
    "BA": "BAM", "BG": "EUR", "HR": "EUR", "CY": "EUR", "CZ": "CZK", "DK": "DKK", "EE": "EUR", "FI": "EUR",
    "FR": "EUR", "GE": "GEL", "DE": "EUR", "GR": "EUR", "HU": "HUF", "IS": "ISK", "IE": "EUR", "IT": "EUR",
    "KZ": "KZT", "LV": "EUR", "LI": "CHF", "LT": "EUR", "LU": "EUR", "MT": "EUR", "MD": "MDL", "MC": "EUR",
    "ME": "EUR", "NL": "EUR", "MK": "MKD", "NO": "NOK", "PL": "PLN", "PT": "EUR", "RO": "RON", "RU": "RUB",
    "SM": "EUR", "RS": "RSD", "SK": "EUR", "SI": "EUR", "ES": "EUR", "SE": "SEK", "CH": "CHF", "TR": "TRY",
    "UA": "UAH", "GB": "GBP", "VA": "EUR",
}
# Países cuyos precios se muestran convertidos a otra moneda (código ISO del país -> moneda de salida).
DISPLAY_CURRENCY = {"JP": "USD"}


@dataclass(frozen=True)
class Country:
    en: str
    es: str
    iso: str
    region: str
    emoji: str

    @property
    def subregion(self) -> str:
        return _SUB_OF.get(self.iso, self.region)

    @property
    def currency(self) -> str:
        return CURRENCY.get(self.iso, "")

    @property
    def display_currency(self) -> str:
        return DISPLAY_CURRENCY.get(self.iso, self.currency)

    @property
    def flag_emoji(self) -> str:
        if len(self.iso) != 2:
            return "🏳️"
        return "".join(chr(0x1F1E6 + ord(c) - 65) for c in self.iso.upper())


def load_countries(path: Path = EXCEL_PATH) -> list[Country]:
    """Lee la primera columna del Excel. Países que no estén en el diccionario se muestran con su nombre en inglés."""
    df = pd.read_excel(path)
    col = "Country" if "Country" in df.columns else df.columns[0]
    out: list[Country] = []
    for name in df[col].dropna().astype(str).str.strip():
        if not name:
            continue
        es, iso, region, emoji = _INFO.get(name, (name, "", "Otros", "🌍"))
        out.append(Country(name, es, iso, region, emoji))
    return out
