"""
sources.py — Every data source the pipeline uses, and how each app column is built.

Two kinds of inputs live under data/:
  raw/      downloaded automatically by `python -m pipeline fetch` (World Bank, WHO APIs)
  manual/   small CSVs copied from published tables that have no API (EF EPI, GPI,
            climate). Each file's header comment names the source and retrieval date.
  editorial.csv  the original hand-made values. Used (1) for the few columns no
            public dataset covers (PR ease, net salary and rent estimates) and
            (2) as a clearly flagged fallback when a source has no value for a country.
"""

WORLD_BANK_API = "https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}?format=json&mrnev=1&per_page=500"
WHO_GHO_API = "https://ghoapi.azureedge.net/api/{indicator}?$filter=TimeDim%20ge%20{since}"

# id -> metadata. "kind" decides how `python -m pipeline fetch` refreshes it.
SOURCES = {
    "NY.GNP.PCAP.CD": {
        "kind": "worldbank", "name": "GNI per capita, Atlas method (current US$)",
        "publisher": "World Bank, World Development Indicators", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/NY.GNP.PCAP.CD",
    },
    "NY.GDP.PCAP.CD": {
        "kind": "worldbank", "name": "GDP per capita (current US$)",
        "publisher": "World Bank, World Development Indicators", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD",
    },
    "NY.GDP.PCAP.PP.CD": {
        "kind": "worldbank", "name": "GDP per capita, PPP (current international $)",
        "publisher": "World Bank, World Development Indicators", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/NY.GDP.PCAP.PP.CD",
    },
    "PA.NUS.PRVT.PP": {
        "kind": "worldbank", "name": "PPP conversion factor, private consumption (LCU per international $)",
        "publisher": "World Bank, International Comparison Program", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/PA.NUS.PRVT.PP",
    },
    "PA.NUS.FCRF": {
        "kind": "worldbank", "name": "Official exchange rate (LCU per US$, period average)",
        "publisher": "World Bank / IMF", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/PA.NUS.FCRF",
    },
    "SL.UEM.TOTL.ZS": {
        "kind": "worldbank", "name": "Unemployment, total (% of labor force, modeled ILO estimate)",
        "publisher": "World Bank / ILO", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS",
    },
    "SL.EMP.VULN.ZS": {
        "kind": "worldbank", "name": "Vulnerable employment (% of total employment, modeled ILO estimate)",
        "publisher": "World Bank / ILO", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/SL.EMP.VULN.ZS",
    },
    "VC.IHR.PSRC.P5": {
        "kind": "worldbank", "name": "Intentional homicides (per 100,000 people)",
        "publisher": "World Bank / UNODC", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/VC.IHR.PSRC.P5",
    },
    "SP.DYN.LE00.IN": {
        "kind": "worldbank", "name": "Life expectancy at birth, total (years)",
        "publisher": "World Bank", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/SP.DYN.LE00.IN",
    },
    "IT.NET.USER.ZS": {
        "kind": "worldbank", "name": "Individuals using the Internet (% of population)",
        "publisher": "World Bank / ITU", "license": "CC BY 4.0",
        "url": "https://data.worldbank.org/indicator/IT.NET.USER.ZS",
    },
    "UHC_INDEX_REPORTED": {
        "kind": "who", "name": "UHC service coverage index (0–100)",
        "publisher": "World Health Organization, Global Health Observatory", "license": "CC BY-NC-SA 3.0 IGO",
        "url": "https://www.who.int/data/gho/data/indicators/indicator-details/GHO/uhc-index-of-service-coverage",
    },
    "EF_EPI": {
        "kind": "manual", "file": "manual/ef_epi.csv", "name": "EF English Proficiency Index 2025 score",
        "publisher": "EF Education First", "license": "Cited from published ranking",
        "url": "https://www.ef.com/epi/",
    },
    "GPI": {
        "kind": "manual", "file": "manual/gpi.csv", "name": "Global Peace Index 2026 score (lower = more peaceful)",
        "publisher": "Institute for Economics & Peace", "license": "Cited from published ranking",
        "url": "https://www.visionofhumanity.org/maps/",
    },
    "CITY_TEMP": {
        "kind": "manual", "file": "manual/climate_city.csv", "name": "Mean annual temperature of main city (°C)",
        "publisher": "Wikipedia: List of cities by average temperature (compiled from national met services)",
        "license": "CC BY-SA 4.0",
        "url": "https://en.wikipedia.org/wiki/List_of_cities_by_average_temperature",
    },
    "NATIONAL_TEMP": {
        "kind": "manual", "file": "manual/climate_national.csv",
        "name": "Mean annual temperature, national area average 1991–2020 (°C)",
        "publisher": "World Bank Climate Change Knowledge Portal (CRU)", "license": "CC BY 4.0",
        "url": "https://climateknowledgeportal.worldbank.org/",
    },
    "EDITORIAL": {
        "kind": "editorial", "file": "editorial.csv", "name": "Hand-made estimates (original dataset)",
        "publisher": "RelocAitor", "license": "MIT (this project)", "url": "",
    },
}

# Short human-readable names for the UI (provenance.csv keeps the ids).
SHORT_NAMES = {
    "NY.GNP.PCAP.CD": "Income per person (US$/yr)",
    "PRICE_LEVEL(consumption)": "Consumer prices vs US",
    "PRICE_LEVEL(gdp)": "Price level vs US",
    "SL.UEM.TOTL.ZS": "Unemployment %",
    "SL.EMP.VULN.ZS": "Informal/vulnerable jobs %",
    "VC.IHR.PSRC.P5": "Homicides per 100k",
    "GPI": "Global Peace Index",
    "UHC_INDEX_REPORTED": "WHO health coverage index",
    "SP.DYN.LE00.IN": "Life expectancy",
    "IT.NET.USER.ZS": "Internet users %",
    "EF_EPI": "EF English score",
    "CITY_TEMP": "Avg temperature",
    "NATIONAL_TEMP": "National avg temperature",
}

# Countries where English is the main native language. EF doesn't rank these.
NATIVE_ENGLISH = {"USA", "CAN", "GBR", "IRL", "AUS", "NZL", "SGP",
                  # English-speaking Caribbean and the Guianas (none in the original 66)
                  "JAM", "BHS", "BRB", "TTO", "ATG", "DMA", "GRD", "KNA", "LCA", "VCT", "GUY", "BLZ"}

# How each app column is built from the sources.
#   components: [(indicator, weight, transform, higher_is_better)]
#   transform:  "linear" | "log"
# Each component is robust-scaled to 0–1 across the dataset countries
# (values clipped to the 5th–95th percentile, then min-max), inverted when
# higher_is_better is False, then combined as a weighted mean of the
# components a country actually has.
COLUMN_METHODS = {
    "average_salary": {
        "components": [("NY.GNP.PCAP.CD", 1.0, "log", True)],
        "explain": "GNI per capita (Atlas, US$), log-scaled.",
    },
    "cost_of_living": {
        "components": [("PRICE_LEVEL", 1.0, "linear", True)],
        "explain": "Consumer price level = household-consumption PPP factor ÷ exchange rate (1.0 = US prices), "
                   "used when both are from years at most 1 apart; otherwise the economy-wide level "
                   "(GDP per capita US$ ÷ PPP $). Higher = more expensive; the app inverts it for 'affordability'. "
                   "Reflects what residents pay: expat rents in hubs like Singapore, Hong Kong and Dubai are "
                   "much higher than this suggests.",
    },
    "job_market": {
        "components": [("SL.EMP.VULN.ZS", 0.6, "linear", False), ("SL.UEM.TOTL.ZS", 0.4, "linear", False)],
        "explain": "60% low vulnerable (informal / own-account) employment + 40% low unemployment. "
                   "Unemployment alone flatters economies with large informal sectors.",
    },
    "safety": {
        "components": [("VC.IHR.PSRC.P5", 0.5, "log", False), ("GPI", 0.5, "linear", False)],
        "explain": "50% low homicide rate (log-scaled) + 50% Global Peace Index (conflict, militarisation, "
                   "political instability).",
    },
    "healthcare": {
        "components": [("UHC_INDEX_REPORTED", 0.6, "linear", True), ("SP.DYN.LE00.IN", 0.4, "linear", True)],
        "explain": "60% WHO universal health coverage index + 40% life expectancy.",
    },
    "internet": {
        "components": [("IT.NET.USER.ZS", 1.0, "linear", True)],
        "explain": "Share of the population using the internet. Measures access, not speed.",
    },
}
# Columns built by special rules in build.py:
SPECIAL_COLUMNS = {
    "english": "Native English countries = 1.0. Others: EF EPI score robust-scaled to 0.05–0.90.",
    "language_barrier": "1 − english (kept for compatibility; it carries no independent information).",
    "climate": "Comfort of the main city's mean annual temperature: 1.0 at 21 °C, falling to 0 at 7 °C "
               "(colder) or 41 °C (hotter); heat is penalised half as fast as cold.",
    "pr_ease": "Editorial judgement from the original dataset (no public index exists). Countries added later "
               "get their region's median, flagged as such.",
    "salary_usd_month": "Editorial estimate of average monthly net salary (no open source with global coverage). "
                        "Countries added later: predicted from income and prices (log-linear, cross-validated).",
    "rent_usd_month": "Editorial estimate of 1-bed city-centre rent (no open source with global coverage). "
                      "Countries added later: predicted from income and prices (log-linear, cross-validated).",
}
IDEAL_TEMP_C, COLD_SPAN_C, HOT_SPAN_C = 21.0, 14.0, 20.0
