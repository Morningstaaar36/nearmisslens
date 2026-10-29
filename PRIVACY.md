# Privacy

NearMissLens measures how road users move, not who they are.

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
  - for a real recording, only the transcript and the extracted road users, movement and approach are stored;
  - the extraction is instructed to use only what the speaker says.
