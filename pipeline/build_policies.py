"""Build data/policies/*.json — the eight criteria trees.

Provenance, stated plainly because it matters more than the code here:

* The six NCD-derived trees were written by hand against the full NCD text
  fetched by ``fetch_policies.py`` (cached under ``pipeline/.cache/policies/``).
  Every node carries the section of the source it came from.
* The two LCD-derived trees (lumbar fusion, CGM) are paraphrases. CMS returns
  401 for LCD detail text without a licence token, so the specific thresholds
  could not be checked against the document. They are marked
  ``verification: "unverified-paraphrase"`` in the emitted JSON and the UI says
  so. They are here because the nesting is instructive, not because the numbers
  are authoritative.
* ``parse_policy.py`` runs the same job through an LLM and diffs its output
  against these files. It is a check on the hand-written trees, not their source.

Run: python3 pipeline/build_policies.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "data", "policies")
MANIFEST = os.path.join(HERE, ".cache", "policies", "manifest.json")

# Fallback URLs, used only when the fetch cache is absent, so that building the
# policies never silently invents a citation.
KNOWN_URLS = {
    "bariatric_surgery": ("NCD", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=57&ncdver=5"),
    "cochlear_implant": ("NCD", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=245&ncdver=3"),
    "tavr": ("NCD", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=355&ncdver=2"),
    "home_oxygen": ("NCD", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=169&ncdver=2"),
    "power_wheelchair": ("NCD", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=219&ncdver=2"),
    "pet_oncology": ("NCD", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=331&ncdver=4"),
    "lumbar_fusion": ("LCD", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=37848&ver=18"),
    "cgm": ("LCD", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=33822&ver=70"),
}


def load_sources() -> Dict[str, Dict[str, str]]:
    sources = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, "r", encoding="utf-8") as handle:
            for entry in json.load(handle):
                sources[entry["policy_id"]] = {
                    "url": entry["source_url"],
                    "type": entry["source_type"],
                    "title": entry["title"],
                    "display_id": entry["display_id"],
                }
    for policy_id, (source_type, url) in KNOWN_URLS.items():
        sources.setdefault(policy_id, {"url": url, "type": source_type, "title": policy_id, "display_id": ""})
    return sources


SOURCES = load_sources()


class Builder(object):
    """Collects nodes for one policy and keeps their source sections attached."""

    def __init__(self, policy_id: str, title: str, provenance: str, verification: str):
        self.policy_id = policy_id
        self.title = title
        self.provenance = provenance
        self.verification = verification
        self.url = SOURCES[policy_id]["url"]
        self.source_type = SOURCES[policy_id]["type"]
        self.nodes: Dict[str, Dict[str, Any]] = {}

    def _ref(self, section: str) -> Dict[str, str]:
        return {"section": section, "url": self.url}

    def leaf(self, node_id: str, label: str, section: str, key: str, op: str,
             value: Any, unit: Optional[str] = None) -> str:
        self.nodes[node_id] = {
            "id": node_id,
            "type": "LEAF",
            "n": None,
            "children": [],
            "label": label,
            "source_ref": self._ref(section),
            "predicate": {"key": key, "op": op, "value": value, "unit": unit},
        }
        return node_id

    def group(self, node_id: str, node_type: str, label: str, section: str,
              children: List[str], n: Optional[int] = None) -> str:
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "n": n,
            "children": children,
            "label": label,
            "source_ref": self._ref(section),
            "predicate": None,
        }
        return node_id

    def emit(self, root: str) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "title": self.title,
            "source_url": self.url,
            "source_type": self.source_type,
            "provenance": self.provenance,
            "verification": self.verification,
            "root": root,
            "nodes": self.nodes,
        }


HAND = "hand-written from the fetched NCD text; every node cites its section"
PARAPHRASE = "paraphrased from the published LCD; detail text is licence-gated and was not retrieved"
VERIFIED = "checked against source text"
UNVERIFIED = "unverified-paraphrase"


# ---------------------------------------------------------------------------
# 100.1 Bariatric Surgery
# ---------------------------------------------------------------------------

def bariatric() -> Dict[str, Any]:
    b = Builder("bariatric_surgery", "Bariatric Surgery for Co-Morbid Conditions Related to Morbid Obesity (NCD 100.1)", HAND, VERIFIED)
    section = "B. Nationally Covered Indications"
    b.leaf("bmi", "Body-mass index at or above 35", section, "bmi", ">=", 35, "kg/m2")
    b.leaf("comorbid_diabetes", "Type 2 diabetes mellitus", section, "type_2_diabetes", "==", True)
    b.leaf("comorbid_sleep_apnea", "Obstructive sleep apnea", section, "obstructive_sleep_apnea", "==", True)
    b.leaf("comorbid_hypertension", "Hypertension", section, "hypertension", "==", True)
    # "at least one co-morbidity related to obesity" — an N_OF 1, not an AND
    b.group("comorbidity", "N_OF", "At least one obesity-related co-morbidity", section,
            ["comorbid_diabetes", "comorbid_sleep_apnea", "comorbid_hypertension"], n=1)
    b.leaf("prior_treatment", "Previously unsuccessful with medical treatment for obesity", section,
           "medical_weight_management_failed", "==", True)

    b.leaf("proc_rygb", "Roux-en-Y gastric bypass", section, "procedure", "==", "roux_en_y_gastric_bypass")
    b.leaf("proc_bpd", "Biliopancreatic diversion with duodenal switch", section, "procedure", "==", "biliopancreatic_diversion_duodenal_switch")
    b.leaf("proc_lagb", "Laparoscopic adjustable gastric banding", section, "procedure", "==", "laparoscopic_adjustable_gastric_banding")
    b.leaf("proc_lsg", "Laparoscopic sleeve gastrectomy", section, "procedure", "==", "laparoscopic_sleeve_gastrectomy")
    b.group("covered_procedure", "OR", "A nationally covered bariatric procedure", section,
            ["proc_rygb", "proc_bpd", "proc_lagb", "proc_lsg"])

    b.leaf("obesity_alone", "Performed for treatment of obesity alone", "C. Nationally Non-Covered Indications",
           "indication_is_obesity_alone", "==", True)
    b.group("not_obesity_alone", "NOT", "Not for treatment of obesity alone", "C. Nationally Non-Covered Indications",
            ["obesity_alone"])

    return b.emit(b.group("root", "AND", "Bariatric surgery is covered", section,
                          ["bmi", "comorbidity", "prior_treatment", "covered_procedure", "not_obesity_alone"]))


# ---------------------------------------------------------------------------
# 50.3 Cochlear Implantation
# ---------------------------------------------------------------------------

def cochlear() -> Dict[str, Any]:
    b = Builder("cochlear_implant", "Cochlear Implantation (NCD 50.3)", HAND, VERIFIED)
    section = "B. Nationally Covered Indications"
    b.leaf("diagnosis", "Bilateral moderate-to-profound sensorineural hearing impairment", section,
           "bilateral_sensorineural_hearing_loss", "==", True)
    # "limited benefit from amplification" is defined in the policy as <= 60% on
    # open-set sentence recognition in the best-aided condition
    b.leaf("sentence_score", "Open-set sentence recognition at or below 60% in the best-aided condition", section,
           "best_aided_sentence_recognition_percent", "<=", 60, "%")
    b.group("limited_benefit", "AND", "Hearing loss with limited benefit from amplification", section,
            ["diagnosis", "sentence_score"])

    b.leaf("cognitive", "Cognitive ability to use auditory clues and willingness to undergo rehabilitation", section,
           "cognitive_ability_and_willingness", "==", True)

    b.leaf("middle_ear_infection", "Middle ear infection present", section, "middle_ear_infection", "==", True)
    b.group("free_of_infection", "NOT", "Free from middle ear infection", section, ["middle_ear_infection"])
    b.leaf("cochlear_lumen", "Accessible cochlear lumen structurally suited to implantation", section,
           "cochlear_lumen_accessible", "==", True)
    b.leaf("nerve_lesion", "Lesion in the auditory nerve or central auditory pathways", section,
           "auditory_nerve_lesion", "==", True)
    b.group("free_of_lesion", "NOT", "Free from auditory nerve and CNS lesions", section, ["nerve_lesion"])
    b.group("anatomy", "AND", "Anatomy suitable for implantation", section,
            ["free_of_infection", "cochlear_lumen", "free_of_lesion"])

    b.leaf("surgical_contraindication", "Contraindication to surgery", section, "surgical_contraindication", "==", True)
    b.group("no_contraindication", "NOT", "No contraindications to surgery", section, ["surgical_contraindication"])
    b.leaf("fda_labeling", "Device used per FDA-approved labeling", section, "fda_labeling_compliant", "==", True)

    return b.emit(b.group("root", "AND", "Cochlear implantation is covered", section,
                          ["limited_benefit", "cognitive", "anatomy", "no_contraindication", "fda_labeling"]))


# ---------------------------------------------------------------------------
# 20.32 TAVR
# ---------------------------------------------------------------------------

def tavr() -> Dict[str, Any]:
    b = Builder("tavr", "Transcatheter Aortic Valve Replacement (NCD 20.32)", HAND, VERIFIED)
    section = "A. Covered Indications"
    b.leaf("symptomatic_as", "Symptomatic aortic valve stenosis", section, "symptomatic_aortic_stenosis", "==", True)
    b.leaf("fda_system", "Complete valve and implantation system with FDA premarket approval", section,
           "fda_approved_system", "==", True)

    heart = "A.2 Heart team"
    b.leaf("surgeon_exam", "Cardiac surgeon examined the patient face-to-face", heart, "cardiac_surgeon_examined", "==", True)
    b.leaf("cardiologist_exam", "Interventional cardiologist examined the patient face-to-face", heart,
           "interventional_cardiologist_examined", "==", True)
    b.leaf("rationale", "Clinical rationale documented and shared with the heart team", heart,
           "heart_team_rationale_documented", "==", True)
    b.leaf("joint_participation", "Surgeon and cardiologist jointly participate intra-operatively", heart,
           "joint_intraoperative_participation", "==", True)
    b.group("heart_team", "AND", "Patient under the care of a qualifying heart team", heart,
            ["surgeon_exam", "cardiologist_exam", "rationale", "joint_participation"])

    infra = "A.3 Hospital infrastructure"
    b.leaf("valve_surgery_program", "On-site heart valve surgery program", infra, "onsite_valve_surgery_program", "==", True)
    b.leaf("cardiology_program", "On-site interventional cardiology program", infra, "onsite_interventional_cardiology_program", "==", True)
    b.leaf("icu", "Post-procedure ICU with experienced personnel", infra, "post_procedure_icu", "==", True)

    volume = "A.3 Volume requirements"
    b.leaf("existing_program", "Hospital has an established TAVR program meeting the experienced-program volumes", volume,
           "established_tavr_program", "==", True)
    b.leaf("open_heart_volume", "At least 50 open heart surgeries in the previous year", volume,
           "open_heart_surgeries_prior_year", ">=", 50, "cases")
    b.leaf("aortic_valve_volume", "At least 20 aortic valve procedures in the previous 2 years", volume,
           "aortic_valve_procedures_prior_2_years", ">=", 20, "cases")
    b.leaf("surgeons", "At least 2 physicians with cardiac surgery privileges", volume,
           "cardiac_surgeons_on_staff", ">=", 2, "physicians")
    b.leaf("interventionalists", "At least 1 physician with interventional cardiology privileges", volume,
           "interventional_cardiologists_on_staff", ">=", 1, "physicians")
    b.leaf("pci_volume", "At least 300 PCIs per year", volume, "pci_per_year", ">=", 300, "cases")
    b.group("new_program_volumes", "AND", "Volumes qualifying a hospital without prior TAVR experience", volume,
            ["open_heart_volume", "aortic_valve_volume", "surgeons", "interventionalists", "pci_volume"])
    # The policy gives two alternative qualification sets; this is the OR the
    # word "or" in the source actually means, not an extra AND condition.
    b.group("volume_requirements", "OR", "Hospital meets one of the two volume qualification sets", volume,
            ["existing_program", "new_program_volumes"])
    b.group("infrastructure", "AND", "Hospital infrastructure requirements", infra,
            ["valve_surgery_program", "cardiology_program", "icu", "volume_requirements"])

    return b.emit(b.group("root", "AND", "TAVR is covered", section,
                          ["symptomatic_as", "fda_system", "heart_team", "infrastructure"]))


# ---------------------------------------------------------------------------
# 240.2 Home Use of Oxygen
# ---------------------------------------------------------------------------

def home_oxygen() -> Dict[str, Any]:
    b = Builder("home_oxygen", "Home Use of Oxygen (NCD 240.2)", HAND, VERIFIED)
    group_i = "B. Group I"
    b.leaf("po2_rest", "Arterial PO2 at or below 55 mm Hg at rest on room air", group_i,
           "arterial_po2_rest_mmhg", "<=", 55, "mm Hg")
    b.leaf("sat_rest", "Arterial oxygen saturation at or below 88% at rest on room air", group_i,
           "oxygen_saturation_rest_percent", "<=", 88, "%")
    b.group("qualifying_at_rest", "OR", "Qualifying hypoxemia at rest", group_i, ["po2_rest", "sat_rest"])

    b.leaf("po2_exercise", "Arterial PO2 at or below 55 mm Hg during exercise", group_i,
           "arterial_po2_exercise_mmhg", "<=", 55, "mm Hg")
    b.leaf("sat_exercise", "Arterial oxygen saturation at or below 88% during exercise", group_i,
           "oxygen_saturation_exercise_percent", "<=", 88, "%")
    b.group("exercise_desaturation", "OR", "Desaturation during exercise", group_i, ["po2_exercise", "sat_exercise"])
    # The qualifier "for a patient who demonstrates ... at rest" attaches to the
    # exercise limb only. Hanging it off the shared parent would be the classic
    # scope error this project is about.
    b.leaf("sat_rest_adequate", "Resting saturation at or above 89% during the day", group_i,
           "oxygen_saturation_rest_percent", ">=", 89, "%")
    b.group("qualifying_on_exercise", "AND", "Exercise desaturation in a patient adequate at rest", group_i,
            ["exercise_desaturation", "sat_rest_adequate"])
    b.group("group_i", "OR", "Group I hypoxemia", group_i, ["qualifying_at_rest", "qualifying_on_exercise"])

    group_ii = "B. Group II"
    b.leaf("po2_lower", "Arterial PO2 at or above 56 mm Hg", group_ii, "arterial_po2_rest_mmhg", ">=", 56, "mm Hg")
    b.leaf("po2_upper", "Arterial PO2 at or below 59 mm Hg", group_ii, "arterial_po2_rest_mmhg", "<=", 59, "mm Hg")
    b.group("po2_band", "AND", "Arterial PO2 of 56-59 mm Hg", group_ii, ["po2_lower", "po2_upper"])
    b.leaf("sat_89", "Arterial oxygen saturation of 89%", group_ii, "oxygen_saturation_rest_percent", "==", 89, "%")
    b.group("borderline_hypoxemia", "OR", "Borderline hypoxemia", group_ii, ["po2_band", "sat_89"])

    b.leaf("dependent_edema", "Dependent edema suggesting congestive heart failure", group_ii,
           "dependent_edema", "==", True)
    b.leaf("pulmonary_hypertension", "Pulmonary hypertension or cor pulmonale", group_ii,
           "pulmonary_hypertension_or_cor_pulmonale", "==", True)
    # The source says "greater than 56%". The predicate grammar has no strict >,
    # so this is encoded as >= 56.1 (hematocrit is reported to one decimal).
    # Recorded in data/policies/CORRECTIONS.md.
    b.leaf("erythrocythemia", "Erythrocythemia with haematocrit greater than 56%", group_ii,
           "hematocrit_percent", ">=", 56.1, "%")
    b.group("secondary_finding", "N_OF", "At least one qualifying secondary finding", group_ii,
            ["dependent_edema", "pulmonary_hypertension", "erythrocythemia"], n=1)
    b.group("group_ii", "AND", "Group II hypoxemia with a secondary finding", group_ii,
            ["borderline_hypoxemia", "secondary_finding"])

    b.group("hypoxemia", "OR", "Qualifying hypoxemia", "B. Nationally Covered Indications", ["group_i", "group_ii"])
    b.leaf("time_of_need", "Qualifying blood gas or oximetry performed at the time of need", "B. Nationally Covered Indications",
           "test_at_time_of_need", "==", True)

    non_covered = "C. Nationally Non-Covered Indications"
    b.leaf("angina", "Angina pectoris in the absence of hypoxemia", non_covered, "angina_without_hypoxemia", "==", True)
    b.leaf("breathlessness", "Breathlessness without cor pulmonale or evidence of hypoxemia", non_covered,
           "breathlessness_without_cor_pulmonale", "==", True)
    b.leaf("pvd", "Severe peripheral vascular disease with desaturation in an extremity", non_covered,
           "severe_peripheral_vascular_disease", "==", True)
    b.leaf("terminal", "Terminal illness not affecting the ability to breathe", non_covered,
           "terminal_illness_not_affecting_breathing", "==", True)
    b.group("any_non_covered", "OR", "Any nationally non-covered indication", non_covered,
            ["angina", "breathlessness", "pvd", "terminal"])
    b.group("not_non_covered", "NOT", "No nationally non-covered indication applies", non_covered, ["any_non_covered"])

    return b.emit(b.group("root", "AND", "Home oxygen is covered", "B. Nationally Covered Indications",
                          ["hypoxemia", "time_of_need", "not_non_covered"]))


# ---------------------------------------------------------------------------
# 280.3 Mobility Assistive Equipment
# ---------------------------------------------------------------------------

def power_wheelchair() -> Dict[str, Any]:
    b = Builder("power_wheelchair", "Mobility Assistive Equipment — power wheelchair (NCD 280.3)", HAND, VERIFIED)
    section = "B. Clinical Criteria for MAE Coverage"
    b.leaf("prevents_mradl", "Mobility limitation prevents accomplishing MRADLs entirely", section,
           "prevents_mradls", "==", True)
    b.leaf("heightened_risk", "Attempting MRADLs places the beneficiary at heightened risk", section,
           "heightened_risk_attempting_mradls", "==", True)
    b.leaf("not_timely", "Cannot complete MRADLs within a reasonable time frame", section,
           "cannot_complete_mradls_timely", "==", True)
    b.group("mobility_limitation", "OR", "Question 1: a qualifying mobility limitation", section,
            ["prevents_mradl", "heightened_risk", "not_timely"])

    b.leaf("no_other_limits", "No other condition limits participation in MRADLs", section,
           "other_limiting_conditions", "==", False)
    b.leaf("limits_compensated", "Other limiting conditions can be ameliorated or compensated", section,
           "other_limitations_compensated", "==", True)
    b.group("other_conditions", "OR", "Questions 2-3: other limitations absent or compensable", section,
            ["no_other_limits", "limits_compensated"])

    b.leaf("safe_operation", "Beneficiary or caregiver can operate the equipment safely", section,
           "safe_operation_demonstrated", "==", True)
    b.leaf("cane_walker_insufficient", "A cane or walker does not resolve the mobility deficit", section,
           "cane_or_walker_sufficient", "==", False)
    b.leaf("home_supports", "Home environment supports use of a wheelchair", section,
           "home_environment_supports_wheelchair", "==", True)

    manual = "B. Question 7: manual wheelchair"
    b.leaf("upper_extremity", "Insufficient upper extremity function to self-propel a manual wheelchair", manual,
           "can_self_propel_manual_wheelchair", "==", False)
    # The policy's NOTE: an available, willing and able caregiver makes a manual
    # wheelchair appropriate even when the beneficiary cannot self-propel.
    b.leaf("no_caregiver", "No caregiver available, willing and able to propel a manual wheelchair", manual,
           "caregiver_available_for_manual_wheelchair", "==", False)
    b.group("manual_insufficient", "AND", "A manual wheelchair is not sufficient", manual,
            ["upper_extremity", "no_caregiver"])

    pov = "B. Question 8: POV/scooter"
    b.leaf("postural_stability", "Insufficient strength or postural stability to operate a POV", pov,
           "can_operate_pov", "==", False)
    b.leaf("home_pov", "Home cannot accommodate a POV", pov, "home_accommodates_pov", "==", False)
    b.group("pov_insufficient", "OR", "A POV/scooter is not sufficient", pov, ["postural_stability", "home_pov"])

    b.leaf("power_features", "Power wheelchair features are needed to participate in MRADLs", "B. Question 9: power wheelchair",
           "power_features_needed", "==", True)

    return b.emit(b.group("root", "AND", "A power wheelchair is covered", section,
                          ["mobility_limitation", "other_conditions", "safe_operation", "cane_walker_insufficient",
                           "home_supports", "manual_insufficient", "pov_insufficient", "power_features"]))


# ---------------------------------------------------------------------------
# 220.6.17 FDG PET for Oncologic Conditions
# ---------------------------------------------------------------------------

def pet_oncology() -> Dict[str, Any]:
    b = Builder("pet_oncology", "FDG PET for Oncologic Conditions (NCD 220.6.17)", HAND, VERIFIED)
    framework = "2. Initial Anti-Tumor Treatment Strategy"
    b.leaf("biopsy_proven", "Cancer is biopsy proven", framework, "biopsy_proven_cancer", "==", True)
    b.leaf("strongly_suspected", "Cancer strongly suspected on other diagnostic testing", framework,
           "strongly_suspected_cancer", "==", True)
    b.group("cancer_status", "OR", "Biopsy-proven or strongly suspected cancer", framework,
            ["biopsy_proven", "strongly_suspected"])

    b.leaf("candidacy", "Needed to determine candidacy for an invasive procedure", framework,
           "determines_procedure_candidacy", "==", True)
    b.leaf("anatomic_location", "Needed to determine the optimal anatomic location for an invasive procedure", framework,
           "determines_anatomic_location", "==", True)
    b.leaf("tumor_extent", "Needed to determine the anatomic extent of tumour", framework,
           "determines_tumor_extent", "==", True)
    b.group("clinical_purpose", "N_OF", "At least one qualifying clinical purpose", framework,
            ["candidacy", "anatomic_location", "tumor_extent"], n=1)

    initial = "B.1/C.1 Initial anti-tumor treatment strategy"
    b.leaf("is_initial", "Study is for the initial anti-tumour treatment strategy", initial,
           "treatment_strategy", "==", "initial")
    b.leaf("prostate", "Adenocarcinoma of the prostate", initial, "tumor_type", "==", "prostate_adenocarcinoma")
    b.leaf("breast_type", "Breast cancer", initial, "tumor_type", "==", "breast")
    b.leaf("breast_nodes", "Study is initial staging of axillary nodes", initial, "study_purpose", "==", "axillary_node_staging")
    b.group("breast_excluded", "AND", "Breast cancer, axillary node staging", initial, ["breast_type", "breast_nodes"])
    b.leaf("melanoma_type", "Melanoma", initial, "tumor_type", "==", "melanoma")
    b.leaf("regional_nodes", "Study is evaluation of regional lymph nodes", initial, "study_purpose", "==", "regional_node_evaluation")
    b.group("melanoma_excluded", "AND", "Melanoma, regional lymph node evaluation", initial, ["melanoma_type", "regional_nodes"])
    b.group("excluded_initial", "OR", "A nationally non-covered initial indication", initial,
            ["prostate", "breast_excluded", "melanoma_excluded"])
    b.group("not_excluded_initial", "NOT", "Not a nationally non-covered initial indication", initial, ["excluded_initial"])
    b.group("initial_arm", "AND", "Covered as an initial treatment strategy study", initial,
            ["is_initial", "not_excluded_initial"])

    subsequent = "B.2 Subsequent anti-tumor treatment strategy"
    b.leaf("is_subsequent", "Study is for a subsequent anti-tumour treatment strategy", subsequent,
           "treatment_strategy", "==", "subsequent")
    # Three scans are nationally covered; a fourth falls to MAC discretion, so
    # the national criteria are satisfied only up to three.
    b.leaf("prior_scans", "At most 2 prior subsequent-strategy FDG PET scans", subsequent,
           "prior_subsequent_pet_scans", "<=", 2, "scans")
    b.group("subsequent_arm", "AND", "Covered as a subsequent treatment strategy study", subsequent,
            ["is_subsequent", "prior_scans"])

    b.group("coverage_arm", "OR", "Covered under the initial or subsequent strategy", framework,
            ["initial_arm", "subsequent_arm"])

    return b.emit(b.group("root", "AND", "FDG PET is covered", framework,
                          ["cancer_status", "clinical_purpose", "coverage_arm"]))


# ---------------------------------------------------------------------------
# L37848 Lumbar Spinal Fusion  (paraphrase — see module docstring)
# ---------------------------------------------------------------------------

def lumbar_fusion() -> Dict[str, Any]:
    b = Builder("lumbar_fusion", "Lumbar Spinal Fusion (LCD L37848, paraphrased)", PARAPHRASE, UNVERIFIED)
    indication = "Covered indications (paraphrased)"
    b.leaf("spondylolisthesis", "Documented spondylolisthesis", indication, "diagnosis", "includes", ["spondylolisthesis"])
    b.leaf("neuro_symptoms", "Neurogenic claudication or radiculopathy documented", indication,
           "neurogenic_claudication_or_radiculopathy", "==", True)
    b.group("spondylolisthesis_arm", "AND", "Spondylolisthesis with neurogenic symptoms", indication,
            ["spondylolisthesis", "neuro_symptoms"])

    b.leaf("ddd", "Documented degenerative disc disease", indication, "diagnosis", "includes", ["degenerative_disc_disease"])
    b.leaf("instability", "Segmental instability demonstrated on imaging", indication, "segmental_instability", "==", True)
    b.leaf("imaging_correlates", "Imaging findings correlate with the documented symptoms", indication,
           "imaging_correlates_symptoms", "==", True)
    b.group("ddd_arm", "AND", "Degenerative disc disease with instability", indication,
            ["ddd", "instability", "imaging_correlates"])
    b.group("indication", "OR", "A covered surgical indication", indication, ["spondylolisthesis_arm", "ddd_arm"])

    conservative = "Conservative care requirement (paraphrased)"
    b.leaf("conservative_months", "At least 6 months of conservative therapy", conservative,
           "conservative_therapy_months", ">=", 6, "months")
    b.leaf("conservative_contraindicated", "Conservative therapy contraindicated or not feasible", conservative,
           "conservative_therapy_contraindicated", "==", True)
    b.group("conservative_care", "OR", "Conservative care completed or contraindicated", conservative,
            ["conservative_months", "conservative_contraindicated"])
    b.leaf("symptom_duration", "Symptoms present for at least 6 months", conservative,
           "symptom_duration_months", ">=", 6, "months")

    exclusions = "Exclusions (paraphrased)"
    b.leaf("active_infection", "Active spinal infection", exclusions, "active_spinal_infection", "==", True)
    b.leaf("malignancy", "Active malignancy at the operative level", exclusions, "active_malignancy_at_level", "==", True)
    b.group("any_exclusion", "OR", "Any documented exclusion", exclusions, ["active_infection", "malignancy"])
    b.group("no_exclusion", "NOT", "No documented exclusion", exclusions, ["any_exclusion"])

    return b.emit(b.group("root", "AND", "Lumbar spinal fusion meets criteria", indication,
                          ["indication", "conservative_care", "symptom_duration", "no_exclusion"]))


# ---------------------------------------------------------------------------
# L33822 Glucose Monitors — CGM  (paraphrase — see module docstring)
# ---------------------------------------------------------------------------

def cgm() -> Dict[str, Any]:
    b = Builder("cgm", "Continuous Glucose Monitor (LCD L33822, paraphrased)", PARAPHRASE, UNVERIFIED)
    section = "Coverage criteria (paraphrased)"
    b.leaf("diabetes", "Diagnosis of diabetes mellitus", section, "diabetes_diagnosis", "==", True)
    b.leaf("insulin_treated", "Treated with insulin", section, "insulin_treated", "==", True)
    b.leaf("problematic_hypoglycaemia", "History of problematic hypoglycaemia", section,
           "problematic_hypoglycemia_history", "==", True)
    b.group("treatment_basis", "OR", "Insulin treated or problematic hypoglycaemia", section,
            ["insulin_treated", "problematic_hypoglycaemia"])

    b.leaf("visit_recency", "Visit with the treating practitioner within the last 6 months", section,
           "months_since_practitioner_visit", "<=", 6, "months")
    b.leaf("training", "Trained, or scheduled for training, on the device", section, "device_training_completed", "==", True)
    b.leaf("existing_cgm", "An active CGM is already supplied", section, "active_cgm_already_supplied", "==", True)
    b.group("no_duplicate", "NOT", "No duplicate device already supplied", section, ["existing_cgm"])

    return b.emit(b.group("root", "AND", "A continuous glucose monitor meets criteria", section,
                          ["diabetes", "treatment_basis", "visit_recency", "training", "no_duplicate"]))


BUILDERS = [bariatric, cochlear, tavr, home_oxygen, power_wheelchair, pet_oncology, lumbar_fusion, cgm]


def main() -> int:
    sys.path.insert(0, ROOT)
    from pipeline.validate import validate_policy  # noqa: E402

    os.makedirs(OUT_DIR, exist_ok=True)
    failed = False
    for build in BUILDERS:
        policy = build()
        errors = validate_policy(policy)
        if errors:
            failed = True
            print("FAIL {0}".format(policy["policy_id"]))
            for error in errors:
                print("  - {0}".format(error))
            continue
        path = os.path.join(OUT_DIR, "{0}.json".format(policy["policy_id"]))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(policy, handle, indent=1)
            handle.write("\n")
        leaves = sum(1 for node in policy["nodes"].values() if node["type"] == "LEAF")
        print("ok   {0:18s} {1:2d} nodes ({2} leaves)  {3}".format(
            policy["policy_id"], len(policy["nodes"]), leaves, policy["verification"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
