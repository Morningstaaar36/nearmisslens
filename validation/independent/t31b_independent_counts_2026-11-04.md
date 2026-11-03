# T31b: independent intersection crash counts (2026-11-04)

Window: crash date on or after 2021-10-31 and before 2026-11-01.
Sources: each city's own open-data API only, queried with curl on 2026-11-04. I did not open or run anything in the NearMissLens tool.
"Injury crash" means a crash record with at least one person injured or killed, using each dataset's own injury/fatality counts or severity field (details per city below).

## Results

| # | city | intersection | injury crashes at the intersection | total crashes | how decided (one line) |
|---|------|--------------|-----------------------------------:|--------------:|------------------------|
| 1 | dc | Alabama Avenue Southeast & Stanton Road Southeast | 32 | 116 | DC's own NEARESTINTKEY for this node, with OFFINTERSECTION ≤ 30 m |
| 2 | dc | Southeast Freeway & 11th Street Southeast | 7 | 12 | No at-grade crossing (11th St SE goes over I-695). Counted DC's two "11th St SE & Southeast Blvd SE" nodes, ≤ 30 m, without 58 records that only say "11TH STREET SE" and share one default point |
| 3 | nyc | Avenue of the Americas & West 23 Street (Manhattan) | 26 | 45 | on_street_name and cross_street_name are the two streets, either order |
| 4 | nyc | 9 Street & 5 Avenue (Brooklyn, Park Slope) | 12 | 20 | on_street_name and cross_street_name are the two streets, either order, borough BROOKLYN |
| 5 | seattle | Martin Luther King Jr Way South & South Othello Street | 14 | 39 | ADDRTYPE='I' at both SDOT INTKEYs (MLK west roadway 34562 and east roadway 486567) |
| 6 | seattle | South Oregon Street & 35th Avenue South | 0 | 0 | ADDRTYPE='I' at INTKEY 32720. No record in the window |
| 7 | sf | Polk Street & Eddy Street | 17 | n/a (injury-only data) | primary_rd and secondary_rd are the two streets, with intersection field = "Intersection <= 20ft" (CNN 25176000) |
| 8 | sf | 5th Street & Bryant Street | 19 | n/a (injury-only data) | primary_rd and secondary_rd are the two streets, with intersection field = "Intersection <= 20ft" (CNN 23889000) |
| 9 | chicago | Kilbourn Avenue & Belmont Avenue | 7 | 37 | Geocoded crash point within 30 m of the city centerline node (Chicago has no cross-street field) |
| 10 | chicago | Ridge Avenue & Hollywood Avenue | 16 | 154 | Offset junction with 2 centerline nodes 80 m apart. Counted crash points within 30 m of either node |

## Sensitivity: how much each count depends on the rule

| # | alternative rule | injury | total |
|---|------------------|-------:|------:|
| 1 | OFFINTERSECTION ≤ 20 m / ≤ 50 m / any distance (same key) | 24 / 32 / 38 | 84 / 133 / 154 |
| 2 | including the 58 records that only say "11TH STREET SE" (OFFINTERSECTION 21.1 m) | 27 | 70 |
| 3 | adding records that name only one of the two streets but are geocoded to the exact intersection node | 28 | 54 |
| 5 | injury counted from person counts (INJURIES+SERIOUSINJURIES+FATALITIES>0) instead of severity | 13 | 39 |
| 7 | also counting SF's "Intersection Rear End <= 150ft" category | 21 | n/a |
| 7 | every record carrying the intersection's CNN key (includes "Midblock > 20ft") | 28 | n/a |
| 8 | also counting "Intersection Rear End <= 150ft" (that record carries a different CNN key, 23888000) | 20 | n/a |
| 9 | radius 20 m / 40 m / 50 m | 6 / 9 / 9 | 33 / 41 / 45 |
| 10 | radius 20 m / 40 m / 50 m (union of both nodes) | 11 / 20 / 26 | 91 / 180 / 203 |
| 10 | 30 m around the main node only (east Hollywood leg, node 2592) / around the west node only (node 98) | 6 / 10 | 93 / 61 |

## Per city: endpoints, exact queries, rule

The queries are written in `curl -G --data-urlencode` form, with parameters shown unencoded.

### San Francisco: `ubvf-ztfx` (Traffic Crashes Resulting in Injury)

`data.sfgov.org` now redirects (301) to `https://data.sf.gov/resource/ubvf-ztfx.json`. Data as of 2026-10-07. The latest collision is 2026-08-31, so the last two months of the window are not in the data yet.

- Polk & Eddy:
  `https://data.sf.gov/resource/ubvf-ztfx.json?$where=collision_datetime >= '2021-10-31' AND collision_datetime < '2026-11-01' AND ((upper(primary_rd) like '%POLK%' AND upper(secondary_rd) like '%EDDY%') OR (upper(primary_rd) like '%EDDY%' AND upper(secondary_rd) like '%POLK%'))&$limit=5000`
- 5th & Bryant: the same query with `'%5TH%'` and `'%BRYANT%'`. This matches the city's `05TH ST`, and also `25TH ST` and `15TH ST`, which I dropped by hand.
- Cross-check by intersection key: `...?$where=collision_datetime >= '2021-10-31' AND collision_datetime < '2026-11-01' AND cnn_intrsctn_fkey='25176000'` (and `'23889000'`).
- Rule: the record names both streets in either order, and its own `intersection` field is `Intersection <= 20ft`. Every such record also carries the expected CNN intersection key and has `distance` ≤ 20 ft.
- Why: SF records a distance and an at-intersection/mid-block class for every crash. `<= 20ft` is SF's own "at the intersection" class.
- Injury: every record in this dataset is an injury or fatal crash, so a total-crash count cannot be computed from it.
- Polk/Eddy: CNN 25176000 has 28 records in the window: 17 `<= 20ft`, 4 `Rear End <= 150ft`, 7 `Midblock > 20ft`.
- 5th/Bryant: CNN 23889000 has 20 records: 19 `<= 20ft` and 1 midblock at 25 ft. Two more name-matched records sit on other CNNs:
  - 230402761, Rear End at 119 ft, CNN 23888000.
  - 220604513, a fatal crash recorded midblock 158 ft north, CNN 50072000.
  Neither one is counted.

### New York: `h9gi-nx95` (Motor Vehicle Collisions – Crashes)

Max crash_date is 2026-10-31.

- 6 Av / W 23 St:
  `https://data.cityofnewyork.us/resource/h9gi-nx95.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND (upper(on_street_name) like '%23%' OR upper(cross_street_name) like '%23%') AND (upper(on_street_name) like '%AMERICAS%' OR upper(cross_street_name) like '%AMERICAS%' OR upper(on_street_name) like '6 AV%' OR upper(cross_street_name) like '6 AV%' OR upper(on_street_name) like '6TH AV%' OR upper(cross_street_name) like '6TH AV%')&$limit=5000`
  I dropped one Queens hit, `6 AVENUE | 123 STREET`. The 45 kept records use the forms W 23 ST, WEST 23 STREET and 23 STREET together with AVENUE OF THE AMERICAS or 6 AVENUE.
- Radius check: `...&$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, 40.742912, -73.992805, 40)`
- 9 St / 5 Av, Brooklyn:
  `...?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND (upper(on_street_name) like '%9%' OR upper(cross_street_name) like '%9%') AND (upper(on_street_name) like '%5%AV%' OR upper(cross_street_name) like '%5%AV%') AND (borough='BROOKLYN' OR borough IS NULL)&$limit=5000`
  Then I kept only exact names: street in {9 STREET, 9 ST, 9TH STREET, 9TH ST} and avenue in {5 AVENUE, 5 AVE, 5TH AVENUE, 5TH AVE}, borough BROOKLYN. That leaves 20 records.
  Radius check: `within_circle(location, 40.66917, -73.98631, 40)`.
- Rule: on_street_name and cross_street_name name the two streets, in either order.
- Why: NYPD records the cross street, so a record that names both streets is an intersection crash. Records with only an `off_street_name` address are address-located and are not counted. The only such records within 40 m are 707 Avenue of the Americas and 437 5 Ave.
- Injury: number_of_persons_injured + number_of_persons_killed > 0.

### Chicago: `85ca-t3if` (Traffic Crashes – Crashes)

Max crash_date is 2026-11-03.

- This dataset has no cross-street field, only street_no + direction + street_name, plus coordinates geocoded from that address. `intersection_related_i` is blank in most records, so it cannot be used to decide.
- I took the intersection node from the city's own street-centerline table, `pr57-gg9e`:
  `https://data.cityofchicago.org/resource/pr57-gg9e.json?$where=(street_nam like '%BELMONT%' AND (f_cross like '%KILBOURN%' OR t_cross like '%KILBOURN%')) OR (street_nam like '%KILBOURN%' AND (f_cross like '%BELMONT%' OR t_cross like '%BELMONT%')) OR (street_nam like '%HOLLYWOOD%' AND (f_cross like '%RIDGE%' OR t_cross like '%RIDGE%')) OR (street_nam like '%RIDGE%' AND (f_cross like '%HOLLYWOOD%' OR t_cross like '%HOLLYWOOD%'))`
  plus `...?$where=fnode_id in ('98','2592','26381') OR tnode_id in ('98','2592','26381')`.
  - Belmont/Kilbourn: node 26381 at (41.938928, -87.739498). It is a single node where all four legs meet.
  - Ridge/Hollywood is a dog-leg with two nodes 80 m apart:
    - node 2592 at (41.985090, -87.662462): the east Hollywood leg (1233–1299 W) meets Ridge at ~5674 N.
    - node 98 at (41.985547, -87.663205): Ridge 5700 N, Hollywood 1300 W and Wayne Ave 5700 N.
    - The Ridge segment 5674–5698 N joins the two nodes.
- Crash queries (radius 60 m, then distance bands computed locally):
  `https://data.cityofchicago.org/resource/85ca-t3if.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, 41.93892844749904, -87.73949804303113, 60)&$limit=5000`
  The same query was run with `41.98509045602461, -87.66246163765467` and `41.985547147991355, -87.66320495652143`.
  Address cross-check: `...AND ((street_name like 'BELMONT%' AND street_no >= 4400 AND street_no <= 4600) OR (street_name like 'KILBOURN%' AND street_no >= 3100 AND street_no <= 3300))`.
  Records with null coordinates on the junction blocks: none.
- Rule: the crash's geocoded point is within 30 m (~100 ft) of the centerline node. For Ridge/Hollywood, within 30 m of either node.
- Why: an officer records an intersection crash at a corner address (e.g. 4500 W Belmont, 4501 W Belmont, 4459 W Belmont, 3200 N Kilbourn). Those address points sit 12–17 m off the node. A 30 m radius takes in all four corner addresses and stops before the next ~40 m of block. This is a judgment call, so the sensitivity table shows 20/40/50 m.
- Injury: injuries_total + injuries_fatal > 0. This counts "reported, not evident" injuries.
- Kilbourn/Belmont injury crashes within 30 m:
  - 2021-12-25, 4501 W Belmont
  - 2023-12-23, 3200 N Kilbourn, incapacitating
  - 2024-01-18, 4500 W Belmont
  - 2025-02-15, 4459 W Belmont
  - 2025-10-09, 4501 W Belmont
  - 2026-05-23, 4502 W Belmont, **fatal**
  - 2026-10-10, 4504 W Belmont (22 m)

### Washington DC: "Crashes in DC"

ArcGIS MapServer layer `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24/query` ("Vehicular Crash Data").

- DC gives every crash `NEARESTINTKEY` (the key of the nearest intersection), `NEARESTINTSTREETNAME` and `OFFINTERSECTION`.
  - `OFFINTERSECTION` is the distance from that intersection along the route, in metres. It tracks the computed distances (e.g. 115 vs 124 m), so the unit is metres, not feet.
- Date field: `REPORTDATE` holds the crash time. `FROMDATE` is later, the report-entry time.
- Alabama/Stanton, by name:
  `where=REPORTDATE >= TIMESTAMP '2021-10-31 00:00:00' AND REPORTDATE < TIMESTAMP '2026-11-01 00:00:00' AND ((UPPER(ADDRESS) LIKE '%ALABAMA%' AND UPPER(NEARESTINTSTREETNAME) LIKE '%STANTON%') OR (UPPER(ADDRESS) LIKE '%STANTON%' AND UPPER(NEARESTINTSTREETNAME) LIKE '%ALABAMA%'))&outFields=*&returnGeometry=false&f=json&resultRecordCount=2000`
  This showed that the node key is `7b9b6129091917f1959c1d610cfbb024`. Records at "1804/1811 Alabama" belong to the separate Stanton **Terrace** node (`e27a28…`) and are not counted.
- Alabama/Stanton, by key:
  `where=REPORTDATE >= TIMESTAMP '2021-10-31 00:00:00' AND REPORTDATE < TIMESTAMP '2026-11-01 00:00:00' AND NEARESTINTKEY='7b9b6129091917f1959c1d610cfbb024'`
  This returns 154 records with 154 unique CCNs. 116 of them have OFFINTERSECTION ≤ 30.
  The address used most often, 1576 Alabama Ave SE (16.9 m), is the MAR address DC assigns to "Alabama Ave SE & Stanton Rd SE" itself.
- Southeast Freeway / 11th St SE:
  - The crash table has no street called "Southeast Freeway". The freeway is `I695`.
  - DC's own Intersection Points layer (`.../Transportation_WebMercator/MapServer/35/query`, `where=STREET_1_FULL LIKE '11TH STREET SE%' OR ...`) has a record "11TH STREET SE OVER INTERSTATE 695". Its type is OVERPASS and it has no intersection key, at 38.87787, -76.99154.
  - So the two do **not** cross at grade.
  - What DC places at the junction are two at-grade nodes named "11TH STREET SE AND SOUTHEAST BOULEVARD SE". Southeast Blvd is the former freeway alignment east of 11th St, now downgraded.
    - `4701686106fa72754f7b045984cf0f62` at 38.87808
    - `cbeccfda5c67372f33e05ee4545a3faa` at 38.87766
  - Query: `where=REPORTDATE >= TIMESTAMP '2021-10-31 00:00:00' AND REPORTDATE < TIMESTAMP '2026-11-01 00:00:00' AND NEARESTINTKEY IN ('4701686106fa72754f7b045984cf0f62','cbeccfda5c67372f33e05ee4545a3faa')` returns 72 records.
  - Freeway-name search: `UPPER(ADDRESS) LIKE '%FREEWAY%' OR '%FWY%' OR '%I695%' ...`. Only one hit is at this junction: "11TH STREET BRIDGE SE I695 EB", which is already inside the key set.
- Rule: NEARESTINTKEY is the junction's key, and OFFINTERSECTION ≤ 30 m.
  - For #2 I also excluded 58 records whose ADDRESS is just "11TH STREET SE". They have no block number and no cross street. All 58 share one identical MPD coordinate (38.877463, -76.992062) and have no MAR address. That is a default street-level geocode, so their real position on 11th St SE (which includes the bridges) is unknown.
  - Other generic "11TH STREET SE" records elsewhere get other default points, which supports reading this one as a default too.
- Injury: the sum of all MAJORINJURIES*, MINORINJURIES* and FATAL* fields > 0, covering drivers, passengers, pedestrians, bicyclists and other. Adding UNKNOWNINJURIES* changes nothing.
- #2 counted records:
  - 8 at "11th St SE & Southeast Blvd SE"
  - 2 at "11th St SE & K St SE", which DC keys to this node at 0.7 m and 4.0 m
  - 1 on the I-695 EB bridge at 15.8 m
  - 1 at "L St SE & Southeast Blvd SE"
  - Injury crashes: 2022-04-28, 2022-08-25 (I-695 EB), 2022-10-03, 2022-10-25, 2022-11-02, 2024-12-25 and 2026-10-10.

### Seattle: SDOT Collisions All Years

Current endpoint: `https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/SDOT_Collisions_All_Years_1/FeatureServer/0/query`. The older `SDOT_Collisions_All_Years` URL returns "Invalid URL". Max INCDATE is about 2026-10-26.

- Name search, all years: `where=LOCATION LIKE '%KING%' AND LOCATION LIKE '%OTHELLO%'` and `where=LOCATION LIKE '%OREGON%' AND LOCATION LIKE '%35TH AVE S%'`.
  - MLK is split around the light-rail median into `M L KING JR WR WAY S` and `M L KING JR ER WAY S`, so there are two intersection keys: 34562 and 486567.
  - 35th Ave S & S Oregon St is INTKEY 32720.
- Counts:
  `where=(INTKEY IN (34562,486567) OR LOCATION = 'S OTHELLO ST BETWEEN M L KING JR WR WAY S AND M L KING JR ER WAY S') AND INCDATE >= TIMESTAMP '2021-10-31 00:00:00' AND INCDATE < TIMESTAMP '2026-11-01 00:00:00'&outFields=*`
  `where=INTKEY = 32720 AND INCDATE >= TIMESTAMP '2021-10-31 00:00:00' AND INCDATE < TIMESTAMP '2026-11-01 00:00:00'`
  - The median block between the two MLK roadways has 0 records in the window.
- Spatial checks: `geometry=-122.2812,47.53705&inSR=4326&distance=60&units=esriSRUnit_Meter` and `geometry=-122.288905,47.562821&distance=120`.
  - Near MLK/Othello, nothing else is coded as this intersection.
  - Near Oregon/35th, the only records are at Rainier Ave S & S Oregon St (INTKEY 32721, 80 m east) and on Rainier/Letitia blocks. None are at 32720.
- Rule: ADDRTYPE = 'I' and INTKEY is the intersection's key. JUNCTIONTYPE for all 39 MLK records is "At Intersection (intersection related)".
- Injury: MAXSEVERITYDESC ∈ {Injury, Serious Injury, Fatality} Collision. 14 records qualify: 13 with INJURIES ≥ 1, plus one Injury Collision on 2026-06-08 (bicycle/scooter struck) whose person counts are 0.
  - There is one Serious Injury pedestrian crash, on 2022-12-25.
- #6: INTKEY 32720 has only 7 records in all years, and the last is 2021-04-15. Nothing is in the window. Block records next to it ended 2021-10-01.

## Doubts

1. **Chicago (#9, #10) is the softest.** There is no cross-street field, so "at the intersection" rests on a radius around address-geocoded points. The 30 m choice is mine, and the counts move with the radius (see the sensitivity table).
   - For #9, the 2026-05-23 fatal crash is at 4502 W Belmont (17 m) with no intersection flag. It is included.
2. **Ridge & Hollywood (#10) is two junctions.** The city centerline shows an offset (dog-leg) junction, 80 m apart, with Wayne Ave also meeting at the west node. I counted both. If only the main signalized node is meant (east Hollywood leg, 2592), the result is 6 injury / 93 total.
3. **DC #2: the streets do not cross.** 11th St SE passes over I-695, and DC has no "Southeast Freeway" street name. My count is what DC keys to the "11th St SE & Southeast Blvd SE" nodes. The biggest swing is the 58 "11TH STREET SE"-only records at one default point: excluding them gives 7/12, including them gives 27/70. Most of those are from 2024–2026, when MPD addresses apparently became street-only more often. A tool that keys on DC's NEARESTINTKEY with a distance cutoff ≥ 22 m will include them.
4. **DC distance cutoff (#1).** 30 m is a judgment call. 20 m gives 24/84, and any distance under the same key gives 38/154.
5. **SF has no non-injury crashes**, so total crashes cannot be computed. "Intersection Rear End <= 150ft" is SF's own intersection-related class. Counting it moves Polk/Eddy from 17 to 21 and 5th/Bryant from 19 to 20.
   - SF data stop on 2026-08-31, two months before the window ends.
6. **NYC #3.** Nine more records name only one street but sit at the exact intersection-node coordinate. Two of them are injury crashes, on 2021-11-24 and 2023-11-05. Counting them gives 28/54.
   - Records without coordinates but with both street names are counted in the main result.
7. **Seattle #5.** One "Injury Collision" record has zero injured persons in its counts. Counting by persons gives 13 instead of 14.
   - Seattle #6 is a true zero in the city data. The data are not stale overall: the dataset runs to about 2026-10-26.
8. **Recent reports lag** in every dataset. Crashes in the last weeks before 2026-10-31 may not be posted yet, and Chicago and DC records get revised.
9. **Time zones.** DC REPORTDATE and Seattle INCDATE are stored in UTC. Seattle dates are local midnight (07:00 UTC). No counted record falls close enough to either window edge for the time zone to change a count. The one DC record from 2021-10-30 local time is excluded.
