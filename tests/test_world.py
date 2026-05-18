"""Tests for WorldGrid."""

from hypothesis import given, settings
from hypothesis import strategies as st

from ecosystemsim.config import REQUIRED_LAYERS, MapConfig
from ecosystemsim.world import NO_OCCUPANT, NUM_LAYERS, Layer, WorldGrid, make_world


def _make(width: int = 50, height: int = 50) -> WorldGrid:
    cfg = MapConfig(width=width, height=height, layers=REQUIRED_LAYERS)
    return make_world(cfg)


def test_grid_shape() -> None:
    w = _make(50, 50)
    assert w.occupants.shape == (NUM_LAYERS, 50, 50)
    assert w.layer_present.shape == (NUM_LAYERS, 50, 50)
    assert w.resource_biomass.shape == (NUM_LAYERS, 50, 50)
    assert w.scent.shape == (NUM_LAYERS, 50, 50)


def test_occupants_initialize_empty() -> None:
    w = _make()
    assert (w.occupants == NO_OCCUPANT).all()


def test_ground_layer_present_everywhere() -> None:
    w = _make()
    assert w.layer_present[Layer.GROUND].all()


def test_non_ground_layers_absent_by_default() -> None:
    w = _make()
    for layer in (Layer.UNDERSTORY, Layer.TRUNK, Layer.CANOPY, Layer.CAVITY):
        assert not w.layer_present[layer].any()


def test_resource_biomass_non_negative() -> None:
    w = _make()
    assert (w.resource_biomass >= 0).all()


def test_scent_non_negative() -> None:
    w = _make()
    assert (w.scent >= 0).all()


def test_set_and_clear_occupant() -> None:
    w = _make()
    w.set_occupant(Layer.GROUND, 0, 0, 42)
    assert w.get_occupant(Layer.GROUND, 0, 0) == 42
    w.clear_occupant(Layer.GROUND, 0, 0)
    assert w.is_empty(Layer.GROUND, 0, 0)


def test_present_layers_returns_ground() -> None:
    w = _make()
    layers = w.present_layers(0, 0)
    assert "ground" in layers
    assert len(layers) == 1  # only ground present by default


@given(
    width=st.integers(min_value=1, max_value=100),
    height=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_grid_shape_matches_config(width: int, height: int) -> None:
    cfg = MapConfig(width=width, height=height, layers=REQUIRED_LAYERS)
    cfg.__post_init__()
    w = make_world(cfg)
    assert w.occupants.shape == (NUM_LAYERS, height, width)


@given(
    width=st.integers(min_value=1, max_value=100),
    height=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_resource_biomass_never_negative_on_init(width: int, height: int) -> None:
    cfg = MapConfig(width=width, height=height, layers=REQUIRED_LAYERS)
    cfg.__post_init__()
    w = make_world(cfg)
    assert (w.resource_biomass >= 0).all()


@given(
    width=st.integers(min_value=1, max_value=100),
    height=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_scent_never_negative_on_init(width: int, height: int) -> None:
    cfg = MapConfig(width=width, height=height, layers=REQUIRED_LAYERS)
    cfg.__post_init__()
    w = make_world(cfg)
    assert (w.scent >= 0).all()
