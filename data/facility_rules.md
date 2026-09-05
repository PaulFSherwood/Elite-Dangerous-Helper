# Elite Dangerous Colonisation Facility Rules

Human-readable companion to `colonisation_facilities.json`. Edit/read this in `nvim`, MarkText, or any Markdown editor.

## Provenance

- Facility stats, construction-point rules, layout variants, and prerequisite chains: DaftMav **Colonization Construction v3.4.1**, cross-checked through the current EDCPS `buildings.ts` refresh (2026-07-23).
- Direct player screenshots/notes from 2026-08-29/30 additionally confirm Hestia, Hephaestus, Necessitas, Ourea, Aerecura, Tartarus, and the four planetary-port layouts.
- Market-link *targets* such as `Tubal-Cain` are system/body dependent and are therefore **not** hard-coded as facility rules. `market_economy` records the facility economy only when known/usable.
- Community sources explicitly mark some facility→economy mappings as inferred/best-effort. Prerequisite and construction-point fields are kept separate from market-economy data.

## Construction-point rules

- Tier-1 facilities: no construction-point cost; normally award **+1 T2** on completion.
- Tier-2 facilities: normally cost **1 T2** and award **+1 T3**; large settlements award **+2 T3**.
- Tier-2 non-primary ports (Coriolis / Asteroid Base): escalating **3, 5, 7, 9, … T2**, and award **+1 T3**.
- Tier-3 non-primary ports (Orbis / Ocellus / Dodecahedron / Planetary Port): escalating **6, 12, 18, 24, … T3**.
- The claim/primary station is exempt from the non-primary escalating port cost curves.

## Confirmed prerequisite chains

| Facility to build | Requirement (any matching completed facility) |
|---|---|
| Extraction Hub | Settlement — Extraction |
| Civilian Hub | Settlement — Agriculture |
| Exploration Hub | Installation — Communication Station |
| Outpost Hub | Installation — Space Farm |
| Military Hub | Installation — Military |
| Industrial Hub | Installation — Mining Outpost |
| Military Installation | Settlement — Military |
| Security Station | Installation — Relay Station |
| Research Station | Settlement — Research Bio |
| Tourist Installation | Settlement — Tourism |
| Tourism Settlement (all sizes) | Installation — Satellite |

No additional prerequisite is recorded in the current v3.4.1 dependency table for Scientific Hub, Refinery Hub, High Tech Hub, Government, Medical, or Space Bar.

## Planet-side facilities

### Planetary Port

#### Tier 1 — Civilian Planetary Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Hestia
  - Decima
  - Atropos
  - Nona
  - Lachesis
  - Clotho

#### Tier 1 — Industrial Planetary Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Industrial`
- Layouts:
  - Hephaestus
  - Opis
  - Ponos
  - Tethys
  - Bia
  - Mefitis

#### Tier 1 — Scientific Planetary Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `High Tech`
- Layouts:
  - Necessitas
  - Ananke
  - Fauna
  - Providentia
  - Antevorta
  - Porrima

#### Tier 3 — Planetary Port

- Cost: **T3 port curve: 6, 12, 18, 24, … T3**
- Reward on completion: **none**
- Layouts:
  - Zeus
  - Hera
  - Poseidon
  - Aphrodite

### Settlement

#### Tier 1 — Small Agricultural Settlement — Agriculture

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Agriculture`
- Layouts:
  - Picumnus
  - Annona

#### Tier 1 — Small Industrial Settlement

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Industrial`
- Layouts:
  - Metope
  - Palici
  - Minthe

#### Tier 1 — Small Military Settlement

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Military`
- Layouts:
  - Bellona
  - Enyo
  - Polemos

#### Tier 1 — Small Mining Settlement — Extraction

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Extraction`
- Layouts:
  - Mantus
  - Orcus

#### Tier 1 — Small Agricultural Settlement — Agriculture

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Agriculture`
- Layouts:
  - Consus

#### Tier 1 — Small Industrial Settlement

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Industrial`
- Layouts:
  - Fontus

#### Tier 1 — Small Military Settlement

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Military`
- Layouts:
  - Ioke

#### Tier 1 — Small Mining Settlement — Extraction

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Extraction`
- Layouts:
  - Ourea

#### Tier 2 — Large Agricultural Settlement — Agriculture

- Cost: **1 T2**
- Reward on completion: **+2 T3**
- Market economy/link type: `Agriculture`
- Layouts:
  - Ceres
  - Fornax

#### Tier 2 — Large Industrial Settlement

- Cost: **1 T2**
- Reward on completion: **+2 T3**
- Market economy/link type: `Industrial`
- Layouts:
  - Gaea

#### Tier 2 — Large Military Settlement

- Cost: **1 T2**
- Reward on completion: **+2 T3**
- Market economy/link type: `Military`
- Layouts:
  - Minerva

#### Tier 2 — Large Mining Settlement — Extraction

- Cost: **1 T2**
- Reward on completion: **+2 T3**
- Market economy/link type: `Extraction`
- Layouts:
  - Erebus
  - Aerecura

#### Tier 2 — Large Scientific Settlement — Research Bio

- Cost: **1 T2**
- Reward on completion: **+2 T3**
- Market economy/link type: `High Tech`
- Layouts:
  - Chronos

#### Tier 2 — Large Tourism Settlement

- Cost: **1 T2**
- Reward on completion: **+2 T3**
- Market economy/link type: `Tourism`
- Requires: **Installation — Satellite**
- Layouts:
  - Fufluns

#### Tier 2 — Medium Scientific Settlement — Research Bio

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `High Tech`
- Layouts:
  - Asteria
  - Caerus

#### Tier 2 — Medium Tourism Settlement

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Tourism`
- Requires: **Installation — Satellite**
- Layouts:
  - Comus
  - Gelos

#### Tier 2 — Small Scientific Settlement — Research Bio

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `High Tech`
- Layouts:
  - Pheobe

#### Tier 2 — Small Tourism Settlement

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Tourism`
- Requires: **Installation — Satellite**
- Layouts:
  - Aergia

### Hub

#### Tier 2 — Civilian

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Agriculture`
- Requires: **Settlement — Agriculture**
- Layouts:
  - Aegle

#### Tier 2 — Exploration

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Tourism`
- Requires: **Installation — Communication Station**
- Layouts:
  - Tellus

#### Tier 2 — Extraction

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Extraction`
- Requires: **Settlement — Extraction**
- Layouts:
  - Tartarus

#### Tier 2 — High Tech

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `High Tech`
- Layouts:
  - Janus

#### Tier 2 — Industrial

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Industrial`
- Requires: **Installation — Mining Outpost**
- Layouts:
  - Molae
  - Tellus
  - Eunostus

#### Tier 2 — Military

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Military`
- Requires: **Installation — Military**
- Layouts:
  - Alala
  - Ares

#### Tier 2 — Outpost

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Requires: **Installation — Space Farm**
- Layouts:
  - Io

#### Tier 2 — Refinery

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Refinery`
- Layouts:
  - Silenus

#### Tier 2 — Scientific

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `High Tech`
- Layouts:
  - Athena
  - Caelus

## Orbital facilities

### Starport

#### Tier 2 — Asteroid Base

- Cost: **T2 port curve: 3, 5, 7, 9, … T2**
- Reward on completion: **+1 T3**
- Layouts:
  - Ice
  - Metal
  - Rock

#### Tier 2 — Coriolis

- Cost: **T2 port curve: 3, 5, 7, 9, … T2**
- Reward on completion: **+1 T3**
- Layouts:
  - No Truss
  - Dual Truss
  - Quad Truss

#### Tier 3 — Dodecahedron

- Cost: **T3 port curve: 6, 12, 18, 24, … T3**
- Reward on completion: **none**
- Layouts:
  - No Truss
  - Quint Truss
  - Dec Truss

#### Tier 3 — Ocellus

- Cost: **T3 port curve: 6, 12, 18, 24, … T3**
- Reward on completion: **none**
- Layouts:
  - Ocellus

#### Tier 3 — Orbis

- Cost: **T3 port curve: 6, 12, 18, 24, … T3**
- Reward on completion: **none**
- Layouts:
  - Apollo
  - Artemis

### Outpost

#### Tier 1 — Civilian Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Vesta

#### Tier 1 — Commercial Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Plutus

#### Tier 1 — Criminal Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Dysnomia

#### Tier 1 — Industrial Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Vulcan

#### Tier 1 — Military Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Nemesis

#### Tier 1 — Scientific Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Prometheus

### Installation

#### Tier 1 — Communication Station

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Pistis
  - Soter
  - Aletheia

#### Tier 1 — Mining Outpost

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Extraction`
- Layouts:
  - Euthenia
  - Phorcys

#### Tier 1 — Pirate Base

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Apate
  - Laverna

#### Tier 1 — Relay Station

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Enodia
  - Ichnaea

#### Tier 1 — Satellite

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Layouts:
  - Hermes
  - Angelia
  - Eirene

#### Tier 1 — Space Farm

- Cost: **0 construction points**
- Reward on completion: **+1 T2**
- Market economy/link type: `Agriculture`
- Layouts:
  - Demeter

#### Tier 2 — Government

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Layouts:
  - Harmonia

#### Tier 2 — Medical

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Layouts:
  - Asclepius
  - Eupraxia

#### Tier 2 — Military

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Military`
- Requires: **Settlement — Military**
- Layouts:
  - Vacuna
  - Alastor

#### Tier 2 — Research Station

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `High Tech`
- Requires: **Settlement — Research Bio**
- Layouts:
  - Astraeus
  - Coeus
  - Dodona
  - Dione

#### Tier 2 — Security Station

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Requires: **Installation — Relay Station**
- Layouts:
  - Dicaeosyne
  - Poena
  - Eunomia
  - Nomos

#### Tier 2 — Space Bar

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Layouts:
  - Dionysus
  - Bacchus

#### Tier 2 — Tourist

- Cost: **1 T2**
- Reward on completion: **+1 T3**
- Market economy/link type: `Tourism`
- Requires: **Settlement — Tourism**
- Layouts:
  - Hedone
  - Opora
  - Pasithea
