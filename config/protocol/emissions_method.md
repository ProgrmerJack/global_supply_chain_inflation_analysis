# Emissions module — confirmed methodology (IMO 4th GHG 2020, emLab-UCSB scaffold)

Sourced from IMO Fourth GHG Study 2020 (Faber et al. 2020), ICCT 2017 (Olmer et al.),
as implemented by emLab-UCSB `ocean-ghg` (emlab-ucsb.github.io/ocean-ghg/ais_model.html).
This file records what is CONFIRMED; the one pending authoritative input is IMO Table 17
numeric AE/boiler power (see bottom).

## Formula (per vessel, per operational-mode interval)
E_pollutant = Σ over {main engine, auxiliary engine, boiler} of
              hours × load_factor × installed_power_kW × EF_pollutant_g_per_kWh
Congestion-excess emissions = the ANCHOR-mode term (ME off; AE + boiler hoteling load).

## Main-engine emission factors (g/kWh) — CONFIRMED (emLab Table 1.1, from ICCT App. E, SSD/MSD/HSD avg)
CO2 = 629.833 | NOX = 12.960 | SOX = 3.917 | PM = 0.605 | CO = 0.540 | CH4 = 0.010 | N2O = 0.030
- PM2.5/PM10/VOC derived as a factor × CO2.
- Low-load correction (IMO Table 20) applied for ME load < 20% (matters little at hoteling: ME ~off).
- SOX/PM EFs must switch at the 2020 IMO 0.5% sulfur cap (pre-2020 HFO ~2.7% S -> post 0.5%),
  and California at-berth OGV rules (shore power / low-sulfur) across 2009-2025. TO PARAMETERIZE.

## Auxiliary engine + boiler energy (4-phase, larger vessels) — CONFIRMED STRUCTURE
For ME_power_kW <= 150: aux = 0, boiler = 0.
For 150 < ME_power_kW <= 500: aux = 0.05 × ME_power_kW; boiler = boiler_power_kw(class,phase).
Else: aux = aux_engine_power_kw(class, phase); boiler = boiler_power_kw(class, phase).
Phases: at_berth, at_anchor, manoeuvring, at_sea  <-> our modes berth/anchor/manoeuvre/transit.

## Installed ME power imputation — METHOD CONFIRMED (need the regressions)
IMO/ICCT type×size lookup. We have Length/Width/Draft/VesselType (NMEA 70-89), not GT/DWT/kW.
Path: estimate size (GT or DWT) from L×B×draft, then ME power from IMO Table 17 size bins /
ICCT length->power. emLab uses GT; conversions confirmed:
  GT = -1097.4 + 11.049·TEU  (containers; Abramowski et al. 2018)
  GT = f(DWT, ship_type) linear (emLab regression, R²=0.994)

## Vessel-class weights (NMEA cargo/tanker -> IMO Table 17 classes) — CONFIRMED (emLab Table 1.5)
cargo  -> General cargo .32 | Bulk carrier .47 | Container .11 | Ro-Ro .05 | Vehicle .05
tanker -> Oil tanker .45 | Chemical tanker .34 | Liquefied gas .16 | Other liquids .05
(Our NMEA 70-79 = cargo, 80-89 = tanker; apply weighted AE/boiler power across the mapped classes.)

## PENDING — the one authoritative numeric input still to source
IMO 4th GHG Study 2020 **Table 17**: auxiliary-engine power (kW) and boiler power (kW) by
ship_type × size-bin × operational phase (berth/anchor/manoeuvre/sea). This is the linchpin
for hoteling (anchor/berth) emissions. Sources to pull the exact values from:
  - IMO Fourth GHG Study 2020 PDF, Table 17 (authoritative).
  - emLab-UCSB ocean-ghg processed "updated Table 17" data file.
  - EPA Port Emissions Inventory Guidance + CARB SPB inventory (US cross-check, per user: reconcile both).
Once encoded -> build computation -> VALIDATE vs ERL-2024 SPB (Oct-2021 peak ~2001 t CO2/day,
~23 t NOx/day) before the full 2009-2025 run.
