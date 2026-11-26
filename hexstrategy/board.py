"""Integer coordinates for a pointy-top hex board."""
from collections import defaultdict
from dataclasses import dataclass, field

RESOURCES = ("wood", "brick", "wool", "grain", "ore")
CORNERS = ((0, -2), (1, -1), (1, 1), (0, 2), (-1, 1), (-1, -1))


@dataclass(frozen=True)
class Tile:
    center: tuple[int, int]
    resource: str | None
    number: int


@dataclass(frozen=True)
class Board:
    tiles: tuple[Tile, ...]
    vertices: tuple[tuple[int, int], ...]
    edges: tuple[tuple[int, int], ...]
    corners: tuple[tuple[int, ...], ...]
    neighbors: tuple[tuple[int, ...], ...]
    incident: tuple[tuple[int, ...], ...]
    adjoining: tuple[tuple[int, ...], ...]
    ports: tuple[tuple[int, str | None], ...]
    _hash: int = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        tiles = tuple((tile.center, tile.number, RESOURCES.index(tile.resource) if
                       tile.resource else -1) for tile in self.tiles)
        ports = tuple((edge, RESOURCES.index(resource) if resource else -1)
                      for edge, resource in self.ports)
        object.__setattr__(self, "_hash", hash((tiles, ports)))

    def __hash__(self):
        return self._hash

    @classmethod
    def random(cls, rng):
        centers = [(2*q+r, 3*r) for r in range(-2, 3) for q in range(-2, 3)
                   if abs(q+r) <= 2]
        resources = [resource for resource, count in zip(RESOURCES, (4, 3, 4, 4, 3))
                     for _ in range(count)] + [None]
        rng.shuffle(resources)
        # Walk the outer ring, then the inner ring, assigning the standard pip sequence.
        # Discover each ring geometrically to keep it independent of tile ordering.
        from math import atan2
        rings = []
        for radius in (2, 1):
            ring = [i for i, (x, y) in enumerate(centers)
                    if max(abs(y//3), abs((x-y//3)//2), abs((x+y//3)//2)) == radius]
            rings.append(sorted(ring, key=lambda i: atan2(centers[i][1], centers[i][0])))
        rotation = rng.randrange(6)
        start = 2*rotation + 1
        path = rings[0][start:] + rings[0][:start]
        path += rings[1][rotation:] + rings[1][:rotation]
        path.append(centers.index((0, 0)))
        tokens = iter((5, 2, 6, 3, 8, 10, 9, 12, 11, 4, 8, 10, 9, 4, 5, 6, 3, 11))
        numbers = {i: next(tokens) for i in path if resources[i] is not None}
        tiles = tuple(Tile(center, resources[i], numbers.get(i, 0))
                      for i, center in enumerate(centers))
        points = [tuple((x+dx, y+dy) for dx, dy in CORNERS) for x, y in centers]
        vertices = tuple(sorted({point for tile in points for point in tile}))
        index = {point: i for i, point in enumerate(vertices)}
        corners = tuple(tuple(index[point] for point in tile) for tile in points)
        edge_tiles = defaultdict(list)
        adjoining = [[] for _ in vertices]
        for tile, corners_for_tile in enumerate(corners):
            for a, b in zip(corners_for_tile, corners_for_tile[1:] + corners_for_tile[:1]):
                edge_tiles[tuple(sorted((a, b)))].append(tile)
                adjoining[a].append(tile)
        edges = tuple(sorted(edge_tiles))
        neighbors = [[] for _ in vertices]
        incident = [[] for _ in vertices]
        coast = defaultdict(list)
        for i, (a, b) in enumerate(edges):
            neighbors[a].append(b)
            neighbors[b].append(a)
            incident[a].append(i)
            incident[b].append(i)
            if len(edge_tiles[a, b]) == 1:
                coast[a].append((b, i))
                coast[b].append((a, i))
        cursor = min(coast)
        previous = None
        coastline = []
        for _ in range(len(coast)):
            destination, edge = next((v, e) for v, e in coast[cursor] if v != previous)
            coastline.append(edge)
            previous, cursor = cursor, destination
        # Each shore segment carries its own harbor positions and exchanges.
        frames = [((0, None), (3, "wood")), ((1, None),),
                  ((0, "brick"), (3, "grain")), ((1, None),),
                  ((0, "wool"), (3, None)), ((1, "ore"),)]
        rng.shuffle(frames)
        offset = 5*rng.randrange(6)
        ports = tuple((coastline[(offset + 5*segment + p) % len(coastline)], resource)
                      for segment, frame in enumerate(frames) for p, resource in frame)
        return cls(tiles, vertices, edges, corners, tuple(map(tuple, neighbors)),
                   tuple(map(tuple, incident)), tuple(map(tuple, adjoining)), ports)
