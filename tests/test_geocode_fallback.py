"""When Nominatim refuses or is down, a lookup falls back to Photon (the same OpenStreetMap data), roads only, in the
same shape, so one server's limits never block a corner."""
from nearmisslens import brief, context


def test_nominatim_refusing_falls_back_to_photon(monkeypatch):
    asked = []

    def fetch(url, params=None, data=None, timeout=90.0, attempts=6):
        asked.append(url)
        if "nominatim" in url:
            raise RuntimeError(f"{url}: HTTP 429")
        assert params["osm_tag"] == "highway"
        return {"features": [
            {"geometry": {"coordinates": [2.0, 1.0]}, "properties": {"name": "Elsewhere Road", "countrycode": "CA"}},
            {"geometry": {"coordinates": [-73.99, 40.69]}, "properties": {
                "name": "Court Street", "district": "Brooklyn", "city": "New York", "countrycode": "US", "type": "street"}},
        ]}, 0.1
    monkeypatch.setattr(context, "fetch", fetch)
    js = brief._nominatim("Court Street, Brooklyn", "us", None)
    assert asked[0].startswith("https://nominatim") and asked[1] == brief.PHOTON
    assert js == [{"lat": "40.69", "lon": "-73.99", "display_name": "Court Street, Brooklyn, New York",
                   "name": "Court Street", "addresstype": "street", "source": "photon"}]


def test_nominatim_answering_is_used_as_before(monkeypatch):
    def fetch(url, params=None, data=None, timeout=90.0, attempts=6):
        assert "nominatim" in url
        return [{"lat": "40.7", "lon": "-73.9", "display_name": "A Street, New York"}], 0.0
    monkeypatch.setattr(context, "fetch", fetch)
    assert brief._nominatim("A Street, New York", "us", None)[0]["lat"] == "40.7"
