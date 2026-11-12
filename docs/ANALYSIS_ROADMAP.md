# OpenSees Studio — Nonlinear and Dynamic Analysis Roadmap

**Status:** proposed implementation plan  
**Engine baseline:** OpenSeesPy 3.8.0.0, 3D, 6 DOF per node  
**Current application:** OpenSees Studio 1.0.0  
**Prepared:** 2026-11-12

**Implementation status:** the Results-tab mode selector, node visibility toggle,
ribbon cleanup, hinge definition library grouped by model type, per-element hinge
assignments, tree usage colouring, hysteresis diagram sub-dialog and the Pushover
tab with `beamWithHinges` lumped hinge models (Steel01 / Hysteretic /
Takeda-like / FlagShape) are implemented. The remaining phases below are still
planned.

Command-level smoke checks against the installed build passed for:

- a fiber-section `forceBeamColumn` cantilever under `DisplacementControl`;
- a `UniformExcitation` + `Newmark` linear time-history run;
- `eigen` + `modalProperties` + `responseSpectrumAnalysis`.

These checks confirm the command paths exist in the bundled engine. They do not
replace the benchmark validation plan in Section 9.

---

## 1. Executive summary

OpenSees Studio currently exposes a linear-elastic static solver, an eigenvalue
solver and a small material library. The installed OpenSees engine is far more
capable than the GUI: it already contains fiber sections, nonlinear beam-column
elements, plastic-hinge elements, link elements, rigid constraints, dampers,
seismic-isolation bearings, response-spectrum analysis and transient time-history
analysis.

The largest gap is not the engine. It is the application layer: the current data
model has one material type with a few flat parameters, elastic section
properties only, one beam element type, one load pattern type, no analysis-case
object and one static/modal result container.

The recommended order is:

1. **Build the nonlinear frame foundation** — analysis-case architecture,
   material registry, fiber sections, nonlinear beam-column elements and
   pushover.
2. **Add seismic loading and dynamic analysis** — ground motions, linear time
   history, response spectrum, nonlinear time history, dampers and isolation
   bearings.
3. **Add concentrated plasticity and advanced components** — `beamWithHinges`,
   IMK hinge models, advanced hysteresis, nonlinear walls/shells.
4. **Add research/special features** — exact Takeda/Pivot behaviour, SSI,
   multi-support excitation, staged construction, explicit analysis.

A realistic delivery for one experienced developer is approximately
**6–8 months**, with the first usable nonlinear-static release in about
**10–12 weeks**. The work is dominated by material/section editing, solver
orchestration, result visualisation and validation, not by writing OpenSees
commands.

---

## 2. What the GUI supports today

| Area | Current state | Consequence |
|---|---|---|
| Materials | `Elastic`, `ElasticPP`, `Steel02`, `Concrete02` | Only elastic beam behaviour is actually used |
| Sections | Elastic `A`, `Iy`, `Iz`, `J` from shape dimensions or standard database | No fiber discretisation |
| Frame elements | `elasticBeamColumn` | No distributed or concentrated plasticity |
| Truss / shell | `truss`, `ShellMITC4` with elastic plate material | Linear only |
| Links / constraints | None | No zero-length springs, rigid links or diaphragms |
| Dampers / bearings | None | No energy-dissipation or isolation modelling |
| Static analysis | `LoadControl`, `Linear` algorithm | No displacement control, arc length or convergence controls |
| Modal analysis | `eigen` | No response-spectrum combination |
| Dynamic analysis | None | No time series, ground motion or transient analysis |
| Results | One static or one modal result set | No time histories, envelopes, capacity curves or hinge states |
| Persistence | Project schema v1 | No ground motions, analysis cases or fiber definitions |
| MCP / Tcl | 43 MCP tools, static Tcl export | No parity for new analysis types |

The current material list is misleading: `elasticBeamColumn` does not use a
uniaxial material at all. `Steel02` and `Concrete02` only become meaningful once
fiber sections and nonlinear frame elements are added.

---

## 3. OpenSees 3.8.0 capability audit

The following names were verified against the installed OpenSeesPy 3.8.0
command set. The scope is structural-building analysis; geotechnical and
research classes are noted where relevant but are not first-release targets.

### 3.1 Uniaxial materials

| Family | Native OpenSees materials | GUI priority |
|---|---|---|
| Elastic / multilinear | `Elastic`, `ElasticPP`, `ElasticPPGap`, `ElasticBilin`, `ElasticMultiLinear`, `MultiLinear`, `Hardening` | P0 |
| Steel / reinforcement | `Steel01`, `Steel02`, `Steel02Fatigue`, `Steel03`, `Steel4`, `SteelMPF`, `SteelDRC`, `SteelFracture`, `ReinforcingSteel`, `DoddRestrepo`, `RambergOsgoodSteel` | P0/P2 |
| Concrete | `Concrete01`, `Concrete02`, `Concrete02IS`, `Concrete04`, `Concrete06`, `Concrete07`, `ConcreteCM`, `ConcretewBeta`, `Concrete01WithSITC` | P0/P2 |
| Hysteretic / damage | `Hysteretic`, `HystereticSM`, `HystereticSmooth`, `HystereticAsym`, `HystereticPoly`, `Pinching4`, `IMKBilin`, `IMKPeakOriented`, `IMKPinching`, `BoucWen`, `BoucWenInfill` | P0/P1 |
| Self-centering / flag | `FlagShape`, `SelfCentering` | P1/P2 |
| Dampers / impact | `Viscous`, `ViscousDamper`, `Maxwell`, `BilinearOilDamper`, `CoulombDamper`, `FrictionSpringDamper`, `HertzDamp`, `JankowskiImpact`, `ViscoelasticGap` | P1 |
| Wrappers | `Parallel`, `Series`, `MinMax`, `InitStrain`, `InitStress`, `PathIndependent`, `Damper`, `Penalty`, `Multiplier`, `TensionOnly`, `SimpleFracture`, `Fatigue` | P2 |
| Geotechnical | `PySimple1`, `TzSimple1`, `QzSimple1`, `PyLiq1`, `TzLiq1`, `QzLiq1` | P3 |

Notes:

- `Bilin`, `Bilin02`, `ModIMKPeakOriented`, `ModIMKPinching` and their `02`
  variants exist but are deprecated by the current `IMK*` and `HystereticSM`
  models. The GUI should use the current names only.
- `Steel02` and `Concrete02` already exist in the current model, but they are
  not used by the current beam element. The first implementation step must
  connect them to fiber sections.

### 3.2 Hysteresis models requested by the user

| Requested model | Engine support in 3.8.0 | Recommended GUI implementation | Priority |
|---|---|---|---|
| **Bilinear** | Native: `Steel01`, `Hardening`, `ElasticBilin`, `IMKBilin`, and `Hysteretic` with a 2-point envelope | One material editor group with presets; default to `Steel01` for steel and `IMKBilin` for hinge calibration | P0 |
| **Trilinear** | Native: `Hysteretic` 3-point envelope, `ElasticMultiLinear`, `MultiLinear`, `Pinching4`, `HystereticSM` 3–7 point envelope | Backbone table with 2–7 points and cyclic parameters | P0/P1 |
| **Takeda** | No direct `uniaxialMaterial Takeda`. The engine contains a Takeda/Ductility **unloading-rule primitive** (`unloadingRule Takeda ...`) and Takeda-like degradation can be represented by `Hysteretic`/`HystereticSM` with pinching, damage and `beta` | Expose a clear “Takeda-like RC hinge” preset built on `HystereticSM` (degraded unloading via `beta`, pinching, damage). Do not label it as an exact Takeda material. Exact Takeda only in P3 if a supported material route is confirmed | P1 preset, P3 exact |
| **Pivot** | No native Pivot uniaxial material in 3.8.0 | Approximate with `Pinching4` or `Hysteretic`; exact Pivot requires a custom material plugin, not planned for the first releases | P3 |
| **Flag** | Native: `FlagShape` (E, fy, Eh, beta), `SelfCentering` | Dedicated “Flag / self-centering” material group with a beta slider and cyclic preview | P1 |
| **Bouc-Wen** | Native: `BoucWen` uniaxial material | Include in generic hysteretic group with parameter help | P1 |
| **Pinching4** | Native: `Pinching4` | Include in generic hysteretic group and as a hinge/section material | P1 |
| **IMK (Ibarra–Medina–Krawinkler)** | Native: `IMKBilin`, `IMKPeakOriented`, `IMKPinching` | Expose as “plastic hinge” materials with a moment–rotation backbone editor and deterioration parameters | P2 |
| **HystereticSM** | Native: 2–7 point envelope, pinching, damage, `beta`, envelope degradation | Make this the general-purpose user-defined hysteresis editor; it covers bilinear, trilinear and Takeda-like loops | P1 |
| **HystereticSmooth / HystereticAsym** | Native smooth asymmetric hysteresis | Advanced material page | P2 |

The important distinction is:

- **Bilinear, trilinear, flag and Bouc-Wen are fully native.**
- **Takeda is only a low-level unloading primitive / approximation, not a
  direct standalone material.**
- **Pivot is not native in 3.8.0.**

### 3.3 Sections and fiber modelling

| Section / feature | Native OpenSees support | GUI plan |
|---|---|---|
| Elastic section | `ElasticSection2d/3d`, `ElasticShearSection2d/3d`, `ElasticWarpingShearSection2d`, `ElasticTubeSection3d` | Keep current elastic section editor |
| Fiber section | `section Fiber`, `fiber`, `patch`, `layer`; `FiberSection2d/3d`, `FiberSectionAsym3d` | New fiber section builder with meshing, material assignment and preview |
| Aggregated section | `SectionAggregator`, `ParallelSection` | Add axial/shear/torsion aggregation in P2 |
| Shell / plate section | `LayeredShellFiberSection`, `ElasticMembranePlateSection`, `ElasticPlateSection`, `PlateFiber` | Nonlinear shell section in P2 |
| Standard shapes | Current AISC/CISC database has dimensions for I, box, pipe and custom shapes | Use those dimensions to auto-generate fiber meshes |

### 3.4 Elements and constraints

| Category | Native OpenSees elements | GUI plan |
|---|---|---|
| Elastic frame | `elasticBeamColumn`, `ElasticBeam2d/3d`, `ModElasticBeam2d/3d`, `ElasticTimoshenkoBeam2d/3d` | Keep current, add explicit type selector |
| Nonlinear frame | `forceBeamColumn`, `dispBeamColumn`, `mixedBeamColumn`, `ElasticForceBeamColumn` | P0/P1: fiber force/displacement beam-columns |
| Plastic hinges | `beamWithHinges`; `HingeMidpoint`, `HingeRadau`, `HingeRadauTwo`, `HingeEndpoint`, `Legendre`, `NewtonCotes`, `Radau` | P1: concentrated plasticity and hinge integration |
| Truss | `truss`, `CorotTruss`, `trussSection`, `CorotTrussSection`, `Truss2` | P1: corotational truss for large displacement |
| Shell | `ShellMITC4`, `ShellMITC9`, `ShellDKGQ`, `ShellDKGT`, `ShellNLDKGQ`, `ShellNLDKGT`, `ASDShellQ4/T3` | P2 |
| Link / spring | `ZeroLength`, `ZeroLengthSection`, `ZeroLengthND`, `CoupledZeroLength`, `TwoNodeLink`, `TwoNodeLinkSection` | P0: zero-length and two-node links |
| Rigid connection | `rigidLink` (`-bar` / `-beam`), `rigidDiaphragm`, `equalDOF` | P0: constraint objects, not fake elements |
| Seismic isolation | `ElastomericBearingPlasticity3d`, `ElastomericBearingBoucWen3d`, `ElastomericBearingBoucWenMod3d`, `ElastomericBearingUFRP2d`, `ElastomericX`, `LeadRubberX`, `FlatSliderSimple3d`, `SingleFPSimple3d`, `TripleFrictionPendulum`, `TFP_Bearing`, `RJWatsonEQS3d` | P1: 3D variants only (the app is always 3 ndm / 6 ndf) |
| Walls | `MVLEM`, `SFI_MVLEM`, `E_SFI_MVLEM_3D`, `MVLEM_3D` | P2 |
| Contact / impact | `ZeroLengthContact2D/3D`, `CoupledZeroLength`, `ZeroLengthImpact3D` | P3 |

`rigidLink` is an OpenSees **constraint command**, not an element. It should be
stored in a new `Project.constraints` collection so it can be edited, deleted,
exported and mirrored without polluting the element list.

### 3.5 Analysis types and solver components

| Feature | Engine commands | GUI priority |
|---|---|---|
| Linear / nonlinear static | `integrator LoadControl`, `analysis Static` | P0 |
| Pushover | `integrator DisplacementControl` (plus `ArcLength` later), `analysis Static` | P0 |
| Modal | `eigen`, `modalProperties` | P0 (already partly present) |
| Response spectrum | `responseSpectrumAnalysis`, `modalProperties`, SRSS/CQC post-processing | P1 |
| Linear elastic time history | `timeSeries Path`, `pattern UniformExcitation`, `integrator Newmark`, `analysis Transient` | P1 |
| Nonlinear time history | `Newmark` / `HHT` / `GeneralizedAlpha`, `analysis Transient`, convergence controls | P1 |
| Variable time step | `analysis VariableTransient`, adaptive substepping | P2 |
| Arc-length / limit-point | `integrator ArcLength` / `ArcLength1` | P2 |
| Damping | `rayleigh`, `modalDamping` | P1 |
| Recorders | `recorder Node`, `recorder Element`, `recorder Drift`, envelope recorders | P0/P1 |
| Algorithms | `Linear`, `Newton`, `ModifiedNewton`, `NewtonLineSearch`, `KrylovNewton`, `SecantNewton`, `BFGS`, `Broyden` | P0/P1 |
| Systems | `BandGen`, `BandSPD`, `ProfileSPD`, `SuperLU`, `UmfPack`, `SparseSYM` | P1 |

### 3.6 Engine limitations the GUI must communicate

- No native Pivot material in 3.8.0.
- No direct `uniaxialMaterial Takeda`; only a low-level unloading-rule
  primitive and approximations through `Hysteretic`/`HystereticSM`.
- 2D bearing elements are not usable in the current fixed 3D model. Use the
  `*3d` variants.
- `responseSpectrumAnalysis` only computes modal displacements. The GUI must
  perform SRSS/CQC combination and store the combined result.
- `forceBeamColumn` is sensitive to section definition: a fiber section must
  have non-zero stiffness about both bending axes, and enough fibers to avoid
  an ill-conditioned flexibility matrix.
- Modal analysis requires mass. The current density-derived lumped-mass option
  must be extended to nonlinear elements and link masses.

---

## 4. Priority list

Priorities are based on user value, dependency order and risk. “Engine ready”
does not mean “GUI ready”.

### P0 — Nonlinear frame foundation (first release, v1.1)

| ID | Feature | Why it comes first | Depends on |
|---|---|---|---|
| P0-1 | Analysis-case and result framework | Every nonlinear/dynamic feature needs named cases, solver settings, recorders and separate result sets | — |
| P0-2 | Material registry and material editor v2 | Current flat material form cannot represent the requested models | P0-1 |
| P0-3 | Fiber section builder | Unlocks nonlinear beams, columns and moment–curvature | P0-2 |
| P0-4 | `forceBeamColumn` / `dispBeamColumn` | First real distributed-plasticity frame element | P0-3 |
| P0-5 | Nonlinear static / pushover | First complete nonlinear workflow users can validate | P0-4 |
| P0-6 | ZeroLength / TwoNodeLink + rigidLink / equalDOF / rigidDiaphragm | Link, rigid-offset and spring modelling; foundation for dampers and bearings | P0-1 |
| P0-7 | Core dampers (`Viscous`, `Maxwell`, `BilinearOilDamper`) | High-value seismic devices; uses link elements | P0-6 |
| P0-8 | Hysteresis editor for `Hysteretic` / `HystereticSM` core presets | Bilinear, trilinear and Takeda-like loops in one editor | P0-2 |

### P1 — Seismic analysis and isolation (v1.2)

| ID | Feature | Why | Depends on |
|---|---|---|---|
| P1-1 | Ground-motion manager and time series | Required by all time-history work | P0-1 |
| P1-2 | Linear elastic time history | Validates the time-history pipeline and units | P1-1 |
| P1-3 | Response spectrum analysis + SRSS/CQC | Efficient seismic demand without time history | P0-1, modal |
| P1-4 | Nonlinear time history | Core nonlinear seismic workflow | P1-2, P0-4 |
| P1-5 | Seismic isolation bearings | High-value bridge/building isolation workflow | P0-6 |
| P1-6 | Extended dampers and flag/self-centering materials | `FlagShape`, `SelfCentering`, `Pinching4`, `BoucWen` | P0-2, P0-6 |
| P1-7 | Time-history, response-spectrum and pushover result views | Without plots and envelopes the analyses are not usable | P0-5, P1-2/3/4 |

### P2 — Advanced nonlinear modelling (v1.3)

| ID | Feature | Why later | Depends on |
|---|---|---|---|
| P2-1 | Lumped plasticity: `beamWithHinges`, hinge integration, IMK materials | Requires stable fiber and link workflows first | P0-4 |
| P2-2 | Advanced materials: `Steel4`, `Concrete07`, `ConcreteCM`, `ReinforcingSteel`, `Fatigue`, `HystereticSmooth/Asym` | Larger parameter surfaces and calibration | P0-2 |
| P2-3 | Nonlinear walls and shells: `MVLEM`, `SFI_MVLEM`, layered shell | Different element/section workflows and result extraction | P0-3, P1-4 |
| P2-4 | Advanced links/contact and `SectionAggregator` | Specialist use cases | P0-6, P0-3 |
| P2-5 | Arc-length, variable transient, solver fallback chains | Needed for hard convergence cases | P0-5, P1-4 |
| P2-6 | Performance assessment outputs: drift, hinge rotation, DCR, envelopes | Requires sections, hinges and recorders | P0-5, P2-1 |

### P3 — Research and special-purpose

| ID | Feature | Note |
|---|---|---|
| P3-1 | Exact Takeda / Pivot models | Not native as standalone materials; requires a custom material plugin or accepted approximation |
| P3-2 | Soil–structure interaction (`PySimple1`, `TzSimple1`, `QzSimple1` and liquefaction variants) | Requires geotechnical parameter workflows and far-field boundaries |
| P3-3 | Multi-support excitation and non-uniform ground motion | Requires per-support time series and `MultiSupportPattern` |
| P3-4 | Staged construction / model activation | OpenSees supports regions and staged analysis, but the GUI model has no construction-stage concept |
| P3-5 | Explicit/dynamic contact and impact | Specialist nonlinear contact workflows |
| P3-6 | Fiber stress/strain state colouring and damage contours | High visual value, but depends on fiber result extraction |

---

## 5. GUI target design

### 5.1 Ribbon changes

| Tab | New / changed groups |
|---|---|
| **Properties** | `Materials` (v2), `Sections` (elastic/fiber), `Links & Dampers`, `Bearings` |
| **Boundary** | `Supports`, `Rigid Links`, `Equal DOF`, `Diaphragms` |
| **Load** | `Load Cases`, `Combinations`, `Ground Motions`, `Response Spectra`, `Nodal Loads`, `Element Loads`, `Self Weight` |
| **Analysis** | `Analysis Cases`, `Check Model`, `Run Case`, `Pause/Cancel`, `Results`, `Lock` |
| **Results** | Static, Modal, Response Spectrum, Time History, Pushover, beam diagrams, deformation, envelopes |
| **Tools** | Tcl export, examples, documentation |

The current `scenario_combo` in the status bar stays as the load-case/combination
selector. A separate **analysis case** selector belongs in the Analysis ribbon
and at the top of the Results workspace.

### 5.2 New dialogs

#### A. Material Editor v2

Layout:

- Left: material library tree by family (Elastic, Steel, Concrete, Hysteretic,
  Damper, Bearing, Wrapper, Advanced).
- Right: dynamic parameter form generated from a material registry.
- Bottom: monotonic backbone preview in v1.1; cyclic preview in v1.2.
- Buttons: New, Duplicate, Delete, Assign to selected elements.

The form must be generated from metadata, not a giant `if/elif` chain. Each
parameter needs a label, unit type, default, range, tooltip and section grouping.

#### B. Fiber Section Builder

Layout:

- Template: I/W, rectangular hollow, circular hollow, rectangle, circle,
  L, T, polygon, or custom.
- Mesh: target fiber size or number of divisions; fiber count and estimated
  analysis cost.
- Materials: assign steel, confined concrete, unconfined concrete and optional
  cover material.
- Preview: coloured cross-section with fibers, centroid axes and computed
  `A`, `Iy`, `Iz`, `J`.
- Validation: every fiber must reference a material; section must have non-zero
  bending stiffness in both axes.

Implementation approach:

1. Generate a polygon outline from the existing section geometry.
2. Decompose standard shapes into rectangles/rings for efficient meshing.
3. For irregular shapes, use a bounded grid and point-in-polygon clipping.
4. Emit `fiber(y, z, area, materialTag)` commands.
5. Store the mesh in the project so it round-trips exactly.

#### C. Analysis Case Manager

Layout:

- Left: list of analysis cases.
- Right: tabs `Type`, `Loading`, `Solver`, `Damping`, `Output`.
- Type-specific controls:
  - Static: load case/combination, load steps.
  - Pushover: control node/DOF, target displacement, step size, load pattern.
  - Modal: number of modes.
  - Response spectrum: spectrum, direction, damping, combination method.
  - Linear/nonlinear time history: ground motion, direction, dt, duration,
    integrator, Rayleigh/modal damping, convergence settings.
- Run button validates the model and starts the worker.

#### D. Ground Motion / Spectrum dialogs

- Import AT2, CSV, TXT or pasted values.
- Show dt, number of points, peak ground acceleration, duration and a plot.
- Store values in base units (`mm/s²`) or convert from `g` at import.
- Spectrum: period/acceleration table, damping ratio, import from CSV, plot.
- Optional code-spectrum generator in P2.

#### E. Links, dampers and bearings

One shared two-node component dialog with type-specific panels:

- `ZeroLength` / `TwoNodeLink`: DOF assignment, material per DOF, orientation.
- Damper: viscous, Maxwell, bilinear oil, Coulomb, friction spring.
- Bearing: elastomeric, lead-rubber, flat slider, single FP, triple FP.
- Rigid link / equal DOF / diaphragm: separate constraint dialogs.

#### F. Results workspace

Add a result-type selector and dedicated pages:

- **Static:** existing summary, displacements, reactions, element forces.
- **Modal:** periods, frequencies, participating mass, mode animation.
- **Response spectrum:** spectrum plot, modal contributions, combined
  displacements, base shear.
- **Time history:** time-series plots, peak/envelope tables, drift, base shear,
  damper/bearing hysteresis loops, animation by time step.
- **Pushover:** base shear vs roof displacement, step table, hinge rotation and
  hinge state, deformed shape at selected step.

Use `numpy` for result arrays and Qt painting for plots. No new plotting
dependency is required.

### 5.3 Model tree and tables

Add tree groups:

- `Analysis Cases`
- `Ground Motions`
- `Response Spectra`
- `Links & Constraints`

Double-click opens the relevant editor. Tables gain columns for element type,
analysis case and component properties. Existing Excel copy/paste behavior must
continue to work.

### 5.4 Progress, cancellation and locking

Long analyses must not block the GUI:

- Run in a `QThread` worker.
- Use `ops.analyze(1)` per step where possible, emit progress after each step.
- Provide a cancel flag checked between steps.
- Disable model edits while an analysis is running.
- On completion, lock the model and show results; on failure, keep the previous
  results and show the solver message with the failed step number.

---

## 6. Data-model plan

### 6.1 Project schema v2

Keep v1 projects readable. Add a migration layer in `Project.from_dict`.

New top-level collections:

```python
project.analysis_cases: dict[str, AnalysisCase]
project.ground_motions: dict[str, GroundMotion]
project.spectra: dict[str, ResponseSpectrum]
project.constraints: list[Constraint]
project.fiber_sections: dict[int, FiberSection]   # or section.kind == "Fiber"
```

### 6.2 Material

Current `Material` has flat `E`, `fy`, `b`, `fc`, `epsc0`, `fpcu`, `epsU`.
Replace this gradually:

```python
@dataclass
class Material:
    tag: int
    name: str
    kind: str                     # "Steel02", "Concrete02", "HystereticSM", ...
    params: dict[str, float]      # authoritative new representation
    E: float = 200.0              # v1 compatibility shim
    ...
```

The registry owns:

- parameter labels, units, defaults and limits;
- the OpenSees command builder;
- optional monotonic/cyclic preview function;
- validation rules.

This avoids adding dozens of fields to the dataclass.

### 6.3 Section

Add:

```python
@dataclass
class FiberDef:
    y: float
    z: float
    area: float
    material: int

@dataclass
class Section:
    kind: str = "Elastic"          # Elastic | Fiber | Aggregated
    fibers: list[FiberDef] = []
    gj: float = 0.0
    ...
```

Keep the current shape/property fields for elastic sections and standard
sections. A fiber section may reference the same shape for preview and meshing.

### 6.4 Element

Add a typed element registry. Do not put every element-specific field into the
dataclass:

```python
@dataclass
class Element:
    tag: int
    kind: str                      # beam | truss | shell | force_beam | two_node_link | bearing | ...
    params: dict                   # section_i, section_j, integration, dofs, materials, ...
    ...
```

Compatibility rule: existing `kind="beam"` continues to mean
`elasticBeamColumn`; new nonlinear types use explicit names.

### 6.5 Constraints

```python
@dataclass
class Constraint:
    kind: str                      # rigid_link | rigid_diaphragm | equal_dof
    master: int
    slaves: list[int]
    dofs: list[int] = []           # for equalDOF
    link_type: str = "beam"        # for rigidLink
    perp: int = 3                  # for rigidDiaphragm
```

### 6.6 Analysis cases

```python
@dataclass
class AnalysisCase:
    name: str
    kind: str                      # static | pushover | modal | response_spectrum | linear_th | nonlinear_th
    load_case: str = ""
    steps: int = 10
    control_node: int = 0
    control_dof: int = 1
    target_displacement: float = 0.0
    integrator: str = "Newmark"
    algorithm: str = "Newton"
    tolerance: float = 1e-6
    max_iterations: int = 50
    dt: float = 0.01
    duration: float = 0.0
    damping: dict = field(default_factory=dict)
    ground_motion: str = ""
    direction: int = 1
    spectrum: str = ""
    combination: str = "SRSS"
    recorders: list[dict] = field(default_factory=list)
```

A default compatibility case is created from the existing `settings` when a v1
project is loaded.

### 6.7 Results

Introduce a result base class and subclasses:

```
AnalysisResults
├── StaticResults        (existing, extended)
├── ModalResults         (existing, extended)
├── ResponseSpectrumResults
├── TimeHistoryResults
└── PushoverResults
```

`TimeHistoryResults` stores:

- time vector;
- node displacement/velocity/acceleration arrays for requested nodes;
- element force arrays for requested elements;
- drift and base-shear arrays;
- damper/bearing force-displacement arrays;
- peak/envelope tables.

`PushoverResults` stores:

- step number, control displacement, base shear;
- element hinge rotation/state for each step;
- deformed shape per step (or enough data to regenerate it).

Do not store every result for every node in every time step by default. Store
requested channels and compute envelopes.

---

## 7. Solver and model-builder plan

### 7.1 Split `opsgen.py` without breaking callers

Keep `opsgen.run_static()` and `opsgen.run_modal()` as compatibility facades.
Add focused modules:

| Module | Responsibility |
|---|---|
| `app/uniaxial.py` | Material registry, command generation, validation, preview curves |
| `app/fiber.py` | Section meshing, fiber definitions, section property verification |
| `app/elements.py` | Element-type registry and OpenSees command construction |
| `app/analysis.py` | AnalysisCase, GroundMotion, ResponseSpectrum, solver profiles |
| `app/runner.py` | Threaded analysis runner, step loop, recorders, cancellation |
| `app/results_models.py` | Result containers and combination logic |

`opsgen.build()` becomes the shared model builder used by static, modal,
pushover and time-history runners.

### 7.2 Material command generation

Implement the registry for the first release:

- `Elastic`, `ElasticPP`, `Steel01`, `Steel02`
- `Concrete01`, `Concrete02`, `Concrete04`
- `Hardening`
- `Hysteretic` (2–3 point)
- `HystereticSM` (2–7 point)
- `Viscous`, `Maxwell`, `BilinearOilDamper`
- `FlagShape`, `SelfCentering`
- `Pinching4` (P1)

Every command builder must have a unit test that compares the emitted argument
list to a known-good example.

### 7.3 Fiber section construction

For each fiber section:

1. Validate at least two non-zero-area fibers and non-zero `Iy`/`Iz`.
2. Emit `ops.section("Fiber", tag, "-GJ", gj)`.
3. Emit one `ops.fiber(y, z, area, matTag)` per fiber.
4. Create beam integration:
   - `Legendre` with 3–5 points for distributed plasticity.
   - `HingeRadau`/`HingeMidpoint` for concentrated plasticity in P2.
5. Create `forceBeamColumn` with `geomTransf` (Linear/PDelta/Corot).
6. For 3D, include torsional stiffness and mass.

Verification: compute fiber-section `A`, `Iy`, `Iz` and compare to the
section editor's reported values within 1%.

### 7.4 Nonlinear static / pushover

Two modes:

- **Load control:** apply a reference load pattern in increments. Use for
  monotonic gravity or lateral load up to a target factor.
- **Displacement control:** control node and DOF, target displacement, step
  size. This is the default pushover method.

Recommended solver profile:

```
constraints Transformation
numberer RCM
system UmfPack or BandGen
test NormDispIncr 1e-6 50 0
algorithm Newton
integrator DisplacementControl node dof dU
analysis Static
```

Add automatic fallback to `ModifiedNewton`/`NewtonLineSearch` and smaller steps
when convergence fails. Report the exact step and load factor.

### 7.5 Time history

Ground-motion import:

- AT2: parse time step, acceleration values, optional scale.
- CSV/TXT: first column time or single acceleration column plus dt.
- Convert `g` to `mm/s²` using `g = 9806.65 mm/s²`.
- Store the raw values and the conversion metadata.

Build:

```
timeSeries Path tsTag -dt dt -values ... -factor scale
pattern UniformExcitation patternTag direction -accel tsTag
```

Analysis profiles:

- Linear elastic: `Newmark 0.5 0.25`, `Linear` algorithm.
- Nonlinear: `Newmark` or `HHT`, `Newton`, adaptive substepping, Rayleigh
  damping, `NormDispIncr` convergence test.

Damping:

- Rayleigh: target damping ratio, two periods; compute `alphaM`, `betaK`.
- Modal damping: mode-by-mode factors for response spectrum and linear time
  history.

### 7.6 Response spectrum

1. Run `eigen` and `modalProperties`.
2. For each mode, call `responseSpectrumAnalysis` with the appropriate
   spectrum values and direction, or compute modal displacements from
   eigenvector × participation factor × spectral acceleration.
3. Read modal displacements and element forces for each mode.
4. Combine with SRSS (default) or CQC.
5. Store combined nodal displacements and element forces; report participating
   mass and modal contributions.

The GUI must display the spectrum curve and the modal combination results.

### 7.7 Links, dampers, bearings

- `ZeroLength`: six DOFs, optional zeroLength materials per DOF.
- `TwoNodeLink`: discrete DOFs with material per DOF and orientation vector.
- `rigidLink`: constraint command; no element tag.
- `equalDOF`: constraint command.
- `rigidDiaphragm`: constraint command.
- Bearings: implement 3D variants only:
  - `ElastomericBearingPlasticity3d`
  - `ElastomericBearingBoucWen3d`
  - `LeadRubberX`
  - `FlatSliderSimple3d`
  - `SingleFPSimple3d`
  - `TripleFrictionPendulum` (P2)
- Dampers are uniaxial materials on link elements. Provide default vertical
  stiffness in parallel with the damper where required.

### 7.8 Recorders and result extraction

For each analysis case, create only the requested recorders:

- Node: displacement, velocity, acceleration, reaction.
- Element: local forces, section deformation, hinge rotation, damper force.
- Drift: story drift between node pairs.
- Envelope: peak nodal displacement/acceleration.

Read recorder files after the analysis, parse to arrays and delete temporary
files. For short analyses, direct per-step `nodeDisp`/`eleResponse` calls are
also acceptable. Test both paths.

### 7.9 Tcl export

Extend `export_tcl()` so it emits the same model and analysis case as the GUI:

- all material commands;
- fiber sections and beam integrations;
- advanced element types;
- constraints;
- time series, patterns, recorders;
- selected analysis sequence and solver options;
- comments identifying the analysis case.

Add a test that exports a nonlinear model and runs it through OpenSeesPy.

### 7.10 MCP server

Add generic tools rather than one tool per material:

- `add_material(name, kind, params)`
- `add_fiber_section(name, shape, mesh, materials)`
- `add_element(kind, node_tags, ...)` (extend existing)
- `add_constraint(kind, master, slaves, ...)`
- `add_ground_motion(name, dt, values, scale)`
- `add_response_spectrum(name, periods, values, damping)`
- `add_analysis_case(name, spec)`
- `run_analysis_case(name)`
- `get_analysis_results(name, node_tags, element_tags)`
- `get_pushover_results(name)`
- `get_time_history_results(name)`

Keep the current 43 tools working. Update `tests/test_mcp.py` and
`tests/test_mcp_gui.py`.

---

## 8. Work packages, tasks and acceptance criteria

### WP-1 — Analysis-case framework (P0)

Tasks:

1. Add `AnalysisCase` dataclass and project persistence v2.
2. Add a compatibility default case for v1 projects.
3. Add Analysis Case manager dialog.
4. Refactor `run_static()` and `run_modal()` to run through the case framework.
5. Add a threaded runner with progress/cancel signals.
6. Add `AnalysisResults` base and per-case result selection.

Done when:

- Existing static/modal workflows behave identically through the new case UI.
- A case can be duplicated, renamed, saved, loaded and exported.
- The GUI remains responsive during an analysis.
- All existing tests pass without changes to their numerical expectations.

### WP-2 — Material registry and editor v2 (P0)

Tasks:

1. Implement `uniaxial.py` registry with parameter metadata.
2. Migrate existing four materials to the registry.
3. Build dynamic material form and validation.
4. Add monotonic backbone preview.
5. Add command-generation tests for every material in the first release.

First-release materials: `Elastic`, `ElasticPP`, `Steel01`, `Steel02`,
`Concrete01`, `Concrete02`, `Concrete04`, `Hardening`, `Hysteretic`,
`HystereticSM`, `Viscous`, `Maxwell`, `BilinearOilDamper`, `FlagShape`,
`SelfCentering`, `Pinching4`.

Done when:

- A user can create, edit and assign these materials without touching JSON.
- Invalid parameters are caught before the solver starts.
- The emitted OpenSees command matches the documented syntax.

### WP-3 — Fiber section builder (P0)

Tasks:

1. Add `FiberDef` and `Section.kind`.
2. Implement meshing for I, box, pipe, rectangle, circle, L, T and polygon.
3. Add material assignment and live preview.
4. Validate section stiffness and fiber count.
5. Round-trip fiber sections through save/load and tables.
6. Emit and test `section Fiber` + `fiber` commands.

Done when:

- A standard W section can be converted to fibers in under a minute.
- The preview reports `A`, `Iy`, `Iz` close to the elastic reference.
- A fiber cantilever with `forceBeamColumn` runs and produces a moment–curvature
  response.

### WP-4 — Nonlinear frame elements (P0)

Tasks:

1. Add `forceBeamColumn` and `dispBeamColumn` element types.
2. Add beam integration choice (`Legendre`, `NewtonCotes`, `Radau`).
3. Add geometric transformation choice (`Linear`, `PDelta`, `Corot`).
4. Add element mass and orientation options.
5. Add nonlinear element results extraction (end forces, section forces).

Done when:

- A nonlinear cantilever matches a hand calculation for yield displacement.
- A fiber portal frame runs under gravity and lateral load.
- Existing elastic elements remain unchanged.

### WP-5 — Pushover (P0)

Tasks:

1. Add `DisplacementControl` case type.
2. Add control node/DOF, target displacement and step size.
3. Add base-shear and roof-displacement recorders.
4. Add hinge rotation/state extraction.
5. Add capacity-curve plot and step table.
6. Add model-lock and result invalidation.

Done when:

- A cantilever pushover capacity curve matches the analytical yield point.
- A portal-frame mechanism forms in the expected sequence.
- The user can select a pushover step and view the deformed shape.

### WP-6 — Links and constraints (P0)

Tasks:

1. Add `Project.constraints` and tree group.
2. Add `rigidLink`, `rigidDiaphragm`, `equalDOF` commands.
3. Add `ZeroLength` and `TwoNodeLink` element types.
4. Add DOF/material assignment UI.
5. Add link force/displacement results.

Done when:

- A rigid offset produces the expected kinematic constraint.
- A zero-length rotational spring reproduces a target moment–rotation curve.
- Link results appear in the results table.

### WP-7 — Dampers (P0)

Tasks:

1. Add viscous, Maxwell, bilinear-oil and Coulomb damper materials.
2. Add damper assignment through link elements.
3. Add force–velocity / force–displacement hysteresis output.
4. Add validation of units and direction.

Done when:

- A viscous damper SDOF matches the closed-form damping ratio.
- A bilinear damper loop has the expected yield force and energy dissipation.

### WP-8 — Hysteresis editor and presets (P0/P1)

Tasks:

1. Add common `Hysteretic` 2/3-point editor with pinching and damage.
2. Add `HystereticSM` 2–7 point editor with `beta` and degradation.
3. Add presets:
   - Steel bilinear (`Steel01`)
   - Steel bilinear with hardening (`Hardening`)
   - RC trilinear (`Hysteretic` 3-point)
   - Takeda-like RC hinge (`HystereticSM` preset; clearly labelled)
   - Flag/self-centering (`FlagShape`, `SelfCentering`)
4. Add cyclic preview (P1).
5. Add parameter validation and help text.

Done when:

- A user can produce a trilinear loop and a flag loop without writing Tcl.
- The preset names and limitations are visible in the UI.

### WP-9 — Ground motions and linear time history (P1)

Tasks:

1. Add `GroundMotion` model and persistence.
2. Add AT2/CSV/TXT import and plot.
3. Add unit conversion and scale factor.
4. Add `UniformExcitation` and `Path` command generation.
5. Add linear Newmark time-history case.
6. Add node response recorders and time-series plots.
7. Add animation by time step.

Done when:

- An elastic SDOF response matches the closed-form harmonic/ground-motion
  solution.
- Units are correct for g, mm/s², kN, t and s.

### WP-10 — Response spectrum (P1)

Tasks:

1. Add `ResponseSpectrum` model and import.
2. Add spectrum plot and damping ratio.
3. Run eigen + modalProperties.
4. Compute modal displacements for each mode.
5. Implement SRSS and CQC combination.
6. Store combined displacements and element forces.
7. Add spectrum/modal contribution results page.

Done when:

- A 2-DOF benchmark matches a hand SRSS/CQC calculation.
- The result page shows modal periods, participating mass and combined base
  shear.

### WP-11 — Nonlinear time history (P1)

Tasks:

1. Add Newmark/HHT case settings.
2. Add Rayleigh and modal damping.
3. Add convergence test and algorithm settings.
4. Add adaptive step reduction on failure.
5. Add nonlinear recorders and envelopes.
6. Add cancel/progress and result locking.

Done when:

- The elastic case matches the linear time-history result.
- A yielding SDOF produces the expected permanent displacement.
- Energy balance is acceptable and the analysis reports failed steps clearly.

### WP-12 — Seismic isolation (P1)

Tasks:

1. Add bearing material/element registry.
2. Implement 3D elastomeric, lead-rubber, flat-slider and single-FP bearings.
3. Add parameter forms and unit-aware fields.
4. Add bearing force–displacement and displacement results.
5. Add model check for bearing node connectivity and DOF alignment.

Done when:

- A base-isolated SDOF reproduces the target isolation period and hysteresis
  loop.
- The bearing displacement is reported in the results.

### WP-13 — Lumped plasticity (P2)

Tasks:

1. Add `beamWithHinges` element.
2. Add hinge integration types.
3. Add hinge length and hinge section/material assignment.
4. Add IMK material presets and moment–rotation editor.
5. Add hinge rotation/state results.

Done when:

- A beamWithHinges cantilever matches a plastic-hinge hand calculation.
- Hinge formation is visible in the pushover results.

### WP-14 — Advanced materials and walls/shells (P2)

Tasks:

1. Add advanced steel/concrete material pages.
2. Add `HystereticSmooth`, `HystereticAsym`, `Steel4`, `Concrete07`,
   `ReinforcingSteel`, `Fatigue`.
3. Add `MVLEM`/`SFI_MVLEM` and layered shell sections.
4. Add wall/shell result extraction and validation.
5. Add advanced material help and calibration notes.

Done when:

- A benchmark RC wall and a layered shell run successfully.
- Advanced material commands are covered by unit tests.

### WP-15 — Results, Tcl, MCP and documentation (continuous)

Tasks:

1. Add result pages for each analysis type.
2. Add CSV/PNG export.
3. Add Tcl export for every new feature.
4. Add MCP tools and tests.
5. Add example projects: nonlinear frame, pushover, response spectrum,
   time history, isolated bridge/pier.
6. Update README, screenshots and user guide.

Done when:

- Every GUI feature has a Tcl/MCP equivalent or a documented limitation.
- The installer contains all new examples and tests pass from source and frozen
  builds.

---

## 9. Verification and benchmark plan

| Benchmark | Purpose |
|---|---|
| Elastic cantilever | Regression against current solver |
| Steel01 cantilever yield displacement | Validate nonlinear material and element |
| Fiber section moment–curvature | Validate fiber meshing and section integration |
| Fiber cantilever pushover vs hand calculation | Validate forceBeamColumn and displacement control |
| Portal frame pushover mechanism | Validate hinge formation and post-yield behaviour |
| Steel02 cyclic material test | Validate cyclic parameters and preview |
| Trilinear Hysteretic loop | Validate trilinear editor |
| FlagShape loop | Validate flag/self-centering material |
| ZeroLength rotational spring vs target moment–rotation | Validate link elements |
| Rigid link kinematics | Validate constraints |
| SDOF viscous damper | Validate damping force and energy |
| Base-isolated SDOF | Validate bearing period and hysteresis |
| Elastic SDOF time history | Validate time series, units and Newmark |
| Nonlinear SDOF time history | Validate convergence and permanent drift |
| 2-DOF response spectrum vs hand SRSS/CQC | Validate modal combination |
| Isolated bridge time history | Validate full isolation + time-history workflow |
| Tcl export equivalence | Validate source/frozen export |

Each benchmark gets:

- a headless solver test in `tests/test_solver.py`;
- a command-generation unit test;
- a GUI smoke test in `tests/test_gui.py` where practical;
- an MCP test for new tools;
- a short documentation note with expected values.

---

## 10. Effort estimate

| Phase | Scope | Estimate |
|---|---|---|
| Phase 0 | Analysis-case framework, persistence v2, material registry, threaded runner | 4–5 weeks |
| Phase 1 | Fiber sections, nonlinear frame elements, pushover, links, core dampers, hysteresis editor | 8–10 weeks |
| Phase 2 | Ground motions, linear/nonlinear time history, response spectrum, isolation, result views | 9–11 weeks |
| Phase 3 | Lumped plasticity, advanced materials, walls/shells, advanced solver options | 9–12 weeks |
| Phase 4 | Exact Takeda/Pivot, SSI, multi-support, staged construction, contact | 8–12 weeks |
| **Total** | Full roadmap | **~38–50 weeks** |

A smaller first release is recommended:

| Release | Contents | Estimate |
|---|---|---|
| v1.1 | WP-1 to WP-5 (nonlinear frame + pushover) | 10–12 weeks |
| v1.2 | WP-6 to WP-12 (links, dampers, time history, response spectrum, isolation) | +10–12 weeks |
| v1.3 | WP-13 to WP-15 (lumped plasticity, advanced materials, walls) | +10–14 weeks |

The estimates include implementation, tests, documentation, installer and
frozen-app verification, but not detailed code review or external validation by
a structural engineer.

---

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Nonlinear convergence failures | Users blame the GUI | Clear convergence settings, step reduction, algorithm fallback, step number in the error |
| Fiber section ill-conditioning | `forceBeamColumn` fails to invert flexibility | Validate non-zero `Iy`/`Iz`, minimum fiber count, warning before analysis |
| Unit mistakes for ground motion/spectra | Wrong results by orders of magnitude | Store base units, convert at import, display both raw and converted values |
| Large time-history output | Memory and UI slowdown | Store only requested channels; downsample plots; use envelope tables |
| Takeda/Pivot expectations | Users expect exact models that are not native | Label approximations clearly; put exact models in P3 after feasibility |
| Data migration | Old projects fail to open | Schema v2 with v1 compatibility default cases; round-trip tests |
| Long analyses freeze the GUI | Poor usability | Threaded runner, per-step progress, cancel flag, model lock |
| Tcl/MCP drift | Inconsistent results | Shared command builders and export tests |
| 2D bearing variants unusable | Wrong element choice | Expose only 3D variants in the model builder |
| Scope creep | No release | Freeze phases and require a working benchmark before adding the next material |

---

## 12. Recommended first sprint (2 weeks)

1. Freeze the engine baseline and record the exact `OpenSeesPy` version in the
   About/Diagnostics page.
2. Add schema v2 with `AnalysisCase`, migration from v1 and round-trip tests.
3. Implement the analysis-case manager skeleton and route the existing static
   and modal runs through it.
4. Implement the material registry and migrate the four existing materials.
5. Add command-generation tests for `Elastic`, `ElasticPP`, `Steel01`,
   `Steel02`, `Concrete01`, `Concrete02` and `Concrete04`.
6. Prototype the fiber section preview with an I-section mesh; do not connect it
   to the solver until the section validation tests pass.

Do not start with isolation bearings, Pivot or Takeda. Those depend on the
foundation above.

---

## 13. Immediate answer to the requested model list

| Requested item | Engine available? | First GUI release |
|---|---|---|
| Nonlinear material models | Yes, extensive library | v1.1 |
| Fiber modelling | Yes, fiber sections + force/disp beam-columns | v1.1 |
| Lumped plasticity | Yes, `beamWithHinges` + hinge integration + IMK | v1.3 |
| Link elements | Yes, ZeroLength/TwoNodeLink | v1.1 |
| Rigid links | Yes, `rigidLink` constraint | v1.1 |
| Seismic isolation | Yes, 3D elastomeric/lead-rubber/slider/FP bearings | v1.2 |
| Dampers | Yes, viscous/Maxwell/oil/Coulomb/friction | v1.1–v1.2 |
| Elastic response spectrum | Yes, `responseSpectrumAnalysis` + GUI combination | v1.2 |
| Linear elastic time history | Yes, `Newmark` + `UniformExcitation` | v1.2 |
| Nonlinear dynamic time history | Yes, `Newmark`/`HHT` + convergence controls | v1.2 |
| Nonlinear static / pushover | Yes, `DisplacementControl` | v1.1 |
| Bilinear hysteresis | Yes (`Steel01`, `Hardening`, `IMKBilin`, `ElasticBilin`) | v1.1 |
| Trilinear hysteresis | Yes (`Hysteretic`, `HystereticSM`, `Pinching4`, `MultiLinear`) | v1.1–v1.2 |
| Takeda hysteresis | Partial: unloading-rule primitive; no direct standalone material | v1.2 preset, exact v1.4 |
| Pivot hysteresis | Not native in 3.8.0 | v1.4 approximation or custom |
| Flag hysteresis | Yes (`FlagShape`, `SelfCentering`) | v1.2 |

---

## 14. Approval gates

Before starting each phase, confirm:

1. The engine version and command names are still valid.
2. The phase benchmark passes.
3. The project schema migration is backward compatible.
4. Source, frozen-app, GUI, MCP and installer tests pass.
5. The Tcl export matches the GUI model.
6. The documentation describes limitations, especially Takeda/Pivot.
