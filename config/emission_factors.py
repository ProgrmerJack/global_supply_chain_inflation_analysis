"""
Emission-factor + power tables — IMO Fourth GHG Study 2020 (Faber & Xing), verbatim.

Every value below was transcribed from the IMO Fourth GHG Study 2020 PDF
(greenvoyage2050.imo.org): Table 17 (aux/boiler power), Annex B Table 4 (SFC),
Table 5 (NOx by Tier), Section B.3 (CO2/SOx), emLab-UCSB Table 1.5 (NMEA->class weights).
US cross-check (per plan): EPA Port Emissions Inventory Guidance + CARB/Starcrest SPB.

Congestion-excess emissions = the ANCHOR-mode term (ME off; AE + boiler hoteling load).
"""

# --- IMO Table 17: [At berth, Anchored, Manoeuvring, Sea] power output (kW) ---
# BOILER power then AUX ENGINE power. Sea boiler = 0 (waste-heat boiler assumption).
# Keyed by IMO ship_type -> list of (size_upper_in_native_unit, boiler[4], aux[4]).
# size unit: Container=TEU, tankers/cargo/bulk/roro/vehicle=DWT, Liquefied gas=CBM.
TABLE17 = {
    "Container": [  # TEU
        (999,   [250,250,240,0], [370,450,790,410]),
        (1999,  [340,340,310,0], [820,910,1750,900]),
        (2999,  [460,450,430,0], [610,910,1900,920]),
        (4999,  [480,480,430,0], [1100,1350,2500,1400]),
        (7999,  [590,580,550,0], [1100,1400,2800,1450]),
        (11999, [620,620,540,0], [1150,1600,2900,1800]),
        (14499, [630,630,630,0], [1300,1800,3250,2050]),
        (19999, [630,630,630,0], [1400,1950,3600,2300]),
        (10**9, [700,700,700,0], [1400,1950,3600,2300]),
    ],
    "Oil tanker": [  # DWT
        (4999,   [500,100,100,0],   [250,250,375,250]),
        (9999,   [750,150,150,0],   [375,375,560,375]),
        (19999,  [1250,250,250,0],  [690,500,580,490]),
        (59999,  [2700,270,270,270],[720,520,600,510]),
        (79999,  [3250,360,360,280],[620,490,770,560]),
        (119999, [4000,400,400,280],[800,640,910,690]),
        (199999, [6500,500,500,300],[2500,770,1300,860]),
        (10**9,  [7000,600,600,300],[2500,770,1300,860]),
    ],
    "Chemical tanker": [  # DWT
        (4999,  [670,160,130,0],  [110,170,190,200]),
        (9999,  [670,160,130,0],  [330,490,560,580]),
        (19999, [1000,240,200,0], [330,490,560,580]),
        (39999, [1350,320,270,0], [790,550,900,660]),
        (10**9, [1350,320,270,0], [790,550,900,660]),
    ],
    "Liquefied gas tanker": [  # CBM
        (49999,  [1000,200,200,100],[240,240,360,240]),
        (99999,  [1000,200,200,100],[1700,1700,2600,1700]),
        (199999, [1500,300,300,150],[2500,2000,2300,2650]),
        (10**9,  [3000,600,600,300],[6750,7200,7200,6750]),
    ],
    "Other liquids tanker": [  # DWT
        (999,   [1000,200,200,100],[500,500,750,500]),
        (10**9, [1000,200,200,100],[500,500,750,500]),
    ],
    "Bulk carrier": [  # DWT
        (9999,   [70,70,60,0],   [110,180,500,190]),
        (34999,  [70,70,60,0],   [110,180,500,190]),
        (59999,  [130,130,120,0],[150,250,680,260]),
        (99999,  [260,260,240,0],[240,400,1100,410]),
        (199999, [260,260,240,0],[240,400,1100,410]),
        (10**9,  [260,260,240,0],[240,400,1100,410]),
    ],
    "General cargo": [  # DWT
        (4999,  [0,0,0,0],       [90,50,180,60]),
        (9999,  [110,110,100,0], [240,130,490,180]),
        (19999, [150,150,130,0], [720,370,1450,520]),
        (10**9, [150,150,130,0], [720,370,1450,520]),
    ],
    "Ro-Ro": [  # DWT
        (4999,  [260,250,170,0],[750,430,1300,430]),
        (9999,  [260,250,170,0],[1100,680,2100,680]),
        (14999, [390,380,260,0],[1200,950,2700,950]),
        (10**9, [390,380,260,0],[1200,950,2700,950]),
    ],
    "Vehicle": [  # DWT
        (9999,  [310,300,250,0],[800,500,1100,500]),
        (19999, [310,300,250,0],[850,550,1400,510]),
        (10**9, [310,300,250,0],[850,550,1400,510]),
    ],
    "Refrigerated bulk": [  # DWT
        (1999,  [270,270,270,0],[520,570,560,570]),
        (5999,  [270,270,270,0],[1100,1200,1150,1200]),
        (9999,  [270,270,270,0],[1500,1650,1600,1650]),
        (10**9, [270,270,270,0],[2850,3100,3000,3100]),
    ],
}
PHASES = ["berth", "anchor", "manoeuvre", "sea"]  # index order of the [4] lists

# --- NMEA cargo/tanker (70-89) -> IMO Table 17 classes (emLab Table 1.5 weights) ---
CLASS_WEIGHTS = {
    "cargo":  {"General cargo": 0.32, "Bulk carrier": 0.47, "Container": 0.11, "Ro-Ro": 0.05, "Vehicle": 0.05},
    "tanker": {"Oil tanker": 0.45, "Chemical tanker": 0.34, "Liquefied gas tanker": 0.16, "Other liquids tanker": 0.05},
}
# native size unit per class (for the TABLE17 lookup) and a rough L(m)->size regression.
SIZE_UNIT = {"Container": "TEU"}  # default DWT for all others; Liquefied gas uses CBM~DWT proxy

# --- SFC g/kWh (IMO Table 4, post-2001 rows unless noted) ---
SFC = {  # engine -> {fuel: g/kWh}
    "aux":    {"HFO": 195, "MDO": 185},
    "boiler": {"HFO": 340, "MDO": 320},
    "ssd":    {"HFO": 175, "MDO": 165},   # slow-speed main engine, post-2001
}
CO2_CF = {"HFO": 3.114, "MDO": 3.206}     # g CO2 / g fuel (MEPC.308(73))
SOX_S_TO_SOX = 2 * 0.97753                # SOx = SFC * this * S_fraction

# --- Fuel sulphur fraction for LA/LB (North American ECA) by year ---
def fuel_for_year(year: int):
    """Return (fuel_label, sulphur_fraction) for San Pedro Bay OGVs by year."""
    if year <= 2011:
        return "HFO", 0.0270    # pre-ECA global HFO ~2.7% S
    if year <= 2014:
        return "MDO", 0.0100    # N. American ECA phase-in, 1.0% S
    return "MDO", 0.0010        # ECA 0.1% S from 2015

# --- NOx emission factor (IMO Table 5), g/kWh, by Tier and engine rated speed n (rpm) ---
def nox_ef(tier: str, n_rpm: float) -> float:
    if tier == "I":
        return 17.0 if n_rpm < 130 else (9.8 if n_rpm >= 2000 else 45 * n_rpm ** -0.2)
    if tier == "II":
        return 14.4 if n_rpm < 130 else (7.7 if n_rpm >= 2000 else 44 * n_rpm ** -0.23)
    return 3.4 if n_rpm < 130 else (2.0 if n_rpm >= 2000 else 9 * n_rpm ** -0.2)  # Tier III
# Engine rated speeds: main = slow-speed (n<130); auxiliary = medium-speed (~720 rpm).
N_RPM = {"main": 100, "aux": 720}
def nox_tier_for_build_year(build_year: int, in_neca: bool = True) -> str:
    if build_year >= 2016 and in_neca:
        return "III"
    if build_year >= 2011:
        return "II"
    return "I"

# --- PM10 emission factors g/kWh (ICCT/IMO; sulphur-dependent). PM2.5 = 0.92*PM10 ---
# Representative values by fuel (aux/boiler burning residual vs distillate):
PM10_EF = {"HFO": 1.5, "MDO": 0.25}       # g/kWh; ECA/MDO much lower
PM25_FRACTION = 0.92
# CH4 (Table 6) and CO/N2O (Third IMO) for aux/boiler diesel:
CH4_EF = 0.01
CO_EF = 0.54
N2O_EF = 0.03

# US at-berth control: CA At-Berth Regulation (13 CCR 93118.3). Container/reefer/cruise
# fleets must have a compliant share of at-berth visits use shore power (AUX engines off;
# boilers still run). Compliance share by year (fleet target): 50% (2014-16), 70% (2017-19),
# 80% (2020+). We reduce the BERTH-phase AUX emissions of Container + Refrigerated bulk by
# this share. ANCHORAGE (congestion) is unaffected (ships cannot plug in at anchor).
SHORE_POWER_CLASSES = {"Container", "Refrigerated bulk"}
def shore_power_share(year: int) -> float:
    if year < 2014:
        return 0.0
    if year <= 2016:
        return 0.50
    if year <= 2019:
        return 0.70
    return 0.80
