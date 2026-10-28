import numpy as np
import pandas as pd

from nearmisslens import risk
from nearmisslens import conflicts as cf
from tests.test_conflicts import track


def test_poisson_ci_known_values():
    lo, hi = risk.poisson_ci(0)
    assert lo == 0 and abs(hi - 3.689) < 1e-3
    lo, hi = risk.poisson_ci(10)
    assert abs(lo - 4.795) < 1e-3 and abs(hi - 18.39) < 1e-2


def test_ttc_probability_bounds():
    st = pd.concat([track(1, 0, 0, 10, 0), track(2, 14, 0, 1, 0)])
    ev = cf.ttc_events(st)
    p0 = risk.ttc_probability(st, ev, 0.0, 0.0, n=20)
    p1 = risk.ttc_probability(st, ev, 3.0, 3.0, n=200)
    assert p0.iloc[0] == 1.0 and 0.0 <= p1.iloc[0] <= 1.0


def test_hotspots_rate():
    st = pd.concat([track(1, 0, 0, 10, 0), track(2, 14, 0, 1, 0)])
    ev = risk.event_locations(cf.ttc_events(st), st)
    h = risk.hotspots(ev, st)
    assert h["events"].sum() == len(ev) and (h["ci_high"] >= h["rate_per_1000"]).all()
