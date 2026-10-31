# Falsification gates: how NearMissLens keeps its agents honest

NearMissLens is a street-safety copilot built from agents on Meta's models. Each agent can propose anything; nothing it proposes reaches a city engineer or a resident until a gate has tried to disprove it with public data. This note describes the gates, the evidence that they work, and where they fall short. Every number here comes from `validation/BENCH.md`, and every test was registered in `validation/BENCH_PREREG.md` before it ran.

## The idea

Meta's verifiable-agent pattern (the Agents 102 workshop, `meta-models/legal-agent-workshop`) puts the checks inside the tools, so an agent cannot finish until its work passes them. Those checks compare an agent's claims with documents it was given. Road safety needs one more kind of check: a claim about the world, such as "a leading pedestrian interval will cut pedestrian crashes here", cannot be verified by reading a document. It can only be tested against what happened when the city did it before.

A falsification gate is a deterministic test, inside the tool an agent uses to finish, that tries to show a claim is wrong. The claim goes through only if the test fails to break it. NearMissLens has four gates:

| Claim | Gate | Where it sits |
|---|---|---|
| A number in a memo, brief or letter | The number must appear in the official record the agent was given | `context.FactCheck`, inside every `finish` tool |
| "This dataset is the city's crash data, and these fields mean injuries" | The adapter must return real records near a point in the city, with dates that parse and are recent, and injury fields that are numeric | `opendata.validate_crash_adapter`, inside the data agent's tool |
| "This fix works in this city" | The city's own past installs must show the effect in a registered before/after design, and a fake install date before the real one must show nothing | `treatments.gate`, inside the analyst's `commit_design` and `finish` tools |
| "The drawing shows the proposed fix" | SAM 3.1 must find more of the fix's concept in the edited photo than in the original, inside the junction, with every real road user unchanged | `brief.illustrate_fix` |

## The causal gate

The causal gate is the new part. Its input is a dated treatment program from the open-data registry (where and when the city installed something) and the city's police-reported crashes.

1. **Design.** For each treated site, crashes within a radius are counted in the window before and the window after the install month (the install month itself is skipped). The expected count after, had nothing been installed, is the count before times the change at comparison sites over the same months (Hauer's comparison-group method). The comparison sites are sites the city treated later (not yet treated), or, when there are too few of them, the rest of the city away from any treatment. The effect is θ = crashes after ÷ crashes expected; below 1 means fewer crashes than expected. A 95% interval comes from resampling treated and comparison sites (2,000 resamples).
2. **Rule.** The program passes only if the interval for θ is entirely below 1.
3. **Placebo.** The same design runs again with a fake install date 19 months before the real one and 18-month windows that both end before the real install. Nothing was installed then, so any "effect" there means the sites were already changing for some other reason (a trend, or the city picking sites after a bad year). The program passes only if every placebo interval includes 1.
4. **Held-out data.** When an AI analyst chooses the design, it explores on a random half of the sites and commits one design. The gate runs that design once on the other half. The analyst cannot try designs until one passes.

Studies are JSON files (`validation/studies/`), so a city, a program, a radius or a window is data, not code. The same engine ran unchanged on New York, Seattle and the other cities listed in `BENCH.md`.

## What the gates found

**New York's leading pedestrian intervals work.** At 1,651 intersections where the city installed an LPI between 2015 and 2021, pedestrian injury crashes fell 17% (θ 0.833, 95% interval 0.781–0.887) compared with intersections that got one later. The placebo on the same sites shows no change (θ 1.02, 0.95–1.10). The national CMF the brief ranks LPIs with (CMF Clearinghouse 9903) is a 19% cut, so the city's own record supports the ranking.

**New York's turn calming fails the gate.** A simple before/after credits it with a 26% cut. The comparison-group estimate is 16%, but the placebo shows a 22% fall in the 18 months before the work started (interval 0.70–0.86), so the decline was already under way. The gate does not credit it.

**The LPI result replicates in Seattle.** The same design, unchanged, on Seattle's 371 usable LPI intersections: pedestrian injury crashes fell 33% (θ 0.675, 0.476–0.875) compared with intersections treated later; both placebos include 1. Seattle's crash records count pedestrians involved rather than pedestrians injured, so the outcome there is injury crashes with a pedestrian involved.

**The gate rarely credits programs that do not exist.** 200 fake programs were built from New York's injury-crash hotspots, each with 300 sites more than 150 m from any recorded treatment and a random install month. Nothing was installed, so every claimed reduction is false:

| Analysis | Fake programs credited with a reduction |
|---|---|
| Naive before/after | 16 of 200 (8.0%, 95% interval 5.0–12.6%) |
| Comparison group without the placebo | 12 of 200 (6.0%, 3.5–10.2%) |
| Full causal gate | 11 of 200 (5.5%, 3.1–9.6%) |

The registered rule (the gate below the naive rate, with an upper bound of at most 10%) was met. The gate's rate is still higher than the 2.5% a one-sided 95% interval promises, so a passed gate is strong evidence, not proof. On random dates, crash trends partly cancel out, which is why the naive rate is not higher; on the real programs above, where sites were chosen by the city, the naive analysis overstated the LPI effect and credited turn calming.

## Limits

- The study is observational. Sites are chosen by the city, so regression to the mean can remain even with the placebo; no Empirical Bayes model is fitted.
- Work recorded outside the open datasets is not seen, and police-reported crashes miss some injuries.
- The gate tests whether a program worked where it was installed. Whether it will work at a new junction is still an engineer's judgement; the brief shows the local result next to the national CMF and does not replace either.
- The gate can be wrong in both directions: about 1 in 20 fake programs passed, and a real effect on few sites can fail for lack of data.
