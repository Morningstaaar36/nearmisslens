"""Junction Safety Brief: from an address to a ranked, cited, checked plan for a city engineer.

1. The official record (context.dossier): street layout, police-reported crashes over five years, the city's priority
   designations and its projects.
2. Fix options: every FHWA Proven Safety Countermeasure whose CMF Clearinghouse record targets a crash group the
   record shows (pedestrian, angle/turning, rear-end), with expected crashes avoided per year by the Highway Safety
   Manual's simple method, observed crashes per year x (1 - CMF). This is not the Empirical Bayes method; the brief
   says so.
3. The top option drawn by Muse Image on the city's own aerial photo, with a SAM 3.1 check that it was added.
4. A memo agent (Muse Spark, or Muse Spark Open on Baseten) writes the brief; a checker rejects any number that is not
   in the facts."""
from __future__ import annotations

import io
import json
import math
import os
import re
from pathlib import Path

import cv2
import httpx
import numpy as np

from . import context, countermeasures, harm, panel, sam_api
from .agent import Tool, run_agent
from .config import SETTINGS, portable, resolve
from .config import MODELS

YEARS = context.YEARS
OVERPASS_SERVERS = (context.OVERPASS, *context.OVERPASS_MIRRORS)


GEOCODES = Path(__file__).resolve().parent / "data" / "geocodes.json"


def _key(address: str) -> str:
    streets = address.split(",")[0].lower().replace(" and ", " & ")
    return " & ".join(sorted(" ".join(x.split()) for x in streets.split("&")))


def _norm(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()) + " "


def city_named(address: str) -> str | None:
    """The registry city named after the first comma ('Pine St & 5th Ave, Seattle, WA'), by its id, name or an alias
    in registry.json; the name written first wins, so 'Seattle, Washington' is Seattle. None if no city is named."""
    from . import opendata
    rest = _norm(address.partition(",")[2])
    best = None
    for c in opendata.load_cities():
        for n in {c["id"], c["name"], *c.get("aliases", [])}:
            i = rest.find(_norm(n))
            if i >= 0 and (best is None or i < best[0]):
                best = (i, c["id"])
    return best[1] if best else None


def _entry(table: dict, address: str) -> dict | None:
    """The offline table's point for an address, only in the city the address names. Without a city, a street pair
    known in one city only is used; known in several, it is refused rather than guessed."""
    key, city = _key(address), city_named(address)
    if city:
        return table.get(f"{city}|{key}")
    if address.partition(",")[2].strip():
        return None  # a place the registry does not know: never another city's point
    hits = [v for k, v in table.items() if k.partition("|")[2] == key]
    if len(hits) > 1:
        raise ValueError(f"{address!r} is a corner in more than one city ({', '.join(sorted(h['city'] for h in hits))}); "
                         "add the city, e.g. 'Street A & Street B, City'")
    return hits[0] if hits else None


def gazetteer() -> dict:
    return json.loads(GEOCODES.read_text()) if GEOCODES.exists() else {}


def save_gazetteer(extra: list[dict] | None = None) -> int:
    """The offline geocode table: every screened priority intersection and the briefs already built, so known
    places need no geocoding service (and replay works for them)."""
    from . import citywide
    table = gazetteer()
    for city, res in citywide.screened():
        for r in res.get("rows", []):
            table[f"{city}|{_key(r['name'])}"] = {"lat": r["lat"], "lon": r["lon"], "name": r["name"], "city": city}
    for p in SETTINGS.runs_dir.glob("briefs/*/brief.json"):
        f = json.loads(p.read_text())
        d = f.get("dossier") or {}
        if d.get("lat") is not None and d.get("city"):
            table.setdefault(f"{d['city']}|{_key(f['junction'])}", {"lat": d["lat"], "lon": d["lon"], "name": f["junction"].split(",")[0],
                                                   "city": d.get("city")})
    for e in extra or []:
        table[f"{e['city']}|{_key(e['name'])}"] = e
    GEOCODES.write_text(json.dumps(dict(sorted(table.items())), indent=0))
    return len(table)


ABBREV_FULL = {"st": "Street", "ave": "Avenue", "av": "Avenue", "blvd": "Boulevard", "rd": "Road", "pkwy": "Parkway",
               "dr": "Drive", "pl": "Place", "ln": "Lane", "ct": "Court", "hwy": "Highway", "expy": "Expressway",
               "sq": "Square", "ter": "Terrace", "way": "Way", "n": "North", "s": "South", "e": "East", "w": "West",
               "rev": "Reverend", "jr": "Junior", "mt": "Mount", "ft": "Fort"}
ROADWAY_TAGS = {"wr", "er", "nr", "sr", "nb", "sb", "eb", "wb", "ramp", "rp"}  # a carriageway or ramp of one street
QUADRANT = {"nw": "Northwest", "ne": "Northeast", "sw": "Southwest", "se": "Southeast"}


def address_variants(address: str) -> list[str]:
    """The ways a person writes an intersection, rewritten the way the geocoder needs it ('Street A & Street B, City'
    with OpenStreetMap's full names): 'and'/'at'/'near' become '&', abbreviations are spelled out, and a quadrant
    written on one street (DC's 'NW') is carried to the other. The original comes first."""
    out = [address]
    head, _, rest = address.partition(",")
    rest = rest.strip()
    parts = re.split(r"\s+(?:and|at|near|&|/)\s+", head.strip(), maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return out

    def full(street: str, quad: str | None) -> str:
        words = [ABBREV_FULL.get(w.lower().strip("."), w) for w in street.split()]
        q = next((QUADRANT[w.lower().strip(".")] for w in words if w.lower().strip(".") in QUADRANT), None)
        words = [w for w in words if w.lower().strip(".") not in QUADRANT]
        return " ".join(words + ([q or quad] if (q or quad) else []))
    quad = next((QUADRANT[w.lower().strip(".")] for p in parts for w in p.split() if w.lower().strip(".") in QUADRANT), None)
    for a, b in ((parts[0], parts[1]), (parts[1], parts[0])):
        for f in (lambda s: s.strip(), lambda s: full(s, None), lambda s: full(s, quad)):
            v = f"{f(a)} & {f(b)}" + (f", {rest}" if rest else "")
            if v not in out:
                out.append(v)
    return out


def geocode(address: str) -> tuple[float, float, str]:
    """An address, or an intersection written 'Street A & Street B, City': the offline table first, then Nominatim
    finds the area, and for an intersection OpenStreetMap gives the node shared by the two streets nearest to it."""
    if not address or not address.strip():
        raise ValueError("give an address or an intersection, e.g. 'Street A & Street B, City'")
    errors = []
    for k, v in enumerate(address_variants(address)):  # as written first, then 'St' -> 'Street', 'and' -> '&' ...
        known = _entry(gazetteer(), v)
        if known:
            return known["lat"], known["lon"], f"{known['name']}, {address.split(',', 1)[1].strip()}" \
                if "," in address else known["name"]
        try:  # in replay, a lookup made in the live run is answered from the request cache; anything else is refused
            return _lookup(v)
        except FileNotFoundError:
            if k == 0:
                raise ValueError(f"{address!r} is not in the offline set; run without replay to look it up") from None
        except OutsideCoverage:
            raise
        except ValueError as e:
            errors.append(e)
    raise errors[0]


DIRECTIONS = "North|South|East|West|Northeast|Northwest|Southeast|Southwest|N|S|E|W|NE|NW|SE|SW"


def _directional(street: str) -> str:
    """A street name pattern that also matches it with a direction word before or after it, and with or without a
    period after an initial ("Reverend James A Polite Avenue" is "Reverend James A. Polite Avenue" in OpenStreetMap)."""
    words = [w.rstrip(".") + "[.]?" if len(w.rstrip(".")) == 1 else w for w in street.split()]
    return f"(({DIRECTIONS}) )?{' '.join(words)}( ({DIRECTIONS}))?"


DIRECTION_WORDS = {"n": "north", "s": "south", "e": "east", "w": "west", "ne": "northeast", "nw": "northwest",
                   "se": "southeast", "sw": "southwest"}


def street_pattern(name: str) -> str:
    """An OpenStreetMap name pattern for a street as people write it: each abbreviation or its full word ("Ave" or
    "Avenue"), the direction before or after the name, abbreviated or not ("SW Hinds St" is "Southwest Hinds
    Street"), ordinal numbers with or without their suffix, and initials with or without a period."""
    full_dir = {**DIRECTION_WORDS, **{v: v for v in DIRECTION_WORDS.values()}}
    toks = [t for t in re.split(r"\s+", name.strip()) if t]
    lowered = [t.lower().rstrip(".") for t in toks]
    direction = None
    if len(toks) > 1 and lowered[0] in full_dir:
        direction, toks, lowered = full_dir[lowered[0]], toks[1:], lowered[1:]
    elif len(toks) > 1 and lowered[-1] in full_dir:
        direction, toks, lowered = full_dir[lowered[-1]], toks[:-1], lowered[:-1]
    words = []
    for t, low in zip(toks, lowered):
        full = ABBREV_FULL.get(low)
        if full and len(low) > 1 and low not in ("n", "s", "e", "w"):
            short = next((k for k, v in ABBREV_FULL.items() if v.lower() == full.lower() and len(k) > 1), low)
            words.append(f"({re.escape(short)}[.]?|{re.escape(full)})")
        elif re.fullmatch(r"0*\d+(st|nd|rd|th)?", low):
            n = re.match(r"0*(\d+)", low).group(1)
            words.append(f"{n}(st|nd|rd|th)?")
        elif len(low) == 1:
            words.append(f"{re.escape(low)}[.]?")
        else:
            words.append(re.escape(t.rstrip(".")))
    core = " ".join(words)
    if direction:
        abbr = next(k for k, v in DIRECTION_WORDS.items() if v == direction)
        d = f"({abbr}[.]?|{direction})"
    else:
        d = f"({DIRECTIONS})"
    return f"({d} )?{core}( {d})?"


def _crossing(a: str, b: str, area: str) -> list[tuple[float, float]]:
    """The nodes where streets named a and b (patterns, case-insensitive) meet in the area (an Overpass filter:
    "around:R,LAT,LON" or a bounding box "S,W,N,E"). Each public Overpass server is asked once, within a time limit;
    ValueError when none answers."""
    q = (f'[out:json][timeout:90];way({area})[highway][name~"^{a}$",i]->.a;'
         f'way({area})[highway][name~"^{b}$",i]->.b;node(w.a)(w.b);out;')
    for server in OVERPASS_SERVERS:  # the public servers fail now and then; try the next one
        try:
            res, _ = context.fetch(server, data={"data": q}, timeout=75, attempts=1)
        except RuntimeError:
            continue
        return [(e["lat"], e["lon"]) for e in res.get("elements", []) if e.get("type") == "node"]
    raise ValueError("OpenStreetMap servers are unavailable; try again or give coordinates")


PHOTON = "https://photon.komoot.io/api/"


def _photon(q: str, country: str, bbox: list | None = None) -> list:
    """Photon (komoot's open geocoder over the same OpenStreetMap data), roads only, in Nominatim's shape: the
    fallback when Nominatim refuses or does not answer, so a lookup is not blocked by one server's limits."""
    params = {"q": q, "limit": 5, "osm_tag": "highway"}
    if bbox:
        s, w, n, e = bbox
        params["bbox"] = f"{w},{s},{e},{n}"
    js, _ = context.fetch(PHOTON, params, attempts=2)
    out = []
    for f in js.get("features") or []:
        pr = f.get("properties") or {}
        if country and (pr.get("countrycode") or "").lower() not in {c.strip().lower() for c in country.split(",")}:
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        shown = ", ".join(str(pr[k]) for k in ("name", "locality", "district", "city", "county", "state", "postcode",
                                               "country") if pr.get(k))
        out.append({"lat": str(lat), "lon": str(lon), "display_name": shown, "name": pr.get("name", ""),
                    "addresstype": pr.get("type", ""), "source": "photon"})
    return out[:1]


def _search(params: dict, country: str, bbox: list | None = None) -> list:
    """Nominatim, else Photon when Nominatim is refusing or down."""
    try:
        js, _ = context.fetch("https://nominatim.openstreetmap.org/search", params)
        return js
    except RuntimeError:
        return _photon(params["q"], country, bbox)


def _nominatim(q: str, country: str, city: str | None) -> list:
    """Nominatim's best match (Photon's when Nominatim refuses). A long street runs past the city line (its best match
    can be in a suburb on the same road), so when the address names a registry city and the match is not in it, the
    search is repeated within that city's bounding box. The first search's parameters are unchanged, so earlier
    lookups answer from the cache."""
    from . import opendata
    params = {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": country}
    js = _search(params, country)
    c = opendata.city(city) if city else None
    if c and (not js or context.city_of(float(js[0]["lat"]), float(js[0]["lon"])) != c["id"]):
        s, w, n, e = c["bbox"]
        inside = _search({**params, "viewbox": f"{w},{n},{e},{s}", "bounded": 1}, country, c["bbox"])
        js = inside or js
    return js


def _street_words(name: str) -> list[set[str]]:
    """Each street of an intersection's name as a set of words, abbreviations spelled out and direction words, street
    types and punctuation set aside: "E 9th St & Rev Q. Zed Ave, Town" -> [{9th}, {reverend, q, zed}]."""
    drop = {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "street", "avenue",
            "boulevard", "road", "place", "drive", "lane", "court", "parkway", "way", "terrace", "highway",
            "expressway", "square", "the"}
    head = name.split(",")[0]
    out = []
    for part in re.split(r"\s+(?:&|and|at|/)\s+|\s*&\s*", head, flags=re.I):
        words = {re.sub(r"^0*(\d+?)(st|nd|rd|th)?$", r"\1", ABBREV_FULL.get(w, QUADRANT.get(w, w)).lower())
                 for w in re.findall(r"[a-z0-9]+", part.lower())}  # "169th", "169" and "04th" are one street each
        words = {w for w in words if w not in drop and w not in ROADWAY_TAGS}
        if words:
            out.append(words)
    return out


def same_corner(proposed: str, corner: str) -> bool:
    """Whether the investigated corner is the proposal's intersection: every street the proposal names is one of the
    corner's streets (word for word, abbreviations and direction words aside)."""
    want, have = _street_words(proposed), _street_words(corner)
    return bool(want) and all(any(_words_match(w, h) for h in have) for w in want)


def _words_match(a: set[str], b: set[str]) -> bool:
    """One street's words against another's: the smaller set's every word is in the larger, where an initial matches
    a word that starts with it ("M L King Jr Way" is "Martin Luther King Junior Way")."""
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    hit = lambda w: w in big or (len(w) == 1 and w.isalpha() and any(x.startswith(w) for x in big)) or \
        (len(w) > 1 and any(len(x) == 1 and w.startswith(x) for x in big))
    return all(hit(w) for w in small)


CODED_SHARE = 0.5  # below this share of the circle's coded crashes at the corner itself, the circle is mostly others'


def coded_here(cr: dict, corner: str, min_coded: int = 5) -> dict | None:
    """Where the crash dataset codes each crash's two streets: how many of the crashes in the circle the city codes
    at this intersection, and the neighbouring intersections that hold the rest. None when the dataset does not code
    streets, or codes too few crashes here to say."""
    pairs, coded = (cr or {}).get("street_pairs") or [], (cr or {}).get("street_coded") or 0
    if coded < min_coded:
        return None
    here = [p for p in pairs if same_corner(p["pair"], corner) and same_corner(corner, p["pair"])]
    others = [p for p in pairs if p not in here]
    at = sum(p["crashes"] for p in here)
    return {"coded": coded, "at_corner": at, "injury_at_corner": sum(p["injury_crashes"] for p in here),
            "share": round(at / coded, 3), "elsewhere": others[:3], "mostly_elsewhere": at / coded < CODED_SHARE}


def coded_sentence(name: str, ch: dict) -> str:
    """The plain sentence for a circle that mostly holds other corners' crashes."""
    rest = ", ".join(f"{p['pair']} {p['crashes']}" for p in ch["elsewhere"])
    return (f"The city's record codes {ch['at_corner']} of the {ch['coded']} crashes within the circle at "
            f"{name.split(',')[0]} itself; the rest are coded at neighbouring intersections ({rest}), so the counts "
            "and estimates here include other corners' crashes.")


SETTLEMENT = {"city", "town", "village", "hamlet", "municipality", "suburb", "borough", "quarter", "neighbourhood",
              "city_district"}
# a place named after "in" or after a comma ("Oak Avenue in Elmwood", "Oak Avenue, Elmwood")
PLACE_AFTER_IN = re.compile(r"(?:\bin[ ]+|,[ ]*)((?:[A-Z][a-z]+|[A-Z]\.)(?:[ -][A-Z][a-z]+){0,3})")
MONTHS = {"January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


def places_named(text: str, city: dict) -> list[str]:
    """Place names a text gives after "in" ("... Oak Avenue in Elmwood"), the city's own names left out."""
    own = {city["name"], city.get("short_name") or "", *(city.get("aliases") or [])}
    own = {n.lower() for n in own if n}
    out = []
    for m in PLACE_AFTER_IN.finditer(text or ""):
        name = m.group(1).strip()
        if name in MONTHS or name.lower() in own or any(name.lower().startswith(o + " ") for o in own):
            continue
        if name not in out:
            out.append(name)
    return out


def place_outside(place: str, city: dict) -> str | None:
    """The geocoder's description of `place` when it is a town, village or neighbourhood inside the city's bounding
    box but outside the city's own limits; None when it is in the city, is not a settlement, or cannot be looked up
    (a lookup that fails never refuses a case)."""
    from . import opendata
    country = (json.loads(opendata.REGISTRY.read_text()).get("geocoder") or {}).get("countrycodes", "")
    s, w, n, e = city["bbox"]
    try:
        js, _ = context.fetch("https://nominatim.openstreetmap.org/search",
                              {"q": place, "format": "jsonv2", "limit": 5, "countrycodes": country,
                               "viewbox": f"{w},{n},{e},{s}", "bounded": 1})
    except Exception:
        return None
    hit = next((h for h in js or [] if (h.get("addresstype") or h.get("type")) in SETTLEMENT
                and _same_name(place, h.get("name") or "")), None)
    if hit is None:
        return None
    shown = hit.get("display_name", "")
    return None if in_city_limits(shown, city) else shown


def _same_name(asked: str, found: str) -> bool:
    n = lambda x: re.sub(r"^(city|town|village|borough) of ", "", " ".join(re.findall(r"[a-z]+", x.lower())))
    return n(asked) == n(found)


def towns_outside(text: str, city: dict, limit: int = 4) -> list[tuple[str, str]]:
    """(place, its description) for each place the text names that lies inside the city's box but outside its
    limits: a source about Main St & Oak Ave in a neighbouring town is not about the city's own Main & Oak."""
    out = []
    for name in places_named(text, city)[:limit]:
        shown = place_outside(name, city)
        if shown:
            out.append((name, shown))
    return out


class OutsideCoverage(ValueError):
    """The place is in no registry city: refused at once, before any slow intersection search."""


def in_city_limits(display_name: str, city: dict) -> bool:
    """Whether the geocoder's place is inside the registry city, not a town inside its bounding box: one of the
    city's names (registry name, short name, aliases) is among the place's parts once the state, postcode and
    country are set aside (a street in a town inside the city's box is not in the city).
    A place with no description is not refused here."""
    parts = [x.strip() for x in (display_name or "").split(",") if x.strip()]
    if not parts:
        return True
    zips = [i for i, x in enumerate(parts) if re.fullmatch(r"\d{5}(-\d{4})?", x)]
    if zips:  # "..., <state>, <postcode>, <country>": keep what comes before the state
        parts = parts[:max(zips[-1] - 1, 0)]
    names = {city["name"], city.get("short_name") or city["name"], *(city.get("aliases") or [])}
    # a county named after the city ("Los Angeles County") is not the city: a town in it is outside the limits
    parts = [x for x in parts if not re.search(r"\b(County|Parish|Township)$", x)]
    text = ", ".join(parts)
    return any(re.search(r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])", text, re.I) for n in names if n)


def _covered() -> str:
    from . import opendata  # the cities whose crash records are registered: a city without them is not covered
    return ", ".join(c["name"] for c in opendata.load_cities() if "crash" in opendata.coverage(c["id"])["kinds"])


def _lookup(address: str) -> tuple[float, float, str]:
    from . import opendata
    country = (json.loads(opendata.REGISTRY.read_text()).get("geocoder") or {}).get("countrycodes", "")
    streets = address.split(",")[0]
    rest = ",".join(address.split(",")[1:])
    first = streets.split("&")[0].strip() if "&" in streets else streets
    named = city_named(address)
    js = _nominatim(f"{first},{rest}", country, named)
    if not js:
        raise ValueError(f"address not found: {address}")
    lat, lon, name = float(js[0]["lat"]), float(js[0]["lon"]), js[0].get("display_name", address)
    here = opendata.city(context.city_of(lat, lon) or "")
    place = rest.split(",")[0].strip() if rest.strip() else ""
    shown = js[0].get("display_name", "")
    if here and place and re.search(r"(?<![A-Za-z])" + re.escape(place) + r"(?![A-Za-z])", shown, re.I) \
            and not in_city_limits(shown, here):  # the address names a town inside the city's box, and it is there
        raise OutsideCoverage(f"{address!r} is in {js[0]['display_name'].split(',')[1].strip() if ',' in js[0].get('display_name', '') else 'another place'}"
                              f", outside {here['name']}'s own limits: its crash records do not cover it")
    if context.city_of(lat, lon) is None:
        raise OutsideCoverage(f"{address!r} is outside the cities this copy covers ({_covered()})"
                              + ("" if os.environ.get("NML_PUBLIC") == "1" else "; add a city with nml add-city"))
    if "&" not in streets:
        return lat, lon, name
    a, b = (x.strip() for x in streets.split("&")[:2])
    jb = _nominatim(f"{b},{rest}", country, named)
    if jb:  # long streets: search around the midpoint of the two streets' anchors, wide enough to reach both
        lat, lon = (lat + float(jb[0]["lat"])) / 2, (lon + float(jb[0]["lon"])) / 2
    nodes = _crossing(street_pattern(a), street_pattern(b), f"around:12000,{lat},{lon}")
    c = opendata.city(named) if named else None
    if not nodes and c:  # the whole named city, with a direction before or after each name ("North Milwaukee Avenue"):
        s, w, n, e = c["bbox"]  # a common name's best match can be another street of that name across town
        nodes = _crossing(_directional(a), _directional(b), f"{s},{w},{n},{e}")
        if nodes:
            lat, lon = float(js[0]["lat"]), float(js[0]["lon"])  # the crossing nearest the first street's match
    if not nodes:
        raise ValueError(f"no intersection of {a} and {b} found near {name}")
    lat2, lon2 = min(nodes, key=lambda n: (n[0] - lat) ** 2 + (n[1] - lon) ** 2)
    from . import context as _c
    found = {"lat": lat2, "lon": lon2, "name": f"{a} & {b}", "city": _c.city_of(lat2, lon2)}
    named = city_named(address)
    if named and found["city"] != named:
        raise ValueError(f"{a} & {b} was found in {found['city'] or 'a place no registry city covers'}, not in the city "
                         "the address names")
    if found["city"]:  # remembered in its own city, so the next lookup (and replay) needs no service
        table = gazetteer()
        table[f"{found['city']}|{_key(address)}"] = found
        GEOCODES.write_text(json.dumps(dict(sorted(table.items())), indent=0))
    return lat2, lon2, f"{a} & {b}, {rest.strip()}"


def in_place(d: dict) -> dict[str, dict]:
    """Proven Safety Countermeasures the city's records show already installed at the junction, with the year: a
    project adapter whose records are themselves a countermeasure says so in the registry ("countermeasure")."""
    from . import opendata
    out = {}
    for p in (d.get("plans") or {}).get("projects", []):
        name = (opendata.adapter(p.get("dataset") or "") or {}).get("countermeasure")
        if name and (name not in out or (p.get("year") or 0) < (out[name].get("year") or 0)):
            out[name] = {"countermeasure": name, "year": p.get("year"), "dataset": p.get("dataset")}
    return out


def _conditions(d: dict, min_share: float = 0.05) -> frozenset[str]:
    """Countermeasure preconditions the crash record supports: a contributing factor behind at least min_share of
    the crashes."""
    from . import opendata
    cr = d.get("crashes") or {}
    total = max(cr.get("crashes", 0), 1)
    # each crash dataset words its contributing factors differently; its adapter maps them to conditions
    mapping = (opendata.adapter(cr.get("adapter") or "") or {}).get("factor_conditions", {})
    conds = set()
    for f, n in (cr.get("factor_counts") or {}).items():
        c = mapping.get(str(f).lower())
        if c and n / total >= min_share:
            conds.add(c)
    if "a turning movement" in conds:
        conds.add("a left-turn movement")
    return frozenset(conds)


def site_control(d: dict) -> str:
    """The junction's traffic control from the street layout (OpenStreetMap), or 'unknown'."""
    street = d.get("street") or {}
    near = street.get("signals_at_junction")
    if street.get("signals", 0) > 0 and near != 0:  # 0: the signals mapped nearby belong to another crossing
        return "Signalized"
    if "error" not in street and street.get("stop_signs", 0) > 0:
        return "Stop-controlled"
    if "error" not in street and street.get("roads") and (not street.get("signals") or near == 0):
        return "Uncontrolled"
    return "unknown"


def populations(cr: dict) -> dict:
    """Crash counts over the period for each population a CMF can cover; None where the record cannot show it."""
    g = cr.get("crash_groups", {})
    injury = cr.get("injury_crashes", 0)
    typed = bool(cr.get("crash_type_recorded"))
    return {"pedestrian": g.get("pedestrian", 0), "all": injury,
            # rear-end crashes come from crash types where recorded, otherwise from contributing factors
            "rear_end": g.get("rear_end", 0) if (typed or cr.get("factor_counts")) else None,
            "angle": g.get("angle_turning", 0) if typed else None,
            "wet": round(injury * cr["wet_share"], 1) if cr.get("wet_share") is not None else None,
            "night": round(injury * cr["dark_share"], 1) if cr.get("dark_share") is not None else None,
            "walking_along": cr.get("walking_along")}


# How strongly the evidence backs an estimated fix here, strongest first. "measured here": this city's own past installs
# passed the causal gate. "FHWA-cited": the record FHWA's fact sheet cites, no unverified precondition. "national
# studies": the median of eligible records. "needs a site check": the estimate holds only if something the public data
# cannot show is true (the record's study sites, or the fix's own precondition). "contradicted here": the city's own
# record rules out the national effect.
LIT_ALREADY = 0.8  # lighting is not estimated where the record codes this share of after-dark crashes as lit
EVIDENCE = ("measured here", "FHWA-cited", "national studies", "needs a site check", "contradicted here")
SUPPORTED = EVIDENCE[:3]  # the tiers a plan may total without a site visit


def evidence_tier(o: dict) -> str:
    if (o.get("local_program") or {}).get("contradicts_cmf"):
        return "contradicted here"
    if o.get("verify_on_site"):
        return "needs a site check"
    if o.get("local_evidence"):
        return "measured here"
    return "FHWA-cited" if o.get("fhwa_cited") else "national studies"


def fix_options(d: dict, cmf, control: str | None = None) -> dict:
    """Every FHWA Proven Safety Countermeasure for the junction. A fix is estimated (crashes avoided per year,
    dollars) only when one of its curated CMF records applies to this site's control, kind and a crash population
    the record shows; otherwise it is listed with the reason and no number. Each estimate carries its evidence tier
    (EVIDENCE). Order: low-cost before reconstruction, then by tier, then by crashes avoided. `control` overrides
    the mapped control, to estimate the site as a proposal describes it."""
    cr = d.get("crashes") or {}
    if not cr or "error" in cr:
        return {"options": [], "not_estimated": [], "note": "no crash record available for this location"}
    control = control or site_control(d)
    conds = _conditions(d)
    pops = populations(cr)
    have = in_place(d)
    from . import treatments
    estimated, not_estimated = [], []
    for item in countermeasures.psc_items():
        name = item["name"]
        if item.get("site_fix") is False or name in have:
            continue
        sel = countermeasures.select(item, control, pops, cmf, frozenset(d.get("site_kinds") or ()))
        lit = cr.get("dark_lit_share")
        if name == "Lighting" and sel.get("quantified") and lit is not None and lit >= LIT_ALREADY \
                and (cr.get("dark_crashes") or 0) >= 5:  # its estimate is for an unlit corner; the record says lit
            sel = {"quantified": False, "reason": f"the record codes {round(100 * lit)}% of the crashes after dark "
                                                  "here as with street lights on, and the lighting estimate is for a "
                                                  "corner without street lighting"}
        checks = [c for c in (item.get("condition") if item.get("condition") not in conds else None,
                              item.get("site_check"), sel.get("site_condition")) if c]
        if not sel["quantified"]:
            not_estimated.append({"countermeasure": name, "quantified": False, "reason": sel["reason"],
                                  "verify_on_site": "; ".join(checks) or None})
            continue
        per_year = sel["target_crashes_5y"] / YEARS
        avoided = per_year * (1 - sel["cmf"])
        o = {"countermeasure": name, "scale": item.get("scale", "low-cost"), **sel, "crf_pct": round(100 * (1 - sel["cmf"]), 1),
             "target_crashes_per_year": round(per_year, 1), "expected_crashes_avoided_per_year": round(avoided, 1),
             **harm.option(avoided, sel["targets"], cr), "verify_on_site": "; ".join(checks) or None}
        ev = treatments.local_evidence(d.get("city"), name)  # this city's own past installs, where tested
        if ev:
            o["local_evidence"] = ev
        st = treatments.program_status(d.get("city"), name)
        if st["status"] in treatments.NOT_SUPPORTED:  # the city tried it and its own record does not show an effect
            # it changes the ranking only when the city's interval rules out the national CMF's effect (or crashes
            # rose); a wide interval from a few sites is shown but carries no weight
            o["local_program"] = {**{k: st[k] for k in ("status", "label", "text", "source", "study", "ci95")},
                                  "contradicts_cmf": st["status"] == "worse" or st["ci95"][0] > sel["cmf"]}
        o["evidence"] = evidence_tier(o)
        estimated.append(o)
    # low-cost fixes before reconstructions (which need a design study), then the strength of the evidence, then size
    opts = sorted(estimated, key=lambda o: (o["scale"] == "reconstruction", EVIDENCE.index(o["evidence"]),
                                            -o["expected_crashes_avoided_per_year"]))
    projects = (d.get("plans") or {}).get("projects", [])
    return {"options": opts, "not_estimated": not_estimated, "in_place": list(have.values()), "control": control,
            "repeat_risk": treatments.repeat_risk(d.get("city"), projects),
            "harm": harm.junction(cr, YEARS), "conditions_from_record": sorted(conds),
            "method": "expected crashes avoided per year = target crashes per year x (1 - CMF), Highway Safety Manual "
                      "simple method (not Empirical Bayes), with the CMF FHWA's fact sheet cites or else the median of "
                      "the curated records that fit the site; dollars use the U.S. DOT's injury-crash value "
                      f"({harm.SHORT}), break-even cost over {harm.LIFE_YEARS} years at {harm.RATE:.0%}"}


def _mercator(lat: float, lon: float) -> tuple[float, float]:
    return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi


USGS_IMAGERY = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"


AERIAL_PX, AERIAL_RADIUS_M = 768, 90.0  # the aerial photo: AERIAL_PX square over 2 x AERIAL_RADIUS_M


def aerial(lat: float, lon: float, city: str | None, out: Path, size: int = AERIAL_PX,
           radius_m: float = AERIAL_RADIUS_M) -> Path | None:
    """An aerial photo centred on the junction: a city or state orthophoto from the registry when one covers the
    point, otherwise USGS national imagery (public domain, any US location)."""
    from . import opendata
    if out.exists():
        return out
    if SETTINGS.replay:  # replay never calls a network service
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    mx, my = _mercator(lat, lon)
    params = {"bbox": f"{mx - radius_m},{my - radius_m},{mx + radius_m},{my + radius_m}", "bboxSR": 3857,
              "imageSR": 3857, "size": f"{size},{size}", "format": "jpg", "f": "image"}
    sources = [(a["endpoint"], a["source"]) for a in opendata.adapters_for(lat, lon, "imagery")]
    sources.append((USGS_IMAGERY, "USGS The National Map imagery"))
    with httpx.Client(timeout=60, headers=context.UA) as c:
        for url, source in sources:
            try:
                r = c.get(url, params=params)
            except httpx.TransportError:
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                if img is not None and img.std() > 8:  # a blank or placeholder tile has almost no variation
                    cv2.imwrite(str(out), img)
                    out.with_suffix(".txt").write_text(source)
                    return out
    return None


def street_photo(lat: float, lon: float, out: Path, radius_m: float = 35.0) -> dict | None:
    """The most recent Mapillary street-level photo within radius_m of the junction (Meta's street imagery,
    CC BY-SA), with its capture date and link. Needs MAPILLARY_CLIENT_TOKEN."""
    import os
    token = os.environ.get("MAPILLARY_CLIENT_TOKEN")
    if not token:
        return None
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists():
        return {**json.loads(meta.read_text()), "image": portable(str(out))}
    if SETTINGS.replay:  # replay never calls a network service
        return None
    d = radius_m / 111_320
    bbox = f"{lon - d / math.cos(math.radians(lat))},{lat - d},{lon + d / math.cos(math.radians(lat))},{lat + d}"
    js, _ = context.fetch("https://graph.mapillary.com/images",
                          {"access_token": token, "bbox": bbox, "limit": 50,
                           "fields": "id,captured_at,thumb_1024_url,computed_geometry,is_pano"})
    imgs = [x for x in js.get("data", []) if x.get("thumb_1024_url") and not x.get("is_pano")]
    if not imgs:
        return None
    pick = max(imgs, key=lambda x: x.get("captured_at") or 0)
    with httpx.Client(timeout=60) as c:
        r = c.get(pick["thumb_1024_url"])
    if r.status_code != 200:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    import datetime as _dt
    info = {"image": portable(str(out)), "mapillary_id": pick["id"], "url": f"https://www.mapillary.com/app/?pKey={pick['id']}",
            "captured": _dt.datetime.utcfromtimestamp((pick.get("captured_at") or 0) / 1000).date().isoformat(),
            "licence": "CC BY-SA 4.0, Mapillary contributors"}
    meta.write_text(portable(json.dumps(info)))
    return info


INSTRUCTIONS = (
    "You write two sections of a Junction Safety Brief for a city traffic engineer, from the facts given. The ranked "
    "table of fixes is produced separately by code; do not rank or list fixes yourself. record: what the official "
    "record shows (crashes over the period, who was hurt, main factors, whether the city has designated the location, "
    "past projects or treatments, whether there is a plan gap), at most 150 words. limits: the limits of the estimate "
    "(simple method, not Empirical Bayes; do not add fixes together; data gaps in this record), at most 80 words. Use "
    "only numbers in the facts. Call finish once; if it is rejected, fix the errors.")


def fixes_table(opts: dict, n: int = 8) -> str:
    """The ranked fixes, built by code from the option list so the ranking and numbers are exact."""
    rows = ["| # | FHWA Proven Safety Countermeasure | CMF Clearinghouse | Targets | Expected crashes avoided per year | "
            "Harm avoided per year | Pays for itself if it costs under | Site check |",
            "|---|---|---|---|---|---|---|---|"]
    notes = []
    for k, o in enumerate(opts.get("options", [])[:n], 1):
        rows.append(f"| {k} | {o['countermeasure']} | CMF {o['cmf_id']}: {o['cmf']} ({o['stars']}; {o['chosen_by']}) | "
                    f"{o['targets']}, {o['target_crashes_per_year']}/yr | {o['expected_crashes_avoided_per_year']} | "
                    f"${o['harm_avoided_usd_per_year']:,.0f} | ${o['break_even_cost_usd']:,.0f} | "
                    f"{'reconstruction, needs a design study; ' if o.get('scale') == 'reconstruction' else ''}"
                    f"{('verify: ' + o['verify_on_site']) if o.get('verify_on_site') else 'supported by the record'} |")
        if o.get("local_evidence"):
            notes.append(f"_{o['countermeasure']}, tested on this city's own installs: {o['local_evidence']['text']}_")
        if o.get("local_program"):
            notes.append(f"_{o['countermeasure']}, tried by this city ({o['local_program']['label']}): "
                         f"{o['local_program']['text']}; "
                         + ("this rules out the national estimate, so it is ranked lower._"
                            if o["local_program"]["contradicts_cmf"] else "too uncertain to change the ranking._"))
    h = opts.get("harm")
    head = (f"Injury crashes here cost about ${h['usd_per_year']:,.0f} a year in the U.S. DOT's official values "
            f"({h['injury_crashes_per_year']} a year at ${h['value_per_injury_crash_usd']:,.0f} each, {h['dollar_year']} dollars"
            f"{'; deaths are not valued separately' if h['deaths_in_record'] else ''}).\n\n") if h else ""
    have = "".join(f"\n\nAlready in place (city records): {x['countermeasure']}"
                   f"{' since ' + str(x['year']) if x.get('year') else ''}; not proposed again." for x in opts.get("in_place", []))
    skipped = opts.get("not_estimated") or []
    none = ("\n\nNot estimated here: " + "; ".join(f"{x['countermeasure']} ({x['reason']})" for x in skipped) + ".") \
        if skipped else ""
    repeat = "".join(f"\n\n**Tried here before:** {x['text']}" for x in opts.get("repeat_risk") or [])
    return head + "\n".join(rows) + "".join(f"\n\n{x}" for x in notes) + have + repeat + none + \
        f"\n\n_Method: {opts.get('method', '')}. Do not add fixes together._"


def write_brief(client, facts: dict, tag: str, model: str = MODELS["reader"]) -> dict:
    check = context.FactCheck(facts)
    attempts = []

    def finish(record: str, limits: str) -> dict:
        errors = check.text(record) + check.text(limits)
        attempts.append({"record": record, "limits": limits, "errors": errors})
        return {"error": "rejected by the fact checker", "errors": errors} if errors else {"ok": True}

    tool = Tool("finish", "Submit the two sections.", panel._obj({"record": {"type": "string"}, "limits": {"type": "string"}},
                                                                 ["record", "limits"]), finish)
    run = run_agent(client, model, INSTRUCTIONS, "Facts:\n" + json.dumps(facts, default=str), [tool], 6, 0.05,
                    effort="low", tag=tag, escalate_after=3)
    final = next((a for a in reversed(attempts) if not a["errors"]), None)
    text = None
    if final:
        text = (f"# Junction Safety Brief: {facts['junction']}\n\n## What the record shows\n{final['record']}\n\n"
                f"## Ranked fixes\n{fixes_table(facts['fixes'])}\n\n## Limits\n{final['limits']}\n")
    return {"brief": text, "checker_errors": [] if final else (attempts[-1]["errors"] if attempts else ["no brief"]),
            "attempts": len(attempts), "usd": round(run.usd, 5), "stopped": run.stopped}


def build(address: str | None = None, lat: float | None = None, lon: float | None = None, client=None,
          illustrate: bool = False, out_dir: Path | None = None, memo: bool = True) -> dict:
    """The full brief for one junction; the facts, the option ranking and (if asked) the illustration and memo."""
    from .countermeasures import load_cmf
    if address and (lat is None or lon is None):
        lat, lon, name = geocode(address)
    else:
        name = address or f"{lat:.5f}, {lon:.5f}"
    d = context.dossier(lat, lon)
    opts = fix_options(d, load_cmf())
    slug = "".join(ch if ch.isalnum() else "_" for ch in name.split(",")[0].lower())[:60]
    out_dir = out_dir or SETTINGS.runs_dir / "briefs" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    facts = {"junction": name, "dossier": d, "fixes": opts}
    photo = aerial(lat, lon, d.get("city"), out_dir / "aerial.jpg")
    facts["aerial_photo"] = portable(str(photo)) if photo else None
    try:  # optional: Mapillary is a free public API and fails now and then
        facts["street_photo"] = street_photo(lat, lon, out_dir / "street.jpg")
    except (RuntimeError, httpx.HTTPError) as e:
        facts["street_photo"] = None
        facts["street_photo_error"] = str(e)[:200]
    if illustrate and photo and opts["options"] and client is not None:
        facts["illustration"] = illustrate_fix(client, resolve(photo), opts["options"], out_dir, slug)
    if memo and client is not None:
        facts["brief"] = write_brief(client, {k: v for k, v in facts.items() if k not in ("aerial_photo", "street_photo")},
                                     f"brief {slug}")
    prev = out_dir / "brief.json"
    if "illustration" not in facts and prev.exists() and (out_dir / "fix.jpg").exists():  # keep an earlier drawing
        kept = json.loads(prev.read_text()).get("illustration")
        facts["illustration"] = {**kept, "image": portable(str(out_dir / "fix.jpg"))} if kept else None  # paths move with the runs dir
    prev.write_text(portable(json.dumps(facts, indent=1, default=str)))
    if facts.get("brief", {}).get("brief"):
        (out_dir / "brief.md").write_text(facts["brief"]["brief"])
    return facts


def illustrate_fix(client, photo: Path, options: list[dict], out_dir: Path, slug: str) -> dict | None:
    """Muse Image draws the highest-ranked illustratable countermeasure on the aerial photo; SAM 3.1 checks it."""
    from . import render
    specs = {i["name"]: i.get("render") for i in countermeasures.psc_items()}
    pick = next((o for o in options if specs.get(o["countermeasure"])), None)
    if pick is None:
        return None
    spec = specs[pick["countermeasure"]]
    before = cv2.imread(str(photo))
    prompt = (f"This is a top-down aerial photo of a road intersection. {spec['prompt']} "
              f"{render.KEEP}")
    edited = render.edit_image(client, before, prompt, f"brief {slug}")
    # keep only the edit around the junction (the photo's centre) and never let it remove or move a real road user:
    # SAM 3.1 masks of cars and people in the original are protected, as in the drone illustrations
    h, w = before.shape[:2]
    keep = np.zeros((h, w), bool)
    for concept in ("car", "person"):
        keep |= render._union_mask(sam_api.segment_image(client, before, concept, f"brief {slug} keep {concept}"), before.shape)
    alpha = render.disc_alpha(before.shape, (w / 2, h / 2), 0.36 * w, 0.06 * w)
    after = render.composite(before, edited, alpha, keep)
    region = alpha > 0.5
    a0 = render.concept_area(client, before, spec["check"], region, f"brief {slug} before")
    a1 = render.concept_area(client, after, spec["check"], region, f"brief {slug} after")
    side = np.hstack([before, render.label(after)])
    path = out_dir / "fix.jpg"
    cv2.imwrite(str(path), side)
    return {"countermeasure": pick["countermeasure"], "cmf_id": pick["cmf_id"], "image": portable(str(path)),
            "check_concept": spec["check"], "area_before": a0, "area_after": a1, "check_passed": bool(a1 > a0)}
