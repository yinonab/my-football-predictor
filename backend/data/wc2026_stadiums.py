"""Official FIFA World Cup 2026 stadium metadata (static elevation + coordinates).

Source: FIFA 2026 host venue list (16 stadiums). Elevations are conservative
approximations for diagnostics — not fetched live during prediction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AltitudeBucket = Literal["sea_level", "low", "moderate", "high", "very_high", "unknown"]


@dataclass(frozen=True)
class Wc2026Stadium:
    stadium_id: str
    stadium_name: str
    city: str
    country: str
    host_area: str
    latitude: float
    longitude: float
    elevation_m: int
    altitude_bucket: AltitudeBucket
    source_note: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


def altitude_bucket_for_elevation(elevation_m: int | float | None) -> AltitudeBucket:
    if elevation_m is None:
        return "unknown"
    e = float(elevation_m)
    if e < 300:
        return "sea_level"
    if e < 800:
        return "low"
    if e < 1200:
        return "moderate"
    if e < 1800:
        return "high"
    return "very_high"


# FIFA 2026 — 16 official stadiums (3 Mexico, 2 Canada, 11 USA)
WC2026_STADIUMS: tuple[Wc2026Stadium, ...] = (
    Wc2026Stadium(
        stadium_id="atlanta_mercedes_benz",
        stadium_name="Mercedes-Benz Stadium",
        city="Atlanta",
        country="USA",
        host_area="Atlanta",
        latitude=33.755,
        longitude=-84.401,
        elevation_m=310,
        altitude_bucket="low",
        source_note="Approx. stadium elevation ~310m (Atlanta metro)",
        aliases=("atlanta", "mercedes-benz stadium", "mercedes benz stadium"),
    ),
    Wc2026Stadium(
        stadium_id="boston_gillette",
        stadium_name="Gillette Stadium",
        city="Foxborough",
        country="USA",
        host_area="Boston",
        latitude=42.091,
        longitude=-71.264,
        elevation_m=60,
        altitude_bucket="sea_level",
        source_note="Approx. ~60m; FIFA host area Boston/Foxborough",
        aliases=("boston", "foxborough", "gillette stadium"),
    ),
    Wc2026Stadium(
        stadium_id="dallas_att",
        stadium_name="AT&T Stadium",
        city="Arlington",
        country="USA",
        host_area="Dallas",
        latitude=32.748,
        longitude=-97.093,
        elevation_m=170,
        altitude_bucket="sea_level",
        source_note="Approx. ~170m; FIFA host area Dallas/Arlington",
        aliases=("dallas", "arlington", "at&t stadium", "att stadium"),
    ),
    Wc2026Stadium(
        stadium_id="houston_nrg",
        stadium_name="NRG Stadium",
        city="Houston",
        country="USA",
        host_area="Houston",
        latitude=29.685,
        longitude=-95.411,
        elevation_m=15,
        altitude_bucket="sea_level",
        source_note="Approx. ~15m",
        aliases=("houston", "nrg stadium"),
    ),
    Wc2026Stadium(
        stadium_id="kansas_city_arrowhead",
        stadium_name="GEHA Field at Arrowhead Stadium",
        city="Kansas City",
        country="USA",
        host_area="Kansas City",
        latitude=39.049,
        longitude=-94.484,
        elevation_m=270,
        altitude_bucket="low",
        source_note="Approx. ~270m",
        aliases=("kansas city", "arrowhead stadium", "geha field"),
    ),
    Wc2026Stadium(
        stadium_id="la_sofi",
        stadium_name="SoFi Stadium",
        city="Inglewood",
        country="USA",
        host_area="Los Angeles",
        latitude=33.953,
        longitude=-118.339,
        elevation_m=35,
        altitude_bucket="sea_level",
        source_note="Approx. ~35m; FIFA host area Los Angeles",
        aliases=("los angeles", "inglewood", "sofi stadium", "la"),
    ),
    Wc2026Stadium(
        stadium_id="miami_hard_rock",
        stadium_name="Hard Rock Stadium",
        city="Miami Gardens",
        country="USA",
        host_area="Miami",
        latitude=25.958,
        longitude=-80.239,
        elevation_m=3,
        altitude_bucket="sea_level",
        source_note="Approx. ~3m; FIFA host area Miami",
        aliases=("miami", "miami gardens", "hard rock stadium"),
    ),
    Wc2026Stadium(
        stadium_id="philadelphia_lincoln",
        stadium_name="Lincoln Financial Field",
        city="Philadelphia",
        country="USA",
        host_area="Philadelphia",
        latitude=39.901,
        longitude=-75.168,
        elevation_m=12,
        altitude_bucket="sea_level",
        source_note="Approx. ~12m",
        aliases=("philadelphia", "lincoln financial field"),
    ),
    Wc2026Stadium(
        stadium_id="sf_levis",
        stadium_name="Levi's Stadium",
        city="Santa Clara",
        country="USA",
        host_area="San Francisco Bay Area",
        latitude=37.403,
        longitude=-121.970,
        elevation_m=7,
        altitude_bucket="sea_level",
        source_note="Approx. ~7m; FIFA host area San Francisco Bay",
        aliases=(
            "san francisco",
            "santa clara",
            "levi's stadium",
            "levis stadium",
            "bay area",
        ),
    ),
    Wc2026Stadium(
        stadium_id="seattle_lumen",
        stadium_name="Lumen Field",
        city="Seattle",
        country="USA",
        host_area="Seattle",
        latitude=47.595,
        longitude=-122.332,
        elevation_m=50,
        altitude_bucket="sea_level",
        source_note="Approx. ~50m",
        aliases=("seattle", "lumen field"),
    ),
    Wc2026Stadium(
        stadium_id="ny_metlife",
        stadium_name="MetLife Stadium",
        city="East Rutherford",
        country="USA",
        host_area="New York / New Jersey",
        latitude=40.813,
        longitude=-74.074,
        elevation_m=3,
        altitude_bucket="sea_level",
        source_note="Approx. ~3m; FIFA host area New York/New Jersey",
        aliases=(
            "east rutherford",
            "new york",
            "new jersey",
            "metlife stadium",
            "ny/nj",
        ),
    ),
    Wc2026Stadium(
        stadium_id="toronto_bmo",
        stadium_name="BMO Field",
        city="Toronto",
        country="Canada",
        host_area="Toronto",
        latitude=43.633,
        longitude=-79.419,
        elevation_m=75,
        altitude_bucket="sea_level",
        source_note="Approx. ~75m",
        aliases=("toronto", "bmo field"),
    ),
    Wc2026Stadium(
        stadium_id="vancouver_bc_place",
        stadium_name="BC Place",
        city="Vancouver",
        country="Canada",
        host_area="Vancouver",
        latitude=49.277,
        longitude=-123.108,
        elevation_m=2,
        altitude_bucket="sea_level",
        source_note="Approx. ~2m",
        aliases=("vancouver", "bc place"),
    ),
    Wc2026Stadium(
        stadium_id="guadalajara_akron",
        stadium_name="Estadio Akron",
        city="Guadalajara",
        country="Mexico",
        host_area="Guadalajara",
        latitude=20.682,
        longitude=-103.462,
        elevation_m=1566,
        altitude_bucket="high",
        source_note="Approx. ~1566m (Zapopan/Guadalajara metro)",
        aliases=("guadalajara", "zapopan", "estadio akron", "akron"),
    ),
    Wc2026Stadium(
        stadium_id="mexico_city_azteca",
        stadium_name="Estadio Azteca",
        city="Mexico City",
        country="Mexico",
        host_area="Mexico City",
        latitude=19.303,
        longitude=-99.150,
        elevation_m=2240,
        altitude_bucket="very_high",
        source_note="Approx. ~2240m (Ciudad de México)",
        aliases=(
            "mexico city",
            "ciudad de méxico",
            "ciudad de mexico",
            "cdmx",
            "estadio azteca",
            "azteca",
        ),
    ),
    Wc2026Stadium(
        stadium_id="monterrey_bbva",
        stadium_name="Estadio BBVA",
        city="Monterrey",
        country="Mexico",
        host_area="Monterrey",
        latitude=25.669,
        longitude=-100.245,
        elevation_m=540,
        altitude_bucket="low",
        source_note="Approx. ~540m (Guadalupe/Monterrey metro)",
        aliases=("monterrey", "estadio bbva", "bbva"),
    ),
)

_ALIAS_INDEX: dict[str, Wc2026Stadium] = {}


def _normalize_key(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("'", "")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def _build_alias_index() -> dict[str, Wc2026Stadium]:
    if _ALIAS_INDEX:
        return _ALIAS_INDEX
    for stadium in WC2026_STADIUMS:
        keys = {
            _normalize_key(stadium.stadium_id),
            _normalize_key(stadium.stadium_name),
            _normalize_key(stadium.city),
            _normalize_key(stadium.host_area),
        }
        keys.update(_normalize_key(a) for a in stadium.aliases)
        for key in keys:
            if key:
                _ALIAS_INDEX.setdefault(key, stadium)
    return _ALIAS_INDEX


def lookup_stadium(value: str | None) -> Wc2026Stadium | None:
    if not value or not str(value).strip():
        return None
    key = _normalize_key(str(value))
    index = _build_alias_index()
    if key in index:
        return index[key]
    for alias, stadium in index.items():
        if alias in key or key in alias:
            return stadium
    return None


def lookup_coordinates_from_stadiums(city_or_stadium: str | None) -> tuple[float, float] | None:
    stadium = lookup_stadium(city_or_stadium)
    if stadium is None:
        return None
    return stadium.latitude, stadium.longitude
