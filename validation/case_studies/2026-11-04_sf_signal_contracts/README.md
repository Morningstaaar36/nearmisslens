# A real case from the web: SFMTA's planned traffic signals, found and reviewed

Run on November 4, 2026 on the local server (the same code as the live site, outside the site's daily budget). A
script opened Chrome full screen and clicked every step itself; nothing was typed but the corner's name. Nobody chose
the projects: Muse Spark found them on the web. Records are as of 4 November 2026.

**The use case.** A transportation committee member in San Francisco wants to know which of the agency's planned
signal projects the crash record supports, without collecting the projects by hand.

## What the site did

| Step | Result | Time | Model cost |
|---|---|---|---|
| Review a list: **Find its planned projects on the web** (San Francisco) | 5 web searches, 5 pages opened, **4 SFMTA project pages kept**, each passage found on its page word for word: Contract 66 New Traffic Signals, Western Addition Traffic Signal Upgrades Phase 1, Contract 36 Traffic Signal Modifications, Tenderloin Traffic Signal Upgrades. **29 planned projects at single intersections** read from 3 of them, each checked against its page; 19 the pages call completed were left out. | 14 s (a cached search) | $0.12 |
| Review the first 4 ticked | **4th St & Mission Rock St**, flashing beacons: build after a site check (the map shows the corner as stop-controlled; beacons are for uncontrolled crossings), 0.09 injury crashes avoided a year. **New signals at 4th Ave & Fulton St, 4th St & Long Bridge St, 10th Ave & Lincoln Way**: not covered by the evidence (a new signal is not a federal Proven Safety Countermeasure). | 8 min | $0.24 |
| Look up the top corner, 4th Ave & Fulton St | **1 injury crash in five years**, about $68,000 a year in harm. The corner already got painted safety zones (2021) and continental crosswalks; the city's own record neither shows these worked nor rules it out. | under 1 s | none |
| Published about this corner (web search) | 3 SFMTA pages kept: the Fulton Street Safety and Transit Project ("New traffic signals are planned on Fulton Street at 4th and 39th avenues"), Contract 66, and the public hearing notice | 56 s | $0.09 |
| Draft the letter | To SFMTA. Every number was checked; it passed on the first round. | 15 s | cents |

Screenshots: [found on the web](1_found_on_the_web.png), [the projects to tick](2_projects_to_tick.png),
[the ranked list](3_ranked_list.png), [the corner](4_corner_glance.png),
[published about the corner](5_published_about_the_corner.png), [the letter](6_letter.png). The text of every
screen is in [`page_text.json`](page_text.json).

## Checked by hand against the city's own data

DataSF's injury crash dataset (`ubvf-ztfx`), queried by street names since 4 November 2021, has **1 injury crash at
Fulton St & 04th Ave** (2025-08-21, complaint of pain), as the tool says.
[`check_crashes_fulton_4th_by_name.json`](check_crashes_fulton_4th_by_name.json) is the query result (it also holds
two crashes at 34th and 44th Ave, which the query's pattern matched and which are not this corner).

**What the record says.** SFMTA plans a signal at a corner with one injury crash in five years. A signal may be right
for reasons the crash record does not hold (transit priority on Fulton Street, which is that project's purpose), but
the crash record does not call for it, and no federal study promises a reduction.

## What this case found wrong, fixed the same evening

1. **The chart's labels carried the agency's quoted sentence**, cut off mid-word. A proposal read off a page now shows
   its name, with the page's sentence beneath it in the table.
2. **The patterns section drew bars from one crash** ("100% here"). Below the 10 crashes the test needs, it now says
   there are too few crashes to compare.
3. **"1 police-reported crashes"** now reads "1 police-reported crash".
