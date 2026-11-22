"""
ROOTCODE - shared constants and modelling assumptions.

Every number marked ASSUMPTION is a first estimate for the hackathon.
Replace it with your own measurements when you have them, and say so in the pitch.
"""

# ---------------- Physical constants ----------------
RHO_WATER = 1000.0        # kg/m3
G = 9.81                  # m/s2
MU_WATER = 1.0e-3         # Pa.s at ~20 C
NU_WATER = 1.0e-6         # m2/s kinematic viscosity
LATENT_HEAT = 2.45e6      # J/kg, latent heat of vaporisation at ~20-30 C

# ---------------- Tile geometry (laser-cut acrylic / plywood prototype) ----------------
TILE_W = 0.30             # m
TILE_H = 0.30             # m
LAYER_T = 0.003           # m, thickness of one laser-cut sheet (screen layers)
CHANNEL_DEPTH = 0.0006    # m, channels are laser-ENGRAVED (raster) ~0.6 mm deep -> slow laminar drip
MANIFOLD_Y = 0.035        # m from tile top: where channels leave the top manifold
POCKET_W = 0.060          # m, plant pocket width
POCKET_H = 0.050          # m, plant pocket height
COOL_STRIP_Y = 0.265      # m from top: centre of the evaporative cooling strip
COOL_STRIP_AREA = 0.27 * 0.03   # m2, wetted cellulose / cotton strip area per tile
TANK_AREA_PER_TILE = 0.01       # m2, cross-section of the feeding tank per tile (10x10 cm bottle)
TANK_BASE_HEAD = 0.05           # m, height of tank bottom above the manifold

# ---------------- Decision-variable bounds ----------------
W_MIN_MM, W_MAX_MM = 0.6, 3.0         # engraved channel width
WC_MIN_MM, WC_MAX_MM = 0.0, 3.0       # cooling branch width (< WC_CLOSED_MM = closed)
WC_CLOSED_MM = 0.5
V_MIN_L, V_MAX_L = 0.05, 2.0          # daily water poured per ROOT tile (L/day)
MIN_DRAIN_MIN = 15.0                  # deliver slowly so the substrate can absorb it
MAX_REYNOLDS = 2000.0                 # keep flow laminar so the hydraulic model stays valid
P_MIN, P_MAX = 0.15, 0.70             # aperture porosity of the front screen
A_MIN_MM, A_MAX_MM = 8.0, 30.0        # aperture characteristic size
LAYERS_MIN, LAYERS_MAX = 1, 4         # stacked front layers -> screen depth = n * LAYER_T

# ---------------- Building / comfort ----------------
WINDOW_SHGC = 0.70        # ASSUMPTION: single glazing, common in older Tunisian apartments
SCREEN_ABSORPTANCE = 0.6  # ASSUMPTION: share of light hitting solid screen that is absorbed
SECONDARY_GAIN = 0.10     # ASSUMPTION: share of absorbed heat that reaches the room
MIN_EFFECTIVE_POROSITY = 0.20   # comfort constraint: keep some daylight and view

# ---------------- Evaporative cooling ----------------
EVAP_RATE_REF = 6.0       # ASSUMPTION: L per m2 per day for a wet surface, hot dry day (RH 50%)
COOLING_COUPLING = 0.30   # ASSUMPTION: share of evaporative cooling that reduces window heat gain

# ---------------- Plants ----------------
# ASSUMPTION: summer water need of one small pocket (~1-1.5 L of substrate), in L/day.
# Calibrate by weighing pockets during your test. Scaled by facade sun exposure.
PLANT_DEMAND_L_DAY = {
    "mint": 0.25,
    "basil": 0.20,
    "parsley": 0.18,
    "lettuce": 0.20,
    "strawberry": 0.30,
    "chili": 0.25,
    "cherry_tomato": 0.45,
}
POCKET_CAPACITY_FACTOR = 1.5   # pocket holds up to 1.5x daily demand, the rest drains (waste)
DEFICIT_LIMIT = 0.10           # a design is "plant-safe" if total deficit <= 10%
REF_FACADE_IRRADIATION = 4.0   # kWh/m2/day used to scale plant demand by sun exposure

# Default location: Tunis
DEFAULT_LAT, DEFAULT_LON, DEFAULT_TZ = 36.81, 10.18, "Africa/Tunis"

FACADE_AZIMUTHS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
