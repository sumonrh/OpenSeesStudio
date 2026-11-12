"""Catalogue of OpenSees uniaxial materials used by the hinge library.

Only structural material families are included here.  The definitions and
parameter names follow the OpenSees 3.8.0 command manual.  ``kind="spring"``
marks moment-rotation materials that are intended for a rotational spring
hinge; the current pushover implementation uses fibre hinges only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    unit: str = "ratio"          # stress | strain | ratio | length | force
    default: float = 0.0
    decimals: int = 4
    low: float = 0.0
    high: float = 1.0e12
    description: str = ""


@dataclass(frozen=True)
class MaterialSpec:
    key: str                     # exact OpenSees material name
    label: str
    family: str
    params: Tuple[ParamSpec, ...]
    image: str = ""
    kind: str = "fiber"          # fiber | spring
    note: str = ""
    docs: str = ""


def P(key: str, label: str, unit: str = "ratio", default: float = 0.0,
      decimals: int = 4, low: float = 0.0, high: float = 1.0e12,
      description: str = "") -> ParamSpec:
    return ParamSpec(key, label, unit, default, decimals, low, high, description)


S = "stress"
R = "ratio"
E = "strain"

MATERIALS: Dict[str, MaterialSpec] = {}


def add(spec: MaterialSpec) -> None:
    MATERIALS[spec.key] = spec


add(MaterialSpec(
    "Steel01", "Steel01 — bilinear steel", "Steel",
    (P("fy", "fy", S, 0.235, 6, 1e-6, 10,
       "Yield strength; first envelope point."),
     P("b", "b", R, 0.02, 4, 0.0, 0.99,
       "Post-yield tangent / initial elastic tangent.")),
    "steel01.gif",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel01.html",
    note="E is taken from the assigned element material."))
add(MaterialSpec(
    "Steel02", "Steel02 — Giuffré–Menegotto–Pinto steel", "Steel",
    (P("fy", "fy", S, 0.235, 6, 1e-6, 10, "Yield strength."),
     P("b", "b", R, 0.02, 4, 0.0, 0.99, "Strain-hardening ratio."),
     P("R0", "R0", R, 18.0, 2, 1.0, 50.0,
       "Transition curvature parameter."),
     P("cR1", "cR1", R, 0.925, 4, 0.0, 1.0,
       "Transition parameter cR1."),
     P("cR2", "cR2", R, 0.15, 4, 0.0, 1.0,
       "Transition parameter cR2.")),
    "steel02.jpg",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel02.html",
    note="E is taken from the assigned element material."))
add(MaterialSpec(
    "Hardening", "Hardening — bilinear isotropic/kinematic", "Steel",
    (P("fy", "sigmaY", S, 0.235, 6, 1e-6, 10, "Yield stress."),
     P("b", "b", R, 0.02, 4, 0.0, 0.95,
       "Target post-yield tangent ratio; converted to H_kin.")),
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Hardening.html",
    image="hardening.gif",
    note="H_iso is zero; H_kin is calibrated as bE/(1-b). E from the element material."))
add(MaterialSpec(
    "ElasticBilin", "ElasticBilin — bilinear elastic", "Steel",
    (P("b", "E2/E1", R, 0.05, 4, 0.0, 0.99,
       "Secondary stiffness ratio."),
     P("eps2", "eps2", E, 0.001, 6, 1e-9, 1.0,
       "Strain at which the secondary stiffness begins.")),
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/ElasticBilin.html",
    note="Unloading is elastic; there is no strength yield. E from the element material."))

add(MaterialSpec(
    "Concrete01", "Concrete01 — zero tensile strength", "Concrete",
    (P("fpc", "f'c", S, -0.030, 6, -1.0, -1e-6,
       "Compressive strength (negative)."),
     P("epsc0", "eps_c0", E, -0.002, 6, -1.0, -1e-9,
       "Strain at peak compressive strength (negative)."),
     P("fpcu", "f'cu", S, -0.006, 6, -1.0, 0.0,
       "Crushing strength (negative)."),
     P("epsU", "eps_u", E, -0.02, 6, -1.0, 0.0,
       "Strain at crushing strength (negative).")),
    "concrete01.gif",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Concrete01.html"))
add(MaterialSpec(
    "Concrete02", "Concrete02 — linear tension softening", "Concrete",
    (P("fpc", "f'c", S, -0.030, 6, -1.0, -1e-6,
       "Compressive strength (negative)."),
     P("epsc0", "eps_c0", E, -0.002, 6, -1.0, -1e-9,
       "Strain at peak compressive strength."),
     P("fpcu", "f'cu", S, -0.006, 6, -1.0, 0.0,
       "Crushing strength."),
     P("epsU", "eps_u", E, -0.02, 6, -1.0, 0.0,
       "Strain at crushing strength."),
     P("lambda", "lambda", R, 0.5, 4, 0.0, 1.0,
       "Unloading slope ratio at eps_u."),
     P("ft", "f_t", S, 0.003, 6, 0.0, 10.0,
       "Tensile strength."),
     P("Ets", "E_ts", S, 1.5, 6, 0.0, 1e6,
       "Tension softening stiffness (absolute).")),
    "concrete02.gif",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Concrete02.html",
    note="ft and Ets default to 0.1|f'c| and 0.1|f'c|/|epsc0|, the OpenSees "
         "values used when the optional arguments are omitted."))
add(MaterialSpec(
    "Concrete02IS", "Concrete02IS — initial-stiffness control", "Concrete",
    (P("fpc", "f'c", S, -0.030, 6, -1.0, -1e-6,
       "Compressive strength (negative)."),
     P("epsc0", "eps_c0", E, -0.002, 6, -1.0, -1e-9,
       "Strain at peak compressive strength."),
     P("fpcu", "f'cu", S, -0.006, 6, -1.0, 0.0,
       "Crushing strength."),
     P("epsU", "eps_u", E, -0.02, 6, -1.0, 0.0,
       "Strain at crushing strength."),
     P("lambda", "lambda", R, 0.5, 4, 0.0, 1.0,
       "Unloading slope ratio at eps_u."),
     P("ft", "f_t", S, 0.003, 6, 0.0, 10.0,
       "Tensile strength."),
     P("Ets", "E_ts", S, 1.5, 6, 0.0, 1e6,
       "Tension softening stiffness.")),
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Concrete02IS.html",
    note="E0 is taken from the assigned element material and must be positive; "
         "assign this hinge to concrete members (E ≈ 4700√f'c, in MPa), not to "
         "steel members. ft and Ets default to the OpenSees 0.1|f'c| values."))
add(MaterialSpec(
    "Concrete04", "Concrete04 — Popovics concrete", "Concrete",
    (P("fc", "f'c", S, -0.030, 6, -1.0, -1e-6,
       "Compressive strength (negative)."),
     P("ec", "eps_c0", E, -0.002, 6, -1.0, -1e-9,
       "Strain at peak compressive strength."),
     P("ecu", "eps_cu", E, -0.02, 6, -1.0, 0.0,
       "Ultimate compressive strain."),
     P("fct", "f_ct", S, 0.0, 6, 0.0, 10.0,
       "Tensile strength."),
     P("et", "eps_t", E, 0.0, 6, 0.0, 1.0,
       "Ultimate tensile strain."),
     P("beta", "beta", R, 0.4, 4, 0.0, 1.0,
       "Residual stress factor at ultimate tensile strain.")),
    "concrete04.png",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Concrete04.html",
    note="Ec is taken from the assigned element material."))

add(MaterialSpec(
    "Hysteretic", "Hysteretic — general pinching/damage", "Hysteretic",
    (P("fy", "fy", S, 0.235, 6, 1e-6, 10, "Yield stress/force."),
     P("b", "b", R, 0.02, 4, 0.0, 0.95, "Post-yield stiffness ratio."),
     P("ductility", "mu_u", R, 10.0, 3, 2.0, 100.0,
       "Ultimate/yield deformation ratio."),
     P("pinchX", "pinchX", R, 0.8, 3, 0.0, 1.0, "Pinching factor for deformation."),
     P("pinchY", "pinchY", R, 0.8, 3, 0.0, 1.0, "Pinching factor for force."),
     P("damage1", "damage1", R, 0.02, 4, 0.0, 1.0,
       "Damage due to ductility."),
     P("damage2", "damage2", R, 0.0, 4, 0.0, 1.0,
       "Damage due to energy."),
     P("beta", "beta", R, 0.4, 3, 0.0, 1.0,
       "Degraded unloading stiffness exponent.")),
    "hysteretic.gif",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Hysteretic.html",
    note="A 3-point envelope is generated from fy, E, b and ductility."))
add(MaterialSpec(
    "HystereticSM", "HystereticSM — multilinear pinching/damage", "Hysteretic",
    (P("fy", "fy", S, 0.235, 6, 1e-6, 10, "First envelope stress."),
     P("b", "b", R, 0.02, 4, 0.0, 0.95, "Post-yield stiffness ratio."),
     P("ductility", "mu_u", R, 10.0, 3, 2.0, 100.0,
       "Ultimate/yield deformation ratio."),
     P("pinch", "pinch", R, 0.8, 3, 0.0, 1.0, "Pinching factor."),
     P("damage", "damage", R, 0.02, 4, 0.0, 1.0,
       "Ductility/energy damage parameter."),
     P("beta", "beta", R, 0.4, 3, 0.0, 1.0,
       "Degraded unloading stiffness exponent."),
     P("degEnv", "degEnv", R, 0.0, 4, 0.0, 1.0,
       "Envelope degradation factor.")),
    "hystereticsm.jpg",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/HystereticSM.html",
    note="A 3-point positive/negative envelope is generated and passed with -posEnv/-negEnv flags."))
add(MaterialSpec(
    "HystereticSmooth", "HystereticSmooth — smooth hysteresis", "Hysteretic",
    (P("fy", "fbar", S, 0.235, 6, 1e-6, 10,
       "Hysteresis force/stress at zero deformation."),
     P("b", "kb/ka", R, 0.02, 4, 0.0, 0.99,
       "Ratio of tangent stiffness at zero to initial tangent stiffness."),
     P("beta", "beta", R, -1.0, 4, -10.0, 10.0,
       "Hardening/softening parameter.")),
    "hystereticsmooth.gif",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/HystereticSmooth.html",
    note="ka is taken as E, kb as bE and fbar as fy."))
add(MaterialSpec(
    "HystereticAsym", "HystereticAsym — smooth asymmetric hysteresis", "Hysteretic",
    (P("fy", "f0", S, 0.235, 6, 1e-6, 10,
       "Hysteresis force/stress at zero deformation."),
     P("b", "kb/ka", R, 0.02, 4, 0.0, 0.99,
       "Ratio of tangent stiffness at zero to initial tangent stiffness."),
     P("beta1", "beta1", R, 0.4, 4, -10.0, 10.0,
       "Hardening/softening/asymmetry parameter."),
     P("beta2", "beta2", R, 0.2, 4, -10.0, 10.0,
       "Hardening/softening/asymmetry parameter."),
     P("gamma", "gamma", R, 1.0, 4, -10.0, 10.0,
       "Hardening/softening/asymmetry parameter.")),
    "hystereticasym.gif",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/HystereticAsym.html",
    note="ka is taken as E and kb as bE."))

add(MaterialSpec(
    "Pinching4", "Pinching4 — four-point pinched envelope", "Pinching / Bouc-Wen",
    (P("fy", "fy", S, 0.235, 6, 1e-6, 10,
       "Reference first-point stress/force."),
     P("b", "b", R, 0.02, 4, 0.0, 0.95,
       "Post-yield stiffness ratio used to generate the 4 points."),
     P("ductility", "mu_u", R, 10.0, 3, 2.0, 100.0,
       "Ultimate/yield deformation ratio."),
     P("rDisp", "rDisp", R, 0.5, 3, 0.0, 1.0,
       "Reloading deformation ratio."),
     P("rForce", "rForce", R, 0.2, 3, 0.0, 1.0,
       "Reloading force ratio."),
     P("uForce", "uForce", R, 0.0, 3, 0.0, 1.0,
       "Unloading force ratio."),
     P("gE", "gE", R, 10.0, 2, 0.0, 1000.0,
       "Energy dissipation capacity factor.")),
    "pinching4.jpg",
    docs="https://opensees.berkeley.edu/wiki/index.php/Pinching4_Material",
    note="The four envelope points are generated from fy, E, b and ductility; "
         "degradation exponents are fixed at zero and damageType='cycle'. "
         "A full point-by-point editor is future work."))
add(MaterialSpec(
    "BoucWen", "BoucWen — smooth hysteretic", "Pinching / Bouc-Wen",
    (P("alpha", "alpha", R, 0.05, 4, 0.0, 0.99,
       "Post-yield/initial stiffness ratio."),
     P("n", "n", R, 1.0, 2, 0.1, 20.0,
       "Sharpness of the hysteresis transition."),
     P("gamma", "gamma", R, 0.5, 3, -10.0, 10.0,
       "Hysteresis shape parameter."),
     P("beta", "beta", R, 0.5, 3, -10.0, 10.0,
       "Hysteresis shape parameter."),
     P("Ao", "A_o", R, 1.0, 3, 0.0, 100.0,
       "Tangent stiffness parameter."),
     P("deltaA", "deltaA", R, 0.0, 4, 0.0, 100.0,
       "Tangent stiffness degradation parameter."),
     P("deltaNu", "deltaNu", R, 0.0, 4, 0.0, 100.0,
       "Strength degradation parameter."),
     P("deltaEta", "deltaEta", R, 0.0, 4, 0.0, 100.0,
       "Stiffness degradation parameter.")),
    docs="https://opensees.berkeley.edu/wiki/index.php/BoucWen_Material",
    note="ko is taken from the assigned element material."))

add(MaterialSpec(
    "FlagShape", "FlagShape — flag-shaped hysteresis", "Flag / Self-centering",
    (P("fy", "fy", S, 0.235, 6, 1e-6, 10, "Yield force/stress."),
     P("b", "b", R, 0.02, 4, 0.0, 0.99,
       "Post-yield/flag stiffness ratio."),
     P("beta", "beta", R, 0.5, 3, 0.0, 1.0,
       "0 = bilinear elastic, 1 = bilinear hysteretic.")),
    "flagshape.png",
    docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/FlagShape.html",
    note="E is taken from the assigned element material; Eh = bE."))
add(MaterialSpec(
    "SelfCentering", "SelfCentering — flag-shaped with slip/bearing", "Flag / Self-centering",
    (P("fy", "sigAct", S, 0.235, 6, 1e-6, 10,
       "Forward activation stress/force."),
     P("b", "k2/k1", R, 0.02, 4, 0.0, 0.99,
       "Post-activation stiffness ratio."),
     P("beta", "beta", R, 0.5, 3, 0.0, 1.0,
       "Reverse/forward activation ratio."),
     P("epsSlip", "epsSlip", E, 0.0, 6, 0.0, 1.0,
       "Slip strain/deformation; 0 disables slip."),
     P("epsBear", "epsBear", E, 0.0, 6, 0.0, 1.0,
       "Bearing strain; 0 disables bearing."),
     P("rBear", "rBear", R, 0.0, 3, 0.0, 100.0,
       "Bearing stiffness / initial stiffness.")),
    "selfcentering.png",
    docs="https://opensees.berkeley.edu/wiki/index.php/SelfCentering_Material",
    note="k1 is taken from the assigned element material and k2 = b k1."))

# Moment-rotation models.  These are shown in the library and reference
# documentation, but are not assignable to the current fibre-hinge pushover.
for key, label, extra in (
        ("IMKBilin", "IMKBilin — bilinear IMK", ()),
        ("IMKPeakOriented", "IMKPeakOriented — peak-oriented IMK", ()),
        ("IMKPinching", "IMKPinching — pinching IMK", ())):
    params = [
        P("Ke", "Ke", "rot_stiffness", 50000.0, 3, 1e-6, 1e12,
          "Elastic rotational stiffness."),
        P("dp_pos", "dp_pos", "rotation", 0.01, 5, 1e-9, 1.0,
          "Pre-capping rotation, positive."),
        P("dpc_pos", "dpc_pos", "rotation", 0.05, 5, 1e-9, 1.0,
          "Post-capping rotation, positive."),
        P("du_pos", "du_pos", "rotation", 0.08, 5, 1e-9, 1.0,
          "Ultimate rotation, positive."),
        P("Fy_pos", "Fy_pos", "moment", 100.0, 3, 1e-6, 1e12,
          "Yield moment, positive."),
        P("FmaxFy_pos", "Fmax/Fy", R, 1.1, 4, 1.0, 10.0,
          "Maximum/yield strength ratio."),
        P("FresFy_pos", "Fres/Fy", R, 0.1, 4, 0.0, 1.0,
          "Residual/yield strength ratio."),
        P("Lamda_S", "Lambda_S", R, 0.5, 4, 1e-6, 100.0,
          "Cyclic strength deterioration parameter."),
        P("Lamda_C", "Lambda_C", R, 0.5, 4, 1e-6, 100.0,
          "Cyclic post-capping stiffness deterioration parameter."),
        P("Lamda_K", "Lambda_K", R, 0.5, 4, 1e-6, 100.0,
          "Cyclic unloading stiffness deterioration parameter."),
        P("c_S", "c_S", R, 1.0, 4, 1e-6, 100.0,
          "Strength deterioration rate."),
        P("c_C", "c_C", R, 1.0, 4, 1e-6, 100.0,
          "Post-capping stiffness deterioration rate."),
        P("c_K", "c_K", R, 1.0, 4, 1e-6, 100.0,
          "Unloading stiffness deterioration rate."),
        P("D_pos", "D_pos", R, 1.0, 4, 0.0, 1.0,
          "Cyclic deterioration rate, positive."),
        P("D_neg", "D_neg", R, 1.0, 4, 0.0, 1.0,
          "Cyclic deterioration rate, negative."),
    ]
    if key != "IMKBilin":
        params += [
            P("Lamda_A", "Lambda_A", R, 0.5, 4, 1e-6, 100.0,
              "Cyclic accelerated reloading stiffness deterioration parameter."),
            P("c_A", "c_A", R, 1.0, 4, 1e-6, 100.0,
              "Accelerated reloading stiffness deterioration rate."),
        ]
    if key == "IMKPinching":
        params += [
            P("kappaF", "kappaF", R, 0.5, 4, 0.0, 1.0,
              "Pinching force ratio."),
            P("kappaD", "kappaD", R, 0.5, 4, 0.0, 1.0,
              "Pinching deformation ratio."),
        ]
    add(MaterialSpec(
        key, label, "Moment-rotation (spring)", tuple(params),
        {"IMKBilin": "imkbilin.jpg", "IMKPeakOriented": "imkpeaked.jpg",
         "IMKPinching": "imkpinching.jpg"}[key],
        kind="spring",
        docs="https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/"
             + key + ".html",
        note="Moment-rotation model intended for a spring hinge. Not assignable "
             "to the current fibre-hinge pushover."))

FAMILIES = ("Steel", "Concrete", "Hysteretic", "Pinching / Bouc-Wen",
            "Flag / Self-centering", "Moment-rotation (spring)")


def materials_in(family: str) -> List[MaterialSpec]:
    return [m for m in MATERIALS.values() if m.family == family]


def defaults(key: str) -> Dict[str, float]:
    return {p.key: p.default for p in MATERIALS[key].params}


def image_path(key: str) -> str:
    name = MATERIALS[key].image
    if not name:
        return ""
    path = Path(__file__).resolve().parent / "assets" / "hysteresis" / name
    return str(path) if path.exists() else ""


def _hysteretic_points(fy: float, E: float, b: float, ductility: float):
    fy = abs(fy)
    E = max(E, 1e-9)
    ey = fy / E
    e2 = ey * 3.0
    eu = max(ey * ductility, e2 * 1.5)
    s2 = fy * (1.0 + b * 3.0)
    su = fy * (1.0 + b * ductility)
    return (fy, ey, s2, e2, su, eu)


def build_command(material: str, tag: int, params: Dict[str, float],
                  E: float) -> Tuple[str, list]:
    """Return ``(OpenSees material name, argument list)``."""
    p = {key: float(value) for key, value in params.items()}
    m = material
    E = max(float(E), 1e-9)
    if m == "Steel01":
        return m, [p["fy"], E, p["b"]]
    if m == "Steel02":
        return m, [p["fy"], E, p["b"], p["R0"], p["cR1"], p["cR2"]]
    if m == "Hardening":
        b = min(max(p["b"], 0.0), 0.95)
        Hk = b * E / max(1.0 - b, 1e-6)
        return m, [E, p["fy"], 0.0, Hk]
    if m == "ElasticBilin":
        return m, [E, p["b"] * E, p["eps2"],
                   E, p["b"] * E, -p["eps2"]]
    if m == "Concrete01":
        return m, [p["fpc"], p["epsc0"], p["fpcu"], p["epsU"]]
    if m == "Concrete02":
        return m, [p["fpc"], p["epsc0"], p["fpcu"], p["epsU"],
                   p["lambda"], p["ft"], p["Ets"]]
    if m == "Concrete02IS":
        return m, [E, p["fpc"], p["epsc0"], p["fpcu"], p["epsU"],
                   p["lambda"], p["ft"], p["Ets"]]
    if m == "Concrete04":
        return m, [p["fc"], p["ec"], p["ecu"], E, p["fct"], p["et"], p["beta"]]
    if m in ("Hysteretic", "HystereticSM"):
        s1, e1, s2, e2, s3, e3 = _hysteretic_points(
            p["fy"], E, p["b"], p["ductility"])
        if m == "Hysteretic":
            return m, [s1, e1, s2, e2, s3, e3,
                       -s1, -e1, -s2, -e2, -s3, -e3,
                       p.get("pinchX", 0.8), p.get("pinchY", 0.8),
                       p.get("damage1", 0.0), p.get("damage2", 0.0),
                       p.get("beta", 0.0)]
        return m, ["-posEnv", s1, e1, s2, e2, s3, e3,
                   "-negEnv", -s1, -e1, -s2, -e2, -s3, -e3,
                   "-pinch", p["pinch"], p["pinch"],
                   "-damage", p["damage"], 0.0,
                   "-beta", p["beta"],
                   "-degEnv", p["degEnv"]]
    if m == "HystereticSmooth":
        return m, [E, p["b"] * E, p["fy"], p["beta"]]
    if m == "HystereticAsym":
        return m, [E, p["b"] * E, p["fy"], p["beta1"], p["beta2"], p["gamma"]]
    if m == "Pinching4":
        s1, e1, _s2, _e2, _s3, _e3 = _hysteretic_points(
            p["fy"], E, p["b"], p["ductility"])
        eu = max(e1 * p["ductility"], e1 * 4.0)
        e2 = e1 * 2.0
        e3 = max(e2 * 1.2, eu * 0.5)
        s2 = s1 * 1.05
        s3 = s1 * (1.0 + p["b"] * p["ductility"] * 0.5)
        s4 = s1 * (1.0 + p["b"] * p["ductility"])
        e4 = eu
        rD, rF, uF = p["rDisp"], p["rForce"], p["uForce"]
        zeros = [0.0, 0.0, 0.0, 0.0]
        return m, [
            s1, e1, s2, e2, s3, e3, s4, e4,
            -s1, -e1, -s2, -e2, -s3, -e3, -s4, -e4,
            rD, rF, uF, rD, rF, uF,
            *zeros, 1.0, *zeros, 1.0, *zeros, 1.0,
            p["gE"], "cycle"]
    if m == "BoucWen":
        return m, [p["alpha"], E, p["n"], p["gamma"], p["beta"],
                   p["Ao"], p["deltaA"], p["deltaNu"], p["deltaEta"]]
    if m == "FlagShape":
        return m, [E, p["fy"], p["b"] * E, p["beta"]]
    if m == "SelfCentering":
        return m, [E, p["b"] * E, p["fy"], p["beta"],
                   p["epsSlip"], p["epsBear"], p["rBear"]]
    raise ValueError(f"{material} is a moment-rotation material; it cannot be "
                     "used in a fibre hinge.")
