"""Per-tile inspection helper combining WorldGrid + StaticEntityStore views."""

from __future__ import annotations

from typing import Any

from ecosystemsim.entities import StaticEntityStore
from ecosystemsim.world import Layer, WorldGrid


def _tree_dict(store: StaticEntityStore, tree_id: int) -> dict[str, Any] | None:
    tree = store.get_tree(tree_id)
    if tree is None:
        return None
    return {
        "entity_id": tree.entity_id,
        "anchor_x": tree.anchor_x,
        "anchor_y": tree.anchor_y,
        "species": tree.species,
        "state": tree.state,
        "crown_tiles": list(tree.crown_tiles),
        "bark_quality": tree.bark_quality,
        "has_cavity": tree.has_cavity,
    }


def inspect_tile(
    world: WorldGrid,
    store: StaticEntityStore,
    x: int,
    y: int,
) -> dict[str, Any]:
    """Return a snapshot of everything visible at tile (x, y)."""
    if not (0 <= x < world.width and 0 <= y < world.height):
        raise IndexError(f"tile ({x},{y}) out of bounds for {world.width}x{world.height}")

    tree_id = int(world.tree_id[y, x])
    tree_info = _tree_dict(store, tree_id) if tree_id >= 0 else None

    cavity = store.cavity_at(x, y)
    cavity_info: dict[str, Any] | None = None
    if cavity is not None:
        cavity_info = {
            "entity_id": cavity.entity_id,
            "tree_id": cavity.tree_id,
            "entrance_x": cavity.entrance_x,
            "entrance_y": cavity.entrance_y,
            "insulation_score": cavity.insulation_score,
            "capacity": cavity.capacity,
            "occupied_by": cavity.occupied_by,
        }

    modifiers: list[dict[str, Any]] = []
    for mod in store.habitat_modifiers:
        if max(abs(mod.x - x), abs(mod.y - y)) <= mod.radius:
            modifiers.append(
                {
                    "entity_id": mod.entity_id,
                    "kind": mod.kind,
                    "x": mod.x,
                    "y": mod.y,
                    "radius": mod.radius,
                    "moisture_bonus": mod.moisture_bonus,
                    "insect_bonus": mod.insect_bonus,
                    "cover_bonus": mod.cover_bonus,
                }
            )

    resource_biomass = {
        "ground": float(world.resource_biomass[Layer.GROUND, y, x]),
        "understory": float(world.resource_biomass[Layer.UNDERSTORY, y, x]),
        "trunk": float(world.resource_biomass[Layer.TRUNK, y, x]),
        "canopy": float(world.resource_biomass[Layer.CANOPY, y, x]),
        "cavity": float(world.resource_biomass[Layer.CAVITY, y, x]),
    }
    occupants = {
        "ground": int(world.occupants[Layer.GROUND, y, x]),
        "understory": int(world.occupants[Layer.UNDERSTORY, y, x]),
        "trunk": int(world.occupants[Layer.TRUNK, y, x]),
        "canopy": int(world.occupants[Layer.CANOPY, y, x]),
        "cavity": int(world.occupants[Layer.CAVITY, y, x]),
    }

    return {
        "xy": [x, y],
        "layers_present": world.present_layers(y, x),
        "tree": tree_info,
        "cavity": cavity_info,
        "habitat_modifiers": modifiers,
        "resource_biomass": resource_biomass,
        "occupants": occupants,
    }
