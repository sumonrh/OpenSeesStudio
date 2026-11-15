# OpenSees element and boundary types

This is the implementation map for OpenSees 3.8 elements and constraints in OpenSees
Studio. It records what is already supported, what is available in OpenSees, and the
planned order for adding the rest.

## Implemented

| Studio | OpenSees | Notes |
|---|---|---|
| Beam | `elasticBeamColumn` | 3D elastic frame member |
| Truss | `truss` | 2-node axial element |
| Tension-only truss | `truss` + `uniaxialMaterial TensionOnly` | Wrapper returns zero in compression |
| Compression-only truss | `truss` + `uniaxialMaterial ENT` | Linear compression-only; ENT uses the material E |
| Cable | `corotTruss` + `uniaxialMaterial TensionOnly` | Large-displacement tension-only cable |
| Force beam-column | `forceBeamColumn` + fibre `section Fiber` + `beamIntegration` | Distributed plasticity frame member |
| Displacement beam-column | `dispBeamColumn` + fibre `section Fiber` + `beamIntegration` | Distributed plasticity frame member |
| Fibre section | `section Fiber` with mesh from the section outline | One material per member section |
| Beam integration | `Lobatto`, `Legendre`, `NewtonCotes`, `Radau` | 2-40 integration points |
| Elastomeric bearing | `elastomericBearingBoucWen` | Bouc-Wen shear plus elastic axial/rotational materials |
| Lead-rubber isolator | `LeadRubberX` | 3D lead-rubber bearing with heating parameters |
| Viscous damper | `twoNodeLink` + `uniaxialMaterial ViscousDamper` | Axial Maxwell damper |
| Oil damper | `twoNodeLink` + `uniaxialMaterial BilinearOilDamper` | Relief-valve damper |
| Shell | `ShellMITC4` | 4-node elastic shell |
| Point spring | `zeroLength` + `Elastic` | Linear spring support |
| Nonlinear point spring | `zeroLength` + `MultiLinear` | Symmetric force-deformation backbone |
| Tension-only spring | `zeroLength` + `Elastic`/`MultiLinear` + `TensionOnly` | Linear or curved |
| Compression-only spring | `zeroLength` + `ENT` | Linear compression-only |
| P-Y spring | `zeroLength` + `PySimple1` | Sand/clay p-y for piles |
| Rigid link | `rigidLink beam` / `bar` | Beam = 6 DOF; bar = translations |
| Equal DOF | `equalDOF` | Selected DOFs |
| Rigid diaphragm | `rigidDiaphragm` | Rigid plane about an axis |

`ENT` is a linear compression-only material. OpenSees has no generic
`CompressionOnly` wrapper for an arbitrary nonlinear curve; a compression-only
multi-linear spring is therefore rejected by the model check.

## Available OpenSees element families

The names below are the registered OpenSees element types, grouped by family. Some
require additional sections, materials, beam integrations or transformations.

### Axial, truss and cable

- `truss`, `Truss2`, `trussSection`
- `corotTruss`, `corotTrussSection`
- `InertiaTruss`
- `CatenaryCable` (3 DOF/node catenary formulation; requires distributed load and
  careful initial geometry; not exposed as the default cable because of its
  convergence restrictions)

### Beam-column

- `elasticBeamColumn`, `ElasticTimoshenkoBeam`
- `ModElasticBeam2d`, `ModElasticBeam3d`
- `forceBeamColumn`, `dispBeamColumn`
- `beamWithHinges` (currently used internally by pushover)
- `MVLEM`, `SFI_MVLEM`, `MVLEM_3D`, `E_SFI`, `MEFI`

### Shell, plane and solid

- `ShellMITC4`, `ShellMITC9`
- `ShellDKGQ`, `ShellNLDKGQ`, `ShellDKGT`, `ShellNLDKGT`
- `ASDShellQ4`, `ASDShellT3`
- `FourNodeQuad`, `quad`, `tri31`
- `SSPquad`, `SSPbrick`
- `brick8n`, `brick20n`, `brickUP`, `brick20nUP`
- `PML3D`, `PML2D` and the PML variants

### Contact and interface

- `zeroLengthContact2D`, `zeroLengthContact3D`
- `zeroLengthContactNTS2D`
- `ZeroLengthInterface2D`
- `SimpleContact2D`, `SimpleContact3D`
- `BeamContact2D`, `BeamContact2Dp`, `BeamContact3D`, `BeamContact3Dp`
- `BeamEndContact3D`, `BeamEndContact3Dp`
- `PileToe3D`

### Links and special connections

- `twoNodeLink`
- `zeroLength`, `zeroLengthND`, `zeroLengthSection`, `CoupledZeroLength`
- `MultipleShearSpring`, `MultipleNormalSpring`
- `ElasticTubularJoint`
- `Joint2D`, `BeamColumnJoint`

### Bearings, isolators and dampers

- `elastomericBearingBoucWen`, `elastomericBearingPlasticity`
- `ElastomericX`, `LeadRubberX`, `HDR`
- `FPBearingPTV`, `TripleFrictionPendulum`
- `ViscousDamper`, `BilinearOilDamper`
- `CastFuse`, `SAWS`, `ADC`-family devices where compiled

### Boundary and constraint types

- `fix` (nodal restraints)
- `rigidLink beam`, `rigidLink bar`
- `equalDOF`, `equalDOF_Mixed`
- `rigidDiaphragm`
- `zeroLength` spring supports (with any uniaxial material)
- `twoNodeLink` multi-directional support/link
- `imposedMotion` (support excitation)
- `zeroLengthContact*`, `SimpleContact*`, `BeamContact*` for contact boundaries

## Planned implementation sequence

1. **Coupled links and rotational springs** — `twoNodeLink`, `zeroLengthND`,
   `zeroLengthSection`, `CoupledZeroLength`. Adds multi-directional support springs,
   rotational hinges and coupled soil-spring groups.
2. **Nonlinear frame members** - `forceBeamColumn` and `dispBeamColumn` with fibre
   sections and `beamIntegration`; reuse the existing hinge/pushover material library.
   **Implemented in 1.0.9** for Lobatto, Legendre, NewtonCotes and Radau integration.
3. **Cable refinement** - optional `CatenaryCable` UI for users who need catenary
   equilibrium and thermal effects, alongside the current robust tension-only
   `corotTruss` cable; add `trussSection` and `corotTrussSection`.
4. **Contact and pile interfaces** - zeroLength contact, simple contact, beam contact
   and `PileToe3D`, with friction/penalty parameters and a contact results table.
5. **Bearings and isolators** - elastomeric bearings, friction pendulum, lead-rubber
   and viscous dampers, with device property dialogs and hysteresis previews.
   **Implemented in 1.0.9**: `elastomericBearingBoucWen`, `LeadRubberX`,
   `ViscousDamper` and `BilinearOilDamper`; friction-pendulum bearings remain future
   work.
6. **Advanced shells and solids** — ShellMITC9, ShellDKGQ/NLDKGQ, ASD shells, quad and
   brick families for geotechnical and thick-shell models.
7. **Joints and wall elements** — `Joint2D`, `BeamColumnJoint`, `MVLEM`, `SFI_MVLEM`,
   `E_SFI`, `MEFI`.
8. **Remaining materials/wrappers and verification** — expand the uniaxial material
   library (Hysteretic, BoucWen, Pinching4, SelfCentering, TensionOnly variants) and add
   benchmark models for each new element family.

Each phase should add model persistence, tree/dialog editing, viewport drawing,
OpenSees build support, Tcl export, result extraction and solver tests before the next
phase starts.
