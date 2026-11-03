# T31 independent crash counts at 10 intersections (2026-11-04)

Independent audit. Sources: only each city's public open-data API, queried with curl on 2026-11-04. I did not read or run anything in the nearmisslens tool.

- **Window:** crash date on or after 2021-10-31 and before 2026-11-01.
- **Injury crash:** at least one person injured or killed, using the dataset's own injury and fatality count fields.
- **Data currency:** the latest crash date in each dataset when queried was SF 2026-08-31, NYC 2026-10-31, Chicago 2026-11-03, Seattle about 2026-10-25, and DC about 2026-11-01. SF's window is therefore about two months short.

## Results

| # | city | intersection | injury crashes at the intersection | total crashes at the intersection | how decided (one line) |
|---|---|---|---|---|---|
| 1 | dc | Stanton Rd SE & Sheridan Rd SE | **40** (south node 36 + north node 4) | **158** (147 + 11) | DC has two distinct Stanton/Sheridan intersections. Rule: `NEARESTINTKEY` = the node's key and `OFFINTERSECTION` ≤ 30 m. Per-node numbers are given. |
| 2 | dc | Pennsylvania Ave SE & L'Enfant Sq SE | **41** | **105** | `NEARESTINTKEY` = b251534b… (the Penn/L'Enfant Sq node) and `OFFINTERSECTION` ≤ 30 m. Records with explicit intersection text only: 3 / 7. |
| 3 | nyc | Cross Bay Blvd & Woodhaven Blvd (Queens) | **26** | **47** | Woodhaven becomes Cross Bay at the Rockaway Blvd junction. Rule: crashes the NYPD geocoded to that node (within 15 m) and named on Woodhaven, Cross Bay or Rockaway Blvd. The literal "Woodhaven × Cross Bay" street pair matches only 1 / 1. |
| 4 | nyc | Glenwood Rd & Ralph Ave (Brooklyn) | **19** | **32** | `on_street_name`/`cross_street_name` = Glenwood & Ralph (31), plus 1 record naming Glenwood with no cross street at the exact node coordinate. |
| 5 | seattle | Elliott Ave W & W Harrison St | **8** | **10** | `ADDRTYPE`='Intersection', `INTKEY` = 28648, `LOCATION` "ELLIOTT AVE W AND W HARRISON ST". |
| 6 | seattle | Rainier Ave S & 25th Ave S | **1** | **4** | `ADDRTYPE`='Intersection', `INTKEY` = 31466, `LOCATION` "25TH AVE S AND RAINIER AVE S". |
| 7 | sf | Mission St & 14th St | **16** | n/a (the dataset holds injury crashes only, so 16 records) | `cnn_intrsctn_fkey` = 24372000 and the dataset's `intersection` field says "Intersection <= 20ft" (14) or "Intersection Rear End <= 150ft" (2). |
| 8 | sf | 16th St & Julian Ave | **3** | n/a (injury-only dataset, 3 records) | `cnn_intrsctn_fkey` = 24181000 and `intersection` = "Intersection <= 20ft". |
| 9 | chicago | Foster Ave & Pulaski Rd | **24** | **107** | No cross-street field exists. Rule: `street_name` is Foster or Pulaski and the city's address-geocoded point is within 30 m of the intersection. |
| 10 | chicago | Milwaukee Ave & Division St | **17** | **55** | Same rule: `street_name` is Milwaukee or Division and the point is within 30 m of the Milwaukee/Division crossing. Ashland Ave records are excluded. |

## Sensitivity: the same intersections under nearby rules (injury / total)

| # | intersection | stricter | primary (above) | looser |
|---|---|---|---|---|
| 1 | DC Stanton & Sheridan, south node (a5c0bf…) | ≤ 20 m: 36 / 145; without the 82 "2339 Sheridan Rd" fallback records: 18 / 65 | ≤ 30 m: 36 / 147 | ≤ 50 m: 37 / 155 |
| 1 | DC Stanton & Sheridan, north node (7867d8…) | ≤ 20 m: 4 / 8 | ≤ 30 m: 4 / 11 | ≤ 50 m: 8 / 21 |
| 2 | DC Penn & L'Enfant Sq | intersection text only (offset < 1 m): 3 / 7; ≤ 20 m: 33 / 73 | ≤ 30 m: 41 / 105 | ≤ 50 m: 50 / 131 |
| 3 | NYC Cross Bay & Woodhaven | literal name pair: 1 / 1 | node: 26 / 47 | — |
| 4 | NYC Glenwood & Ralph | name pair only: 19 / 31 | 19 / 32 | — |
| 5 | Seattle Elliott & Harrison | — | 8 / 10 | adding adjacent block segments: +5 / +10 (only 1 of them is coded "Mid-Block (but intersection related)", and it is a non-injury crash) |
| 6 | Seattle Rainier & 25th | — | 1 / 4 | adding adjacent block segments: +7 / +22 (3 are "intersection related", none of them injury crashes) |
| 7 | SF Mission & 14th | "Intersection <= 20ft" only: 14 | 16 | every record keyed to the CNN, including midblock records up to 275 ft away: 22 |
| 8 | SF 16th & Julian | — | 3 | every record keyed to the CNN: 4 (one midblock record 30 ft north) |
| 9 | Chicago Foster & Pulaski | grid address only (4000 W Foster / 5200 N Pulaski): 12 / 58; ≤ 15 m: 14 / 66; ≤ 20 m: 17 / 69 | ≤ 30 m: 24 / 107 | ≤ 50 m: 25 / 130 |
| 10 | Chicago Milwaukee & Division | grid address only (1200 N Milwaukee): 5 / 13; ≤ 15 m: 9 / 31; ≤ 20 m: 11 / 39 | ≤ 30 m: 17 / 55 | ≤ 50 m: 21 / 89 |

## Per city: queries and rules

The URLs below are shown unencoded for readability. They were sent with `curl -G --data-urlencode`.

### San Francisco: Traffic Crashes Resulting in Injury (ubvf-ztfx)

`data.sfgov.org` now redirects to `data.sf.gov`.

```
https://data.sf.gov/resource/ubvf-ztfx.json?$where=collision_date >= '2021-10-31' AND collision_date < '2026-11-01' AND ((upper(primary_rd) like '%MISSION%' AND upper(secondary_rd) like '%14TH%') OR (upper(secondary_rd) like '%MISSION%' AND upper(primary_rd) like '%14TH%') OR (upper(primary_rd) like '%16TH%' AND upper(secondary_rd) like '%JULIAN%') OR (upper(secondary_rd) like '%16TH%' AND upper(primary_rd) like '%JULIAN%'))&$limit=5000
https://data.sf.gov/resource/ubvf-ztfx.json?$where=collision_date >= '2021-10-31' AND collision_date < '2026-11-01' AND cnn_intrsctn_fkey in ('24372000','24181000','24374000')&$limit=5000
https://data.sf.gov/resource/ubvf-ztfx.json?$select=max(collision_date),min(collision_date),count(*)
```

**Rule.** The record must be keyed to the intersection's CNN in `cnn_intrsctn_fkey`: 24372000 is Mission/14th and 24181000 is 16th/Julian. The two queries above returned the same records, so no spelling variants were missed. The dataset's own `intersection` field must also classify the crash as an intersection crash: "Intersection <= 20ft" or "Intersection Rear End <= 150ft". Records classified "Midblock > 20ft" are excluded even when keyed to the CNN.

Every record in this dataset is an injury crash (`number_injured` + `number_killed` ≥ 1 for all of them), so a total-crash count is not available from it. One Julian Ave record 205 ft north is keyed to a different CNN (24374000) and is excluded.

### New York: Motor Vehicle Collisions - Crashes (h9gi-nx95)

```
https://data.cityofnewyork.us/resource/h9gi-nx95.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND ((upper(on_street_name) like '%GLENWOOD%' AND upper(cross_street_name) like '%RALPH%') OR (upper(cross_street_name) like '%GLENWOOD%' AND upper(on_street_name) like '%RALPH%'))&$limit=5000
https://data.cityofnewyork.us/resource/h9gi-nx95.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, 40.634483, -73.91885, 150)&$limit=5000
https://data.cityofnewyork.us/resource/h9gi-nx95.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND ((upper(on_street_name) like '%CROSS BAY%' AND upper(cross_street_name) like '%WOODHAVEN%') OR (upper(cross_street_name) like '%CROSS BAY%' AND upper(on_street_name) like '%WOODHAVEN%'))&$limit=5000
https://data.cityofnewyork.us/resource/h9gi-nx95.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, 40.6807, -73.84464, 400)&$limit=5000
https://data.cityofnewyork.us/resource/h9gi-nx95.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND ((upper(on_street_name) like '%ROCKAWAY B%' AND (upper(cross_street_name) like '%WOODHAVEN%' OR upper(cross_street_name) like '%CROSS BAY%')) OR (upper(cross_street_name) like '%ROCKAWAY B%' AND (upper(on_street_name) like '%WOODHAVEN%' OR upper(on_street_name) like '%CROSS BAY%')))&$limit=5000
```

**Rule.** The NYPD records the intersection as an on/cross street pair, and the dataset geocodes every pair to one node coordinate. An injury crash has `number_of_persons_injured` + `number_of_persons_killed` > 0.

- **Glenwood & Ralph.** I counted records whose street pair is Glenwood/Ralph in either order and either spelling (31). I added 1 record that names Glenwood Rd with a blank cross street and sits at the exact node coordinate (40.634483, -73.91886). Records located only by a house address in `off_street_name` (for example "1704 RALPH AVENUE", 6 m away) are excluded, because they are address-located, not intersection-located.
- **Cross Bay & Woodhaven.** The two names belong to one continuous road. Woodhaven Blvd becomes Cross Bay Blvd at the Rockaway Blvd junction, so the two never cross. Only 1 record uses the literal pair WOODHAVEN BLVD / CROSS BAY BLVD, and the dataset places it at 40.6807, -73.84464. That is the same node where it places every Woodhaven × Rockaway Blvd and Cross Bay × Rockaway Blvd record (45 of them), plus 1 Cross Bay record with a blank cross street. I count all 47 records at that node, excluding address-only records.
- **Excluded nearby nodes.** Cross Bay × Liberty Ave (about 45 m south) and Cross Bay × 107th Ave are excluded. So are 4 "Cross Bay × Rockaway Beach Blvd" records, which are in Rockaway Park.

### Chicago: Traffic Crashes - Crashes (85ca-t3if)

```
https://data.cityofchicago.org/resource/85ca-t3if.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, 41.97563, -87.72836, 120)&$limit=50000
https://data.cityofchicago.org/resource/85ca-t3if.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND within_circle(location, 41.90331, -87.66663, 120)&$limit=50000
https://data.cityofchicago.org/resource/85ca-t3if.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND (upper(street_name) like '%FOSTER%' OR upper(street_name) like '%PULASKI%')&$select=street_no,street_direction,street_name,count(*),avg(latitude),avg(longitude)&$group=street_no,street_direction,street_name&$limit=50000
  (same grouped query for MILWAUKEE / DIVISION)
https://data.cityofchicago.org/resource/85ca-t3if.json?$where=crash_date >= '2021-10-31' AND crash_date < '2026-11-01' AND latitude IS NULL AND (...street/number ranges around both corners...)   -> 0 rows
```

**Rule.** Chicago records one street and a house number, with no cross street. Its coordinates are geocoded from that address. A crash counts when `street_name` is one of the two streets and the point is within 30 m of the intersection.

- **Intersection centroids.** I used the dataset's own geocodes of the grid addresses. Foster/Pulaski is 41.97563, -87.72836, from 4000 W Foster and 5200 N Pulaski. Milwaukee/Division is 41.90331, -87.66663, from 1200 N Milwaukee, which Chicago geocodes to the crossing; 1535–1539 W Division lies 7–11 m away.
- **Why 30 m.** Corner addresses on the far side of the street (5199 and 5201 N Pulaski, 3999 and 4001 W Foster) geocode 22–27 m from the centroid. The radius has to reach them to cover all four corners.
- **Injury crash:** `injuries_total` + `injuries_fatal` > 0.
- **Not used:** the `intersection_related_i` flag, because it is mostly null (44 of 107 are 'Y' at Foster/Pulaski).
- **Milwaukee/Division** is part of the six-way Milwaukee/Division/Ashland junction. Records on Ashland Ave, which crosses Division about 60 m west, are excluded.

### Washington DC: Crashes in DC (DC GIS, Public_Safety_WebMercator/MapServer/24)

```
https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/35/query?where=(STREET_1_NAME IN ('STANTON','SHERIDAN') AND STREET_2_NAME IN ('STANTON','SHERIDAN')) OR (STREET_1_NAME LIKE '%ENFANT%' OR STREET_2_NAME LIKE '%ENFANT%')&outFields=NAME,INTERSECTION_TYPE,STATUS,LATITUDE,LONGITUDE,ROUTEID_1,ROUTEID_2,STREET_1_FULL,STREET_2_FULL,INTERSECTIONKEY&f=json
https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24/query?where=FROMDATE >= DATE '2021-10-31' AND FROMDATE < DATE '2026-11-01' AND NEARESTINTKEY='<key>'&outFields=*&returnGeometry=false&f=json
   for key in a5c0bf205c22fb999c8dfa52a3b7ff36 (Stanton/Sheridan south), 7867d8d67c16a50208a9bb8d16e3e67e (Stanton/Sheridan north),
              b251534b7b174c00827f4f5e88524152 (Penn/L'Enfant Sq), 5bf73113ddbd196f37a52c1a9abfe82e (Suitland Pkwy/Stanton, checked and excluded)
https://maps2.dcgis.dc.gov/.../MapServer/24/query?where=FROMDATE >= DATE '2021-10-31' AND FROMDATE < DATE '2026-11-01' AND ((UPPER(ADDRESS) LIKE '%PENNSYLVANIA%' AND (UPPER(ADDRESS) LIKE '%ENFANT%' OR UPPER(ADDRESS) LIKE '%MINNESOTA%')) OR (UPPER(ADDRESS) LIKE '%STANTON%' AND UPPER(ADDRESS) LIKE '%SHERIDAN%'))&outFields=*&f=json
https://maps2.dcgis.dc.gov/.../MapServer/24/query?where=FROMDATE >= DATE '2021-10-31' AND FROMDATE < DATE '2026-11-01' AND ((ROUTEID='13079822' AND LOCATIONERROR LIKE '%13082352%') OR (ROUTEID='13082352' AND LOCATIONERROR LIKE '%13079822%') OR (ROUTEID='13069812' AND LOCATIONERROR LIKE '%13054992%') OR (ROUTEID='13054992' AND LOCATIONERROR LIKE '%13069812%'))&outFields=*&f=json
```

**Rule.** DC locates most crashes at a building address (MAR). The dataset then attaches the nearest intersection (`NEARESTINTKEY`, which matches DC's Intersection Points layer) and the distance to it (`OFFINTERSECTION`, in metres). A crash counts when `NEARESTINTKEY` is the target intersection and `OFFINTERSECTION` ≤ 30 m.

An injury crash has any MAJOR, MINOR or FATAL field (bicyclist, driver, pedestrian, passenger or other) > 0. Counting the "UNKNOWNINJURIES" fields as well does not change any number.

- **Stanton Rd SE & Sheridan Rd SE.** DC's intersection layer has two separate intersections with this exact name, about 1 km apart:
  - The south node, a5c0bf…, is at 38.85349, -76.98341, next to Suitland Pkwy: 36 injury crashes out of 147.
  - The north node, 7867d8…, is at 38.85841, -76.99328: 4 injury crashes out of 11.
  - Neither node has any crash recorded with intersection text; all are address-located.
- **The 82 "2339 Sheridan Rd SE" records.** 82 of the south-node records (18 of them injury crashes) carry `ADDRESS` = "2339 SHERIDAN ROAD SE" and `LOCATIONERROR` = "Intersecting Route ERROR. 13082352*1 Intersecting RouteID Not Found". 13082352 is Stanton Rd SE's route ID, so these were reported as Sheridan Rd at its intersection with Stanton Rd. The intersecting-route lookup failed, and the crash was placed 19 m from the south node. I include them. They are also the reason the south/north split is uncertain (see Doubts).
- **Suitland Pkwy & Stanton Rd.** The nearby "Suitland Pkwy & Stanton Rd" node 5bf731… has 11 injury crashes out of 33 within 30 m. The dataset assigns those to a different intersection, so they are excluded.
- **Pennsylvania Ave SE & L'Enfant Sq SE.** This is node b251534b…, which DC also names Pennsylvania Ave SE & Minnesota Ave SE (west node) and L'Enfant Sq SE & Minnesota Ave SE.
  - Only 7 crashes carry explicit intersection text (offset < 1 m); 3 of them are injury crashes.
  - The rest are address-located at corner buildings: 2341 Penn at 15 m, 2324 Penn at 18 m, 2337 Penn at 29 m.
  - Crashes at the east Penn/Minnesota node (4408d7…, about 78 m away) are excluded.

### Seattle: SDOT Collisions All Years (ArcGIS FeatureServer)

The `SDOT_Collisions_All_Years` service name returns "Invalid URL". The current service is `SDOT_Collisions_All_Years_1`.

```
https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/SDOT_Collisions_All_Years_1/FeatureServer/0/query?where=INCDATE >= DATE '2021-10-31' AND INCDATE < DATE '2026-11-01' AND ((UPPER(LOCATION) LIKE '%ELLIOTT AVE W%' AND UPPER(LOCATION) LIKE '%W HARRISON ST%') OR (UPPER(LOCATION) LIKE '%RAINIER AVE S%' AND UPPER(LOCATION) LIKE '%25TH AVE S%'))&outFields=*&outSR=4326&f=json
https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/SDOT_Collisions_All_Years_1/FeatureServer/0/query?where=INTKEY IN (28648,31466)&outFields=INCKEY,INCDATE,LOCATION,ADDRTYPE,INTKEY,INJURIES,SERIOUSINJURIES,FATALITIES,MAXSEVERITYDESC,JUNCTIONTYPE&f=json
```

**Rule.** SDOT locates each collision either at an intersection (`ADDRTYPE`='Intersection', with an `INTKEY` and `LOCATION` "A AND B") or on a block segment ("A BETWEEN B AND C"). I counted the intersection records with `INTKEY` 28648 (Elliott/Harrison) and 31466 (25th/Rainier), filtered to the window on `INCDATE`. All of them have `JUNCTIONTYPE` "At Intersection (intersection related)". An injury crash has `INJURIES` + `SERIOUSINJURIES` + `FATALITIES` > 0. Block-segment records on the adjacent blocks are excluded; they are shown in the sensitivity table.

## Doubts

1. **DC Stanton & Sheridan is ambiguous by name.** There are two intersections. I report both and use their sum (40 / 158) as the headline. If the tool means one specific corner, compare per node: south node by Suitland Pkwy 36 / 147, north node 4 / 11. In addition, the 82 "2339 Sheridan Rd SE" fallback records come from reports naming Sheridan at Stanton, but the dataset could not resolve which crossing. DC placed them at the south node, and I followed it. Without them, the south node is 18 / 65.
2. **DC and Chicago locate crashes by address, not by intersection.** The 30 m cut-off is my choice, and the counts move with it; see the sensitivity table. DC Penn/L'Enfant is especially sensitive, because 24 crashes sit at 2337 Penn (29.06 m) and 6 at 2320 Penn (30.1–30.5 m).
3. **NYC Cross Bay & Woodhaven** is a name-change point, not a crossing. 26 / 47 counts the whole Rockaway Blvd junction where the dataset puts the one literal Woodhaven × Cross Bay record. The literal reading gives 1 / 1.
4. **SF has no total-crash count**, because the dataset is injury-only. SF data also ends 2026-08-31, so the last two months of the window are missing. Including the "Intersection Rear End <= 150ft" class adds 2 crashes at Mission/14th; the strict ≤ 20 ft count is 14.
5. **Chicago street numbers are the reported address.** A crash in the intersection may be filed under any nearby address. Chicago's `intersection_related_i` flag is too sparse to use.
6. **Seattle Rainier & 25th** has few intersection-coded collisions (4) and many on the adjacent Rainier blocks (22, 7 of them injury crashes). The narrow count follows SDOT's own intersection/block split.
7. **Data revisions.** All APIs are live, and counts can shift slightly as records are added or revised. DC `FROMDATE` is stored in UTC; no record in the counted sets falls on a boundary day.
