# rho [kg/m³], lambda [W/(m·K)], cp [J/(kg·K)]
materials_db: dict[str, tuple[float, float, float]] = {
    "concrete": (2300.0, 1.7, 1000.0),
    "brick": (1800.0, 0.6, 840.0),
    "insulation_mineral_wool": (30.0, 0.04, 840.0),
    "insulation_eps": (20.0, 0.04, 1450.0),
    "wood_pine": (500.0, 0.13, 1600.0),
    "plasterboard": (900.0, 0.25, 1000.0),
    "air_gap": (1.2, 0.025, 1005.0),
    "glass": (2500.0, 1.0, 750.0),
}


def is_heavy(rho: float) -> bool:
    return rho > 500.0
