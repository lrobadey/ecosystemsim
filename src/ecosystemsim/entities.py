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

    def get_tree(self, entity_id: int) -> TreeEntity | None:
        for tree in self.trees:
            if tree.entity_id == entity_id:
                return tree
        return None

    def cavity_at(self, x: int, y: int) -> CavityEntity | None:
        for cavity in self.cavities:
            if cavity.entrance_x == x and cavity.entrance_y == y:
                return cavity
        return None
