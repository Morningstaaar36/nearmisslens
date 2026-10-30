# Licences and attribution

| Item | Licence | Use here |
|---|---|---|
| This repository's code | Apache-2.0 (`LICENSE`) | All of it |
| FLUID dataset: video, trajectories, signal logs, base maps (figshare 10.6084/m9.figshare.29974954 v2) | CC BY 4.0 | Validation data. The viewer shows downscaled base maps and derived trajectories, credited on the page |
| FHWA CMF Clearinghouse | US government work | CMF records cited by ID; downloaded by `nml fetch`, not redistributed |
| FHWA Proven Safety Countermeasures | US government work | Countermeasure list in `nearmisslens/data/fhwa_psc.json` |
| SAM 3.1 | SAM License (Meta) | Called through the Meta Model API; weights are never redistributed |
| Muse Spark, Muse Wonder, Muse Image, Muse Voice Transcribe | Meta Model API terms | Called through the API |
| MMS-TTS (`facebook/mms-tts-eng`, `-spa`, `-fra`) | CC BY-NC 4.0 | Generates synthetic test complaints locally. The audio is not published; only transcripts appear |
| Muse Spark Open (`meta-models/muse-spark-open-1026`) | Meta open-weights licence | Served by Baseten (partner inference) for the open-weights agent tier |
| Muse Glimmer 30B GGUF (`meta-models/Muse-Glimmer-30B-GGUF`) | Apache-2.0 | Served on a Modal GPU with llama.cpp (MIT) for the open-weights agent tier; weights are not redistributed |
| Kokoro-82M (`hexgrad/Kokoro-82M`) | Apache-2.0 | Local narration of the demo video |
| NYC, Washington DC, Chicago, Los Angeles and Seattle open data (crashes, Vision Zero / High Injury Network lists, street projects and treatments) | Each portal's open-data terms | Queried live by `nml brief`, `nml citywide` and the data agent; responses cached locally, cited by dataset id in every brief |
| New York State orthoimagery (NYS GIS Program Office), DC orthophoto 2023 (OCTO) | Public open data | City aerial photos in briefs |
| USGS The National Map imagery | US public domain | Aerial photos where no city orthophoto is registered |
| Mapillary street-level images | CC BY-SA 4.0 | Shown in briefs with a link to the image and the licence |
| OpenStreetMap (Overpass, Nominatim) and map tiles | ODbL 1.0 | Street layout in briefs; the web app's base map, credited on the map |
| Leaflet 1.9.4 | BSD-2-Clause | Web app map (CDN) |
| three.js 0.160.0 | MIT | Viewer 3D replay (CDN) |
| marked 12.0.2 | MIT | Viewer memo rendering (CDN) |
| DOMPurify 3.1.6 | Apache-2.0 or MPL-2.0 | Sanitises rendered markdown in the viewer (CDN) |
| Overpass typeface | SIL Open Font License 1.1 | Viewer (Google Fonts) |

Credit line used on screen: "FLUID dataset (Scientific Data, 2026), CC BY 4.0."

Images made with Muse Image are labelled "AI-generated illustration" in the image itself.
