# T32: independent intersection crash counts (2026-11-04)

I used only each city's own open-data API (plus OpenStreetMap Overpass, for node coordinates in Chicago and to check road geometry in DC). I queried them with curl and did the arithmetic with python3 on JSON files I downloaded to /tmp/claude-1000/t32counter/. I did not open, read, run or import anything in the NearMissLens tool. I only wrote these two output files.

**Window:** crash date on or after 2021-10-31 and before 2026-11-01.
**Injury crash:** at least one person injured or killed, using the dataset's own counts or severity fields.

## Results

| # | City | Intersection | Injury crashes | Total crashes | How decided |
|---|------|--------------|---------------:|--------------:|-------------|
| 1 | DC | Suitland Pkwy SE & Firth Sterling Ave SE | 5 | 22 | ADDRESS names both streets, or the point is within 30 m of DC's intersection point (MAR 906949) |
| 2 | DC | Florida Ave NW & 7th St NW | 35 | 147 | Point within 30 m of DC intersection MAR 902879 (Florida / 7th / Georgia node), or ADDRESS names Florida with 7th St or Georgia Ave |
| 3 | NYC | Flatbush Ave & Avenue U (Brooklyn) | 54 | 96 | on_street_name / cross_street_name pair names both streets |
| 4 | NYC | Hylan Blvd & Midland Ave (Staten Island) | 27 | 52 | on_street_name / cross_street_name pair names both streets |
| 5 | Seattle | Rainier Ave S & S Walker St | 9 | 17 | SDOT intersection key INTKEY = 31563 |
| 6 | Seattle | 5th Ave & Pine St | 7 | 13 | SDOT intersection key INTKEY = 29577 |
| 7 | SF | Mission St & 11th St | 14 | n/a (null) | CNN node 24421000 with the city's class "Intersection <= 20ft" |
| 8 | SF | Duboce Ave & Mission St | 28 | n/a (null) | CNN node 33027000 with class "Intersection <= 20ft" |
| 9 | Chicago | Ashland Ave & Cullerton St | 11 | 46 | Crash point within 30 m of the junction (no cross-street field) |
| 10 | Chicago | Foster Ave & Pulaski Rd | 22 | 107 | Crash point within 30 m of the junction (no cross-street field) |

The SF dataset ("Traffic Crashes Resulting in Injury") contains only injury crashes, so total crashes cannot be known from it. I left that field null rather than repeating the injury count.

## Sensitivity table

Each cell is injury crashes / total crashes. SF cells are injury crashes only. **Bold** marks the primary rule.

| # | Corner | Primary | Alternative rules |
|---|--------|---------|-------------------|
| 1 | DC Suitland / Firth Sterling | **5 / 22** | names both streets only: 5 / 20 · radius only 20 m: 2 / 18 · 30 m: 2 / 18 · 50 m: 2 / 19 · named or ≤20 m: 5 / 22 · named or ≤50 m: 5 / 23 · DC NEARESTINTKEY of this intersection: 0 / 0 (never assigned) · counting "unknown injury" persons as injured: no change |
| 2 | DC Florida / 7th | **35 / 147** | names both streets only (incl. Georgia alias): 5 / 16 · radius only 10 m: 5 / 16 · 20 m: 13 / 59 · 25 m: 25 / 110 · 30 m: 35 / 146 · 40 m: 39 / 164 · 50 m: 47 / 198 · named or ≤20 m: 13 / 60 · named or ≤50 m: 47 / 199 · NEARESTINTKEY = node and OFFINTERSECTION ≤ 30: 34 / 140 · NEARESTINTKEY = node, any offset: 43 / 182 · including unknown injuries, or dating by REPORTDATE or by UTC date: no change |
| 3 | NYC Flatbush / Avenue U | **54 / 96** | plus records naming one street but geocoded at the node (≤5 m): 54 / 101 · any record ≤20 m: 52 / 100 · ≤30 m: 54 / 114 · ≤50 m: 58 / 132 · named plus any other record ≤30 m: 56 / 116 · ≤50 m: 60 / 134 |
| 4 | NYC Hylan / Midland | **27 / 52** | plus one-street-named records at the node (≤5 m): 33 / 62 · any record ≤20 m or ≤30 m: 34 / 65 · ≤50 m: 36 / 68 |
| 5 | Seattle Rainier / Walker | **9 / 17** | injury by count fields only (ignore severity code): 8 / 17 · STATUS = Matched only: 8 / 15 · excluding rear-end: 9 / 17 · radius 20 m: 9 / 17 · 30 m: 9 / 18 · 50 m: 12 / 23 |
| 6 | Seattle 5th / Pine | **7 / 13** | count fields only: 6 / 13 · Matched only: 5 / 11 · excluding rear-end: 7 / 13 · radius 20 m or 30 m: 7 / 13 · 50 m: 8 / 20 (picks up mid-block records) |
| 7 | SF Mission / 11th | **14** | node with empty segment key (cnn_sgmt_fkey null): 12 · every record keyed to the node, mid-block included: 25 · radius 20 m: 16 · 30 m: 18 · 50 m: 23 |
| 8 | SF Duboce / Mission | **28** | node with empty segment key: 25 · adding the "Intersection Rear End <= 150ft" class: 30 · every record at the node: 32 · records naming Duboce and Mission only (≤20 ft class): 14 (all classes: 15) · radius 20 m: 30 · 30 m: 31 · 50 m: 32 |
| 9 | Chicago Ashland / Cullerton | **11 / 46** | 15 m: 6 / 29 · 20 m: 11 / 45 · 25 m: 11 / 45 · 40 m: 13 / 50 · 50 m: 13 / 54 · 30 m with intersection_related_i = Y: 6 / 24 · 30 m excluding rear-end: 10 / 43 · exact intersection address (2000 S Ashland / 1600 W Cullerton): 4 / 21 · within ±3 house numbers of it: 8 / 36 |
| 10 | Chicago Foster / Pulaski | **22 / 107** | 15 m: 4 / 24 · 20 m: 19 / 90 · 25 m: 20 / 98 · 40 m: 23 / 117 · 50 m: 24 / 127 · 30 m with intersection_related_i = Y: 16 / 43 · 30 m excluding rear-end: 18 / 65 · exact address (5200 N Pulaski / 4000 W Foster): 12 / 58 · ±3 house numbers: 19 / 92 |

The most sensitive corners are DC Florida / 7th (13 to 47 injury crashes between 20 m and 50 m), Chicago Foster / Pulaski, and NYC Hylan / Midland (27 or 33, depending on whether one-street records geocoded exactly at the node are counted).

## Per city: endpoints, queries, rules, oddities

### Washington DC
- **Endpoint:** `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24/query` (Vehicular Crash Data). The latest FROMDATE in the layer is 2026-11-02.
- **Intersection points:** `.../DCGIS_DATA/Transportation_WebMercator/MapServer/35` (Intersection Points) and `/160` (Roadway Block Intersection).
- **Queries:**
  - Spatial query, 200 m around each DC intersection point: `where=FROMDATE >= DATE '2021-10-29' AND FROMDATE < DATE '2026-11-03'`, `geometry=lon,lat`, `inSR=4326`, `distance=200`, `units=esriSRUnit_Meter`, `outFields=*`.
  - Name query: `UPPER(ADDRESS) LIKE '%SUITLAND%' AND UPPER(ADDRESS) LIKE '%FIRTH%'`, and the same pattern on MAR_ADDRESS and NEARESTINTSTREETNAME. The equivalent query was run for FLORIDA / 7TH.
  - Key query: `NEARESTINTKEY='<key>'`.
  - FROMDATE was converted to America/New_York, then the exact window was applied. Using the UTC date or REPORTDATE changed nothing.
- **Injury rule:** the sum of MAJORINJURIES_* / MINORINJURIES_* / FATAL_* (bicyclist, driver, pedestrian, passenger, other) is greater than 0. Counting UNKNOWNINJURIES_* as well changed nothing.
- **At-intersection rule:** DC has no cross-street field and no at-intersection class, and only a minority of records name both streets in ADDRESS. Most MPD crashes are geocoded to a nearby MAR property address. I therefore counted a record if its point is within 30 m of DC's own intersection point, or if its ADDRESS names both streets (this catches mis-geocoded records).
- **Suitland / Firth Sterling oddities:**
  - **Divided parkway, two nodes.** Suitland Parkway is divided here, so OSM has two at-grade nodes about 14 m apart. DC's intersection point sits between them. OSM shows no bridge tags within 80 m.
  - **Key never used.** DC's intersection key c69def71... (Roadway Block Intersection, GRADE 0) is never assigned as NEARESTINTKEY. Records that name the intersection are keyed to Sumner Rd & Firth Sterling, 123–143 m away, or to "Route not found", even though their points sit within 1–4 m of the node.
  - **Mis-geocoded records.** Two injury records named "SUITLAND PKWY SE & FIRTH STERLING AVE SE" are geocoded to 427 New Jersey Ave NW, downtown. Two more named records sit 89 m and 143 m away. I counted all four by name. Without them the count is 2 injury / 18.
  - Two "INTERSTATE 295" records (both non-injury) are geocoded within 9 m of the node. They are included under the radius rule.
- **Florida / 7th oddities:**
  - **Three streets, one node.** 7th St NW becomes Georgia Ave NW at Florida Ave. DC's single intersection point (MAR 902879, key aa205ed4...) covers 7th, Georgia and Florida, so records reading "Georgia Ave & Florida Ave" are the same intersection.
  - **Corner-address geocoding.** Most crashes are geocoded to corner properties, which is why the count is very sensitive to radius. Distances from the node: 2001 Georgia Ave at 16 m, 651 Florida Ave at 21 m, 1915 7th St at 22 m, 1915½ 7th St at 25 m, 649 Florida Ave at 26 m, 2000 Georgia Ave at 28–29 m, 2002 Georgia Ave and 1911 7th St at about 35 m, 705 Florida Ave at 41 m.

### New York City
- **Endpoint:** `https://data.cityofnewyork.us/resource/h9gi-nx95.json`. The latest crash_date is 2026-10-31.
- **Named query:** `$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND ((upper(on_street_name) like '%FLATBUSH%' AND upper(cross_street_name) like '%AVENUE U%') OR (upper(on_street_name) like '%AVENUE U%' AND upper(cross_street_name) like '%FLATBUSH%'))`. The same form was used with HYLAN / MIDLAND. All matches are in the right borough.
- **Radius query:** `within_circle(location, lat, lon, 80)` around the node coordinate NYPD itself uses for named records: 40.60981,-73.9225 (Flatbush) and 40.577946,-74.102325 (Hylan).
- **Injury rule:** number_of_persons_injured + number_of_persons_killed > 0.
- **Rule:** the on/cross pair names both streets. Flatbush includes one fatality (2025-05-25), and 2 of the 96 named records have no coordinates.
- **Hylan oddity:** 10 records give only one street name (on_street_name only) but are geocoded exactly at the intersection node, 0–0.4 m away; 6 of them are injury crashes. They are probably intersection crashes with the cross street dropped. I excluded them because the record does not name both streets; including them gives 33 / 62.
- **Flatbush:** the equivalent one-street-at-node records number 5, none of them injury crashes.

### Seattle
- **Endpoint:** `https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/SDOT_Collisions_All_Years_1/FeatureServer/0/query`. The latest INCDATE is 2026-10-26.
- **Intersection keys:** taken from `.../SDOT_Intersections/FeatureServer/0`.
  - COMPKEY 31563, "RAINIER AVE S AND S WALKER ST", 47.583656,-122.302199.
  - COMPKEY 29577, "5TH AVE AND PINE ST", 47.611672,-122.336484.
- **Query:** `where=INTKEY=<key> AND INCDATE >= DATE '2021-10-31' AND INCDATE < DATE '2026-11-01'`. INCDATE is stored as local midnight (07:00/08:00 UTC), so the DATE bounds give exactly the local-date window. I also ran a 150 m spatial query to check for records missing the key.
- **Injury rule:** MAXSEVERITYCODE in (2, 2b, 3), or INJURIES + SERIOUSINJURIES + FATALITIES > 0.
  - At each corner, one record has severity "Injury Collision" but zero injury counts: Rainier 2022-07-22 and 5th/Pine 2022-09-03. I counted them as injury crashes because the severity field says so.
- **Rule:** INTKEY equal to the city's intersection key. Every keyed record has JUNCTIONTYPE "At Intersection (intersection related)". The LOCATION search found no records naming the intersection without the key.
- **Oddities:**
  - **Rainier / Walker:** there is no offset junction here (S Walker St crosses Rainier at one node). 23rd Ave S meets Rainier at a separate signalised node about 112 m away (INTKEY 31562), which I did not include.
  - **Block records:** these are placed at the middle of their block (28 m and more from the node), so the radius counts only move at 50 m.
  - **5th / Pine:** a downtown grid corner with no complication.

### San Francisco
- **Endpoint:** `https://data.sfgov.org/resource/ubvf-ztfx.json` (Traffic Crashes Resulting in Injury). The latest collision_date is 2026-08-31 (data_as_of 2026-10-07), so the last two months of the window are not in the data yet.
- **Queries:**
  - Name query (to find the node): `$where=collision_date >= '2021-10-31' AND collision_date < '2026-11-01' AND ((upper(primary_rd) like '%MISSION%' AND upper(secondary_rd) like '%11TH%') OR ...)`
  - Node query: `$where=... AND cnn_intrsctn_fkey='24421000'` (and `'33027000'`).
  - Radius query: `within_circle(point, lat, lon, 60)`.
- **Node check:** confirmed against the street centerline dataset 3psu-pn9h (segments with f_node_cnn or t_node_cnn equal to the node).
- **Rule:** cnn_intrsctn_fkey = the node and `intersection = 'Intersection <= 20ft'`, which is the city's own at-intersection class. Every record has number_injured + number_killed > 0.
- **Duboce / Mission oddity:** CNN node 33027000 is a single 5-leg node joining Mission St, Duboce Ave (west), 13th St (east; Duboce continues as 13th), Otis St and the US-101 northbound ramp, under the Central Freeway. Its 28 at-intersection records name the streets in three ways:
  - Duboce & Mission: 14.
  - 13th & Mission: 12.
  - 13th & Otis: 2.

  Because the city codes all of them to the same node, I counted all 28. Counting only records that name Duboce and Mission gives 14.
- **Mission / 11th:** 11 of the 25 records keyed to the node are "Midblock > 20ft" (up to 185 ft away along Mission or 11th) and are excluded. One record that names Mission & 11th is keyed to a different node (24364000) and is also excluded.

### Chicago
- **Endpoint:** `https://data.cityofchicago.org/resource/85ca-t3if.json`. The latest crash_date is 2026-11-03.
- **Queries:**
  - Radius query: `$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, lat, lon, 150)`; distances were then computed locally.
  - Address cross-check: `street_name='ASHLAND AVE' AND street_no between 1940 and 2060` (and similar for the other legs), filtered on street_direction S / W / N / W.
- **Node coordinates (OSM Overpass, shared nodes of the two named ways):**
  - Ashland / Cullerton: two nodes 10 m apart (41.8550774,-87.6660159 and 41.8550631,-87.6661332); I used their midpoint, 41.85507,-87.66607.
  - Foster / Pulaski: node 158736274, 41.9755275,-87.7282337.
- **Injury rule:** injuries_total + injuries_fatal > 0.
- **Rule:** Chicago records give one street and a house number, with no cross street, so I used crash points within 30 m of the node.
- **Geocoding:** Chicago places points from the reported address, offset to the side of the street. Even the exact intersection address (e.g. 2000 S Ashland, 1600 W Cullerton) lands 13–16 m from the node, which is why I used 30 m rather than 20 m.
- **Oddities:**
  - **Mis-placed addresses:** some 1950–1959 S Ashland addresses are geocoded at the corner, 13 m away. All records in the address range have coordinates.
  - **Fatalities:** Ashland / Cullerton includes one fatal crash, and Foster / Pulaski includes one within 20 m.
  - **Street direction:** an address query without street_direction would wrongly pull in 2000 N Ashland, so the direction filter matters.
  - **Officer flag:** intersection_related_i (the officer's flag that the intersection played a role) is set on only about half the crashes within 30 m. I did not use it as the primary rule because the dataset documents it as a judgement about cause, not about location.
