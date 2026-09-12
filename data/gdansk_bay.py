"""
Geometria Zatoki Gdanskiej — akwen operacyjny, maski portowe, coastline.
PRD FR-004: pozycje na ladzie wykluczaja maske portowa.
"""
import math

# Bounding box Zatoki Gdanskiej i podejsc (z PRD FR-001)
GDANSK_BAY_BBOX = {
    "south": 54.30,
    "north": 55.00,
    "west": 18.30,
    "east": 19.70,
}

# Centrum mapy
MAP_CENTER = (54.55, 18.90)
MAP_ZOOM = 10

# Maski portowe — wielokaty gdzie pozycje "na ladzie" sa normalne
# (doki, nabrzeza, kanaly portowe)
# Przyblizone, do doprecyzowania z EMODnet/UM Gdynia
PORT_MASKS = [
    {
        "name": "Port Gdańsk (Nowy Port + DCT)",
        "polygon": [
            (54.385, 18.630), (54.410, 18.630),
            (54.410, 18.710), (54.385, 18.710),
        ],
    },
    {
        "name": "Port Gdańsk (Westerplatte / Wisłoujście)",
        "polygon": [
            (54.395, 18.660), (54.410, 18.660),
            (54.410, 18.695), (54.395, 18.695),
        ],
    },
    {
        "name": "Port Gdynia",
        "polygon": [
            (54.520, 18.530), (54.555, 18.530),
            (54.555, 18.570), (54.520, 18.570),
        ],
    },
    {
        "name": "Port Gdynia — basen wewnetrzny",
        "polygon": [
            (54.530, 18.540), (54.545, 18.540),
            (54.545, 18.560), (54.530, 18.560),
        ],
    },
    {
        "name": "Kotwicowisko Gdynia",
        "polygon": [
            (54.545, 18.490), (54.570, 18.490),
            (54.570, 18.540), (54.545, 18.540),
        ],
    },
    {
        "name": "Kotwicowisko Gdansk",
        "polygon": [
            (54.410, 18.720), (54.430, 18.720),
            (54.430, 18.780), (54.410, 18.780),
        ],
    },
]


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray casting — czy punkt jest wewnatrz wielokata."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def is_in_port_mask(lat: float, lon: float) -> bool:
    """Sprawdz czy pozycja jest w masce portowej (FR-004)."""
    for port in PORT_MASKS:
        if point_in_polygon(lat, lon, port["polygon"]):
            return True
    return False


def is_in_operational_area(lat: float, lon: float) -> bool:
    """Czy pozycja jest w akwenie operacyjnym (Zatoka Gdanska)."""
    bb = GDANSK_BAY_BBOX
    return bb["south"] <= lat <= bb["north"] and bb["west"] <= lon <= bb["east"]


# Prosta aproksymacja "na ladzie" — punkty powyzej 54.38N i west od 18.63E
# to polwysep helski i brzeg. Docelowo zastapic Natural Earth 10m coastline.
# Na hackathon: uproszczona linia brzegowa Zatoki Gdanskiej
COASTLINE_SEGMENTS = [
    # Polwysep Helski (przyblizona linia poludniowa)
    [(54.595, 18.800), (54.610, 18.760), (54.630, 18.710),
     (54.660, 18.650), (54.700, 18.570), (54.730, 18.530),
     (54.760, 18.480), (54.790, 18.410)],
    # Brzeg od Gdyni do Gdanska
    [(54.560, 18.530), (54.530, 18.540), (54.510, 18.550),
     (54.490, 18.560), (54.460, 18.580), (54.430, 18.610),
     (54.405, 18.640), (54.390, 18.660)],
    # Mierzeja Wislana
    [(54.370, 18.930), (54.365, 19.000), (54.360, 19.100),
     (54.355, 19.200), (54.350, 19.300), (54.345, 19.400),
     (54.340, 19.500), (54.335, 19.600)],
]


def is_likely_on_land(lat: float, lon: float) -> bool:
    """
    Prosta heurystyka 'na ladzie' dla Zatoki Gdanskiej.
    Nie zastepuje pelnego coastline check, ale pokrywa glowne przypadki.
    WYKLUCZA maski portowe.
    """
    if is_in_port_mask(lat, lon):
        return False

    # Gdynia/Gdansk brzeg — pozycje za daleko na zachod
    if 54.38 <= lat <= 54.56 and lon < 18.52:
        return True

    # Polwysep Helski — waski pas ladu
    if 54.60 <= lat <= 54.80 and 18.35 <= lon <= 18.55:
        if lon <= 18.42:  # zdecydowanie na ladzie
            return True

    # Mierzeja Wislana
    if 54.33 <= lat <= 54.37 and lon > 19.00:
        return True

    return False


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Odleglosc miedzy dwoma punktami w km."""
    R = 6371.0
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat/2)**2 + math.cos(rlat1)*math.cos(rlat2)*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def point_to_segment_km(
    lat: float, lon: float,
    seg_a: tuple[float, float], seg_b: tuple[float, float],
) -> float:
    """Minimalna odleglosc od punktu do odcinka (przyblizenie plaskie, ok dla Baltyku)."""
    ax, ay = seg_a[1], seg_a[0]
    bx, by = seg_b[1], seg_b[0]
    px, py = lon, lat

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return haversine_km(lat, lon, seg_a[0], seg_a[1])

    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    proj_lon = ax + t * dx
    proj_lat = ay + t * dy
    return haversine_km(lat, lon, proj_lat, proj_lon)


def min_distance_to_route_km(
    lat: float, lon: float,
    route: list[tuple[float, float]],
) -> float:
    """Minimalna odleglosc od punktu do calej trasy (lista waypointow)."""
    if len(route) < 2:
        if route:
            return haversine_km(lat, lon, route[0][0], route[0][1])
        return float("inf")
    best = float("inf")
    for i in range(len(route) - 1):
        d = point_to_segment_km(lat, lon, route[i], route[i + 1])
        if d < best:
            best = d
    return best
