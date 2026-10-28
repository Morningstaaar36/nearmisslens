import pandas as pd
import pytest

from nearmisslens import fluid


def test_class_mapping():
    assert fluid.road_user_class("car") == "vehicle"
    assert fluid.road_user_class("Tricycle") == "vehicle"
    assert fluid.road_user_class("moped") == "two_wheeler"
    assert fluid.road_user_class("pedestrain") == "pedestrian"
    assert fluid.road_user_class("kite") == "other"


def test_signal_state():
    sig = pd.DataFrame({"direction": ["N", "N"], "turn": ["p", "p"], "begin_time": [0, 35],
                        "end_time": [35, 60], "state": ["r", "G"]})
    assert fluid.signal_state(sig, 10)[("N", "p")] == "r"
    assert fluid.signal_state(sig, 40)[("N", "p")] == "G"
    assert not fluid.has_right_turn_control(sig)


@pytest.mark.skipif(not fluid.clip(*fluid.DEV).traj_path.exists(), reason="FLUID data not downloaded")
def test_dev_clip_loads():
    c = fluid.clip(*fluid.DEV)
    df = fluid.load_trajectories(c, real_only=True)
    assert {"vehicle", "two_wheeler", "pedestrian"} <= set(df["cls"])
    assert df["frame"].min() == 1


@pytest.mark.skipif(not fluid.clip(*fluid.DEV).base_map.exists(), reason="FLUID data not downloaded")
def test_geotiff_transform_reads_both_tag_styles():
    from nearmisslens.calibrate import geotiff_transform
    for site in (fluid.DEV, fluid.HELDOUT):
        x0, y0, sx, sy = geotiff_transform(fluid.clip(*site).base_map)
        assert 0.03 < sx < 0.06 and sx == pytest.approx(sy)
