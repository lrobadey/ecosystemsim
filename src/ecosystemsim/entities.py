"""Static entity component stores for trees, cavities, and habitat modifiers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TreeEntity:
    entity_id: int
    anchor_x: int
    anchor_y: int
    species: str
    state: str
    crown_tiles: list[tuple[int, int]]
    bark_quality: float
    has_cavity: bool


@dataclass
class CavityEntity:
    entity_id: int
    tree_id: int
    entrance_x: int
    entrance_y: int
    insulation_score: float
    capacity: int
    occupied_by: int | None


@dataclass
class HabitatModifier:
    entity_id: int
    kind: str
    x: int
    y: int
    radius: int
    moisture_bonus: float
    insect_bonus: float
    cover_bonus: float


@dataclass
class StaticEntityStore:
    trees: list[TreeEntity] = field(default_factory=list)
    cavities: list[CavityEntity] = field(default_factory=list)
    habitat_modifiers: list[HabitatModifier] = field(default_factory=list)
    _tree_by_id: dict[int, TreeEntity] = field(default_factory=dict, repr=False)
    _cavity_by_xy: dict[tuple[int, int], CavityEntity] = field(default_factory=dict, repr=False)
    black_spruce_tiles: frozenset[tuple[int, int]] = field(default_factory=frozenset, repr=False)

    def build_indices(self) -> None:
        """Build O(1) lookup indices from the current trees and cavities lists."""
        self._tree_by_id = {t.entity_id: t for t in self.trees}
        self._cavity_by_xy = {(c.entrance_x, c.entrance_y): c for c in self.cavities}
        self.black_spruce_tiles = frozenset(
            xy
            for t in self.trees
            if t.species == "black_spruce" and t.state == "live"
            for xy in [(t.anchor_x, t.anchor_y), *t.crown_tiles]
        )

    def get_tree(self, entity_id: int) -> TreeEntity | None:
        return self._tree_by_id.get(entity_id)

    def cavity_at(self, x: int, y: int) -> CavityEntity | None:
        return self._cavity_by_xy.get((x, y))
