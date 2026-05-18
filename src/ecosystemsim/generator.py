"""Deterministic forest generator for the layered WorldGrid."""

from __future__ import annotations

import numpy as np
from numpy.random import Generator

from ecosystemsim.config import RunConfig
from ecosystemsim.entities import (
    CavityEntity,
    HabitatModifier,
    StaticEntityStore,
    TreeEntity,
)
from ecosystemsim.world import Layer, WorldGrid


def _crown_tiles(anchor_x: int, anchor_y: int, width: int, height: int) -> list[tuple[int, int]]:
    """Return the 3×3 crown footprint clipped to map bounds."""
    tiles: list[tuple[int, int]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            x = anchor_x + dx
            y = anchor_y + dy
            if 0 <= x < width and 0 <= y < height:
                tiles.append((x, y))
    return tiles


def _place_trees(
    rng: Generator,
    density: float,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Rejection-sample non-overlapping tree anchors (Chebyshev distance ≥ 2)."""
    area = width * height
    crown_area = 9
    target = int(round(density * area / crown_area))
    if target <= 0:
        return []

    indices = np.arange(area, dtype=np.int64)
    rng.shuffle(indices)

    placed: list[tuple[int, int]] = []
    for raw in indices.tolist():
        if len(placed) >= target:
            break
        idx = int(raw)
        y = idx // width
        x = idx % width
        ok = True
        for px, py in placed:
            if max(abs(px - x), abs(py - y)) < 2:
                ok = False
                break
        if ok:
            placed.append((x, y))
    return placed


def generate_forest(
    cfg: RunConfig,
    world: WorldGrid,
    rng: Generator,
) -> StaticEntityStore:
    """Populate ``world`` with trees, snags, cavities, and habitat modifiers.

    All randomness flows through the provided ``rng`` so generation is fully
    deterministic for a given seed + config.
    """
    flora = cfg.flora
    width = world.width
    height = world.height
    area = width * height

    store = StaticEntityStore()

    # Reset tree_id (engine may reuse a world instance in tests).
    world.tree_id[:, :] = -1

    # ------------------------------------------------------------------
    # 1) Place tree anchors
    # ------------------------------------------------------------------
    anchors = _place_trees(rng, flora.black_spruce_density, width, height)
    num_trees = len(anchors)

    # ------------------------------------------------------------------
    # 2) Pick snag indices
    # ------------------------------------------------------------------
    num_snags = int(round(flora.snag_fraction * num_trees))
    snag_indices: set[int] = set()
    if num_trees > 0 and num_snags > 0:
        choices = rng.choice(num_trees, size=min(num_snags, num_trees), replace=False)
        snag_indices = {int(v) for v in np.atleast_1d(choices).tolist()}

    # ------------------------------------------------------------------
    # 3) Build TreeEntity rows + activate trunk/canopy/understory layers
    # ------------------------------------------------------------------
    trees: list[TreeEntity] = []
    for i, (ax, ay) in enumerate(anchors):
        is_snag = i in snag_indices
        if is_snag:
            bark_quality = float(rng.uniform(0.3, 0.5))
            state = "dead"
        else:
            bark_quality = float(rng.uniform(0.7, 0.9))
            state = "live"
        crown = _crown_tiles(ax, ay, width, height)
        tree = TreeEntity(
            entity_id=i,
            anchor_x=ax,
            anchor_y=ay,
            species="black_spruce",
            state=state,
            crown_tiles=crown,
            bark_quality=bark_quality,
            has_cavity=False,
        )
        trees.append(tree)
        world.tree_id[ay, ax] = tree.entity_id
        world.layer_present[Layer.TRUNK, ay, ax] = True
        for cx, cy in crown:
            world.layer_present[Layer.CANOPY, cy, cx] = True
            if not is_snag:
                world.layer_present[Layer.UNDERSTORY, cy, cx] = True

    store.trees = trees

    # ------------------------------------------------------------------
    # 4) Install cavities on snags (~50% probability each)
    # ------------------------------------------------------------------
    cavities: list[CavityEntity] = []
    cavity_counter = 0
    for tree in trees:
        if tree.state != "dead":
            continue
        if float(rng.random()) < 0.5:
            insulation = float(rng.uniform(0.6, 0.9))
            cav = CavityEntity(
                entity_id=cavity_counter,
                tree_id=tree.entity_id,
                entrance_x=tree.anchor_x,
                entrance_y=tree.anchor_y,
                insulation_score=insulation,
                capacity=1,
                occupied_by=None,
            )
            cavities.append(cav)
            tree.has_cavity = True
            world.layer_present[Layer.CAVITY, cav.entrance_y, cav.entrance_x] = True
            cavity_counter += 1
    store.cavities = cavities

    # ------------------------------------------------------------------
    # 5) Seed resource biomass
    # ------------------------------------------------------------------
    # Ground: per-tile base draw in [0.1, 0.4].
    ground_base = rng.uniform(0.1, 0.4, size=(height, width)).astype(np.float32)
    world.resource_biomass[Layer.GROUND] = ground_base

    # Per-tree contributions.
    for tree in trees:
        # Trunk biomass scaled by bark_quality.
        trunk_base = float(rng.uniform(0.3, 1.2))
        world.resource_biomass[Layer.TRUNK, tree.anchor_y, tree.anchor_x] = np.float32(
            trunk_base * tree.bark_quality
        )
        if tree.state == "live":
            # Canopy biomass per crown tile.
            for cx, cy in tree.crown_tiles:
                canopy_val = float(rng.uniform(0.5, 2.0))
                world.resource_biomass[Layer.CANOPY, cy, cx] += np.float32(canopy_val)
        else:
            # Snag: bonus ground biomass around the snag (deadwood detritus).
            for cx, cy in tree.crown_tiles:
                bonus = float(rng.uniform(0.05, 0.15))
                world.resource_biomass[Layer.GROUND, cy, cx] += np.float32(bonus)

    # Cavity layer stays at 0.0 (safety value, not food).

    # ------------------------------------------------------------------
    # 6) Moss patches
    # ------------------------------------------------------------------
    modifier_counter = 0
    num_moss = int(round(flora.moss_patch_density * area))
    if num_moss > 0:
        moss_idx = rng.choice(area, size=min(num_moss, area), replace=False)
        for raw in np.atleast_1d(moss_idx).tolist():
            idx = int(raw)
            mx = idx % width
            my = idx // width
            store.habitat_modifiers.append(
                HabitatModifier(
                    entity_id=modifier_counter,
                    kind="moss",
                    x=mx,
                    y=my,
                    radius=1,
                    moisture_bonus=0.3,
                    insect_bonus=0.2,
                    cover_bonus=0.1,
                )
            )
            modifier_counter += 1

    # ------------------------------------------------------------------
    # 7) Fungi (adjacent to snag) / Log (elsewhere) patches
    # ------------------------------------------------------------------
    num_fungi = int(round(flora.fungi_patch_density * area))
    if num_fungi > 0:
        snag_anchors: list[tuple[int, int]] = [
            (t.anchor_x, t.anchor_y) for t in trees if t.state == "dead"
        ]
        adjacent: set[tuple[int, int]] = set()
        for sx, sy in snag_anchors:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = sx + dx
                    ny = sy + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        adjacent.add((nx, ny))
        adjacent_sorted: list[tuple[int, int]] = sorted(adjacent)

        adj_perm = np.arange(len(adjacent_sorted), dtype=np.int64)
        rng.shuffle(adj_perm)
        adj_order: list[tuple[int, int]] = [adjacent_sorted[int(i)] for i in adj_perm.tolist()]

        all_tiles: list[tuple[int, int]] = [
            (x, y) for y in range(height) for x in range(width) if (x, y) not in adjacent
        ]
        rest_perm = np.arange(len(all_tiles), dtype=np.int64)
        rng.shuffle(rest_perm)
        rest_order: list[tuple[int, int]] = [all_tiles[int(i)] for i in rest_perm.tolist()]

        placed_count = 0
        used: set[tuple[int, int]] = set()
        for tile in adj_order:
            if placed_count >= num_fungi:
                break
            if tile in used:
                continue
            store.habitat_modifiers.append(
                HabitatModifier(
                    entity_id=modifier_counter,
                    kind="fungi",
                    x=tile[0],
                    y=tile[1],
                    radius=1,
                    moisture_bonus=0.0,
                    insect_bonus=0.4,
                    cover_bonus=0.2,
                )
            )
            modifier_counter += 1
            used.add(tile)
            placed_count += 1
        for tile in rest_order:
            if placed_count >= num_fungi:
                break
            if tile in used:
                continue
            store.habitat_modifiers.append(
                HabitatModifier(
                    entity_id=modifier_counter,
                    kind="log",
                    x=tile[0],
                    y=tile[1],
                    radius=1,
                    moisture_bonus=0.0,
                    insect_bonus=0.4,
                    cover_bonus=0.2,
                )
            )
            modifier_counter += 1
            used.add(tile)
            placed_count += 1

    # ------------------------------------------------------------------
    # 8) Apply habitat modifier ground biomass bonuses
    # ------------------------------------------------------------------
    for mod in store.habitat_modifiers:
        r = mod.radius
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                tx = mod.x + dx
                ty = mod.y + dy
                if 0 <= tx < width and 0 <= ty < height:
                    world.resource_biomass[Layer.GROUND, ty, tx] += np.float32(mod.insect_bonus)

    return store
