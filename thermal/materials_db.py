"""
Common building materials database.
λ (thermal conductivity) in W/(m·K), ρ (density) in kg/m³, cp (specific heat) in J/(kg·K).
Values from EN ISO 10456 and EN 1745.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialSpec:
    name: str
    lambda_: float  # W/(m·K)
    rho: float      # kg/m³
    cp: float       # J/(kg·K)

    @property
    def thermal_diffusivity(self) -> float:
        return self.lambda_ / (self.rho * self.cp)

    @property
    def volumetric_heat_capacity(self) -> float:
        return self.rho * self.cp  # J/(m³·K)


MATERIALS: dict[str, MaterialSpec] = {
    # Concrete & masonry
    "concrete_dense":       MaterialSpec("Dense concrete",            2.3,  2400, 1000),
    "concrete_light":       MaterialSpec("Lightweight concrete",      0.6,  1200, 1000),
    "brick_common":         MaterialSpec("Common brick",              0.6,  1800, 1000),
    "brick_hollow":         MaterialSpec("Hollow brick",              0.3,  1000, 1000),
    "stone_limestone":      MaterialSpec("Limestone",                 1.4,  2000, 1000),

    # Insulation
    "mineral_wool":         MaterialSpec("Mineral wool",              0.035,  30,  1030),
    "eps":                  MaterialSpec("EPS (polystyrene foam)",    0.038,  20,  1450),
    "xps":                  MaterialSpec("XPS (extruded polystyrene)",0.034,  35,  1450),
    "polyurethane":         MaterialSpec("Polyurethane foam",         0.025,  30,  1400),
    "wood_fibre":           MaterialSpec("Wood fibre insulation",     0.040, 150,  2100),
    "cellulose":            MaterialSpec("Cellulose insulation",      0.040,  60,  1600),

    # Wood & derived products
    "wood_softwood":        MaterialSpec("Softwood (pine, spruce)",   0.13,  500,  1600),
    "wood_hardwood":        MaterialSpec("Hardwood (oak, beech)",     0.18,  700,  1600),
    "plywood":              MaterialSpec("Plywood",                   0.13,  600,  1600),
    "osb":                  MaterialSpec("OSB board",                 0.13,  650,  1700),
    "particle_board":       MaterialSpec("Particle board",            0.14,  700,  1700),

    # Gypsum & plaster
    "gypsum_board":         MaterialSpec("Gypsum board (plasterboard)",0.21, 900,  1000),
    "gypsum_plaster":       MaterialSpec("Gypsum plaster",            0.40, 1100, 1000),
    "cement_plaster":       MaterialSpec("Cement plaster",            1.00, 1900, 1000),

    # Glazing (effective values for whole window incl. frame, not just glass)
    "glazing_single":       MaterialSpec("Single glazing",            5.8,  2500,  750),
    "glazing_double":       MaterialSpec("Double glazing (air)",      2.8,  2500,  750),
    "glazing_double_low_e": MaterialSpec("Double low-e glazing",      1.4,  2500,  750),
    "glazing_triple":       MaterialSpec("Triple glazing",            0.8,  2500,  750),

    # Floor / soil
    "soil_clay":            MaterialSpec("Clay soil",                 1.5,  1800, 2200),
    "sand_gravel":          MaterialSpec("Sand/gravel",               2.0,  1800,  910),
    "screed":               MaterialSpec("Cement screed",             1.40, 2000, 1000),
    "ceramic_tile":         MaterialSpec("Ceramic tiles",             1.30, 2300,  840),
    "parquet":              MaterialSpec("Parquet/wood floor",        0.18,  700, 1600),

    # Roofing
    "roof_tiles_clay":      MaterialSpec("Clay roof tiles",           1.00, 2000,  800),
    "bitumen_membrane":     MaterialSpec("Bitumen membrane",          0.23, 1100, 1000),
    "metal_sheet":          MaterialSpec("Metal sheet (steel/alu)",   50.0, 7800,  500),
}
