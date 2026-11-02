# Privacy

NearMissLens works from public records and measures how road users move, not who they are. This page lists what it
stores, where, and about whom.

## The engineer and the copilot

- **Addresses you search** are sent to OpenStreetMap's Nominatim to find the corner, unless the corner is already in
  the shipped gazetteer (`nearmisslens/data/geocodes.json`). A new result is added to the local gazetteer; nothing ties
  it to who searched.
- **Crash records** are the cities' published police-report datasets. The engineer reads counts, dates, injury fields,
  vehicle types and recorded factors. It never reads or shows names or plates. It reads each record's dataset row id
  (for example `collision_id`) only to count a crash once and to join a crash to its vehicles and people; the id is
  never shown, and the pages show only totals for a 100 m circle.
- **Road owners and offices** come from published inventories and district maps. No person is named: a letter is
  addressed to an office ("Council Member, District 17"), so nothing goes stale and no individual is singled out.
- **Street photos** come from Mapillary, which blurs faces and plates before publishing. A brief keeps a local copy
  under `runs/briefs/`, and the static site does not publish them; it links to Mapillary instead.
- **The static site** (GitHub Pages) has no server code and stores nothing. The page remembers nothing between visits.
  It loads a font from Google Fonts, the Leaflet map library from unpkg.com and map tiles from OpenStreetMap, so those
  services see the visitor's IP address, as with any page that uses them.
- **The live endpoint** (Modal) is built but not deployed; the site is a static replay. Deployed, it would keep no
  request log and no IP addresses. Its caps are global daily counters (a date,
  a request count and a dollar amount), so there is nothing per visitor to keep. Searched addresses are sent to
  Nominatim and the cities' open-data APIs to answer the request.
- **Letters** are drafted for you to review and send yourself. NearMissLens sends nothing.

## The desk, the 311 inbox and Corner Watch

- **The desk** reads public web pages it finds with Meta's `web_search` and keeps their visible text in the local
  cache, to check that every quote it publishes is on the page. It fetches only public `http(s)` addresses, with its
  own named user agent; a site that refuses automated readers is respected, and its quote is shown as unverified.
- **People named in the news.** A published desk case can repeat what a news report already published, such as the
  name and age of a person killed or injured, because the case quotes the report. The desk adds no name the source does
  not print, and refuses to publish a licence plate.
- **311 reports** come from San Francisco's public Open311 feed, which already publishes each report's text, address,
  time and photo link. The inbox keeps one saved copy per day under `data/inbox/`. A published desk case quotes the
  report and links its record in the city's feed; it adds no names. Photos are read by Muse Spark and not republished.
- **Camera frames** come from Seattle's public traffic-camera snapshots, fetched no faster than the city refreshes
  them. Frames stay on this machine (`data/cameras/`) and are never published: the site shows counts of people and
  vehicles and the model's answers about the corner's layout. Nothing identifies, tracks or recognises a person; a
  count is per frame and no one is followed between frames.

## The drone-video pipeline

- **Anonymous tracks:**
  - road users are track IDs that exist only within one clip;
  - IDs are not linked across clips or sites;
  - nothing in the pipeline identifies, recognises or re-identifies a person or vehicle.
- **No demographic inference:**
  - classes are vehicle, two-wheeler and pedestrian;
  - no age, gender or other personal attributes are estimated.
- **Source footage:**
  - the validation video is the published FLUID dataset, recorded from about 120 m;
  - people appear as blobs of about a metre, and faces and plates cannot be resolved;
  - the sites are referred to only by the dataset's codes, and we do not geolocate them.
- **Model calls:** frames and short clips are sent to the Meta Model API for tracking, review and illustration. API use is subject to Meta's Acceptable Use Policy, which prohibits using the models to collect, process or infer sensitive information about individuals; this project does neither.
- **Illustrations:** Muse Image edits are labelled as AI-generated. Real road users inside the edited area are kept from the original frame and are not regenerated.
- **Complaints:**
  - the test complaints are synthetic;
  - a recorded complaint is transcribed by Muse Voice Transcribe, and the temporary audio files are deleted right after;
  - only the transcript and the extracted road users, movement and approach are kept;
  - the extraction is instructed to use only what the speaker says.
- **Voice-over:** the demo narration is the author's own voice, recorded locally with `nml voice-studio`.
