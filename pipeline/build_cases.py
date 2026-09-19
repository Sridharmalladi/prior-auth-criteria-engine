"""Build data/cases/*.json — 20 synthetic clinical notes with gold labels.

The notes are written for this project. They are not real patient records, not
de-identified real records, and not drawn from MIMIC or any other credentialed
corpus; that is why a public repo can carry them.

Two rules make the gold labels worth something:

1. **Spans are computed, never typed.** Each fact declares the evidence
   substring; this script finds it in the note and writes the offsets. A
   substring that is missing, or that appears more than once, is a build error.
   ``extract_facts.py`` applies the same check to LLM output.
2. **``gold_blocking_node`` is assigned by clinical judgement, not read back out
   of the evaluator.** Where the evaluator's ranking disagrees with the human
   label, that is recorded as an attribution failure in the eval — it is not
   quietly relabelled. Some of these disagreements are real and appear in
   ``data/eval/failures.json``.

Run: python3 pipeline/build_cases.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "data", "cases")
POLICY_DIR = os.path.join(ROOT, "data", "policies")

CASES: List[Dict[str, Any]] = []


def case(case_id: str, policy_id: str, title: str, note: str, facts: List[Dict[str, Any]],
         gold_decision: str, gold_blocking_node: Optional[str], note_on_gold: str = "") -> None:
    CASES.append({
        "case_id": case_id,
        "policy_id": policy_id,
        "title": title,
        "note_text": note.strip(),
        "raw_facts": facts,
        "gold_decision": gold_decision,
        "gold_blocking_node": gold_blocking_node,
        "note_on_gold": note_on_gold,
    })


def f(key: str, value: Any, evidence: str, unit: Optional[str] = None, confidence: float = 0.95) -> Dict[str, Any]:
    return {"key": key, "value": value, "evidence": evidence, "unit": unit, "confidence": confidence}


# ===========================================================================
# lumbar fusion
# ===========================================================================

case(
    "lumbar_fusion_01", "lumbar_fusion", "68F, L4-5 spondylolisthesis, fusion requested",
    """
SPINE SURGERY CONSULTATION — SYNTHETIC TEACHING CASE

68-year-old woman referred for evaluation of chronic low back and bilateral leg pain.

HPI: Symptoms began approximately 18 months ago and have progressed. She describes
neurogenic claudication with standing tolerance under five minutes, relieved by sitting
and by leaning on a shopping trolley. No bowel or bladder dysfunction.

CONSERVATIVE CARE: Completed 9 months of supervised physical therapy across two courses,
NSAIDs, and two epidural steroid injections without durable relief.

IMAGING: Upright lateral radiographs demonstrate grade I degenerative spondylolisthesis at
L4-5 with 6 mm of anterolisthesis. MRI confirms severe central canal stenosis at the same
level, correlating with the reported claudication.

PMH: Hypertension, hypothyroidism. No history of spinal infection. No malignancy.
Afebrile, CRP and ESR within normal limits.

ASSESSMENT: Grade I degenerative spondylolisthesis at L4-5 with neurogenic claudication
refractory to conservative management. Recommend decompression and instrumented fusion.
""",
    [
        f("diagnosis", ["spondylolisthesis"], "Grade I degenerative spondylolisthesis at\nL4-5 with neurogenic claudication"),
        f("neurogenic_claudication_or_radiculopathy", True, "neurogenic claudication with standing tolerance under five minutes"),
        f("conservative_therapy_months", 9, "Completed 9 months of supervised physical therapy", "months"),
        f("symptom_duration_months", 18, "Symptoms began approximately 18 months ago", "months"),
        f("active_spinal_infection", False, "No history of spinal infection"),
        f("active_malignancy_at_level", False, "No malignancy."),
    ],
    "APPROVE", None,
)

case(
    "lumbar_fusion_02", "lumbar_fusion", "54M, spondylolisthesis, 3 months of therapy",
    """
SPINE SURGERY CONSULTATION — SYNTHETIC TEACHING CASE

54-year-old man, warehouse supervisor, with low back pain radiating into the right leg.

HPI: Pain for the past 8 months, worse with extension and prolonged standing. Right L5
radicular pattern with intermittent paraesthesia over the dorsum of the foot. Strength is
5/5 throughout. No red flag symptoms.

CONSERVATIVE CARE: Referred to physical therapy 3 months ago and has attended consistently;
he reports partial improvement in the first six weeks with a plateau since. Taking
meloxicam daily. No injections attempted yet; he is willing to proceed with them.

IMAGING: Flexion-extension radiographs show grade I isthmic spondylolisthesis at L5-S1 with
3 mm of translation on flexion. MRI shows foraminal narrowing on the right at L5-S1
consistent with his symptoms.

PMH: Type 2 diabetes, well controlled. No infection, no malignancy, afebrile.

ASSESSMENT: Symptomatic isthmic spondylolisthesis. Surgical candidate, but conservative
management is incomplete. Discussed continuing therapy and proceeding to injection.
""",
    [
        f("diagnosis", ["spondylolisthesis"], "grade I isthmic spondylolisthesis at L5-S1"),
        f("neurogenic_claudication_or_radiculopathy", True, "Right L5\nradicular pattern with intermittent paraesthesia"),
        f("conservative_therapy_months", 3, "Referred to physical therapy 3 months ago", "months"),
        f("conservative_therapy_contraindicated", False, "he is willing to proceed with them"),
        f("symptom_duration_months", 8, "Pain for the past 8 months", "months"),
        f("active_spinal_infection", False, "No infection, no malignancy, afebrile."),
        f("active_malignancy_at_level", False, "no malignancy, afebrile."),
    ],
    "DENY", "conservative_months",
    "Three months documented against a six-month requirement; everything else is satisfied.",
)

case(
    "lumbar_fusion_03", "lumbar_fusion", "61M, three independent failures",
    """
SPINE SURGERY CONSULTATION — SYNTHETIC TEACHING CASE

61-year-old man with mechanical low back pain, referred for consideration of fusion.

HPI: Axial low back pain for 7 months without radicular features. No neurogenic
claudication. Pain is reproduced by lumbar extension and by palpation of the paraspinal
musculature.

CONSERVATIVE CARE: Two months of home exercises supplied by his primary care physician;
no supervised physical therapy course has been completed. No contraindication to therapy.

IMAGING: MRI reports lumbar strain with mild multilevel facet arthropathy. No
spondylolisthesis and no degenerative disc disease reported at any level. No
flexion-extension instability on dynamic films. Imaging findings do correlate with the
distribution of his pain.

INTERVAL HISTORY: Admitted six weeks ago with an epidural abscess at L3-4 managed with
IV antibiotics; repeat MRI shows persistent enhancement and the infectious disease team
considers the spinal infection active and ongoing.

ASSESSMENT: Axial back pain without a structural surgical indication, incomplete
conservative care, and an active spinal infection.
""",
    [
        f("diagnosis", ["lumbar_strain"], "MRI reports lumbar strain with mild multilevel facet arthropathy"),
        f("neurogenic_claudication_or_radiculopathy", False, "without radicular features. No neurogenic\nclaudication."),
        f("segmental_instability", False, "No\nflexion-extension instability on dynamic films"),
        f("imaging_correlates_symptoms", True, "Imaging findings do correlate with the\ndistribution of his pain"),
        f("conservative_therapy_months", 2, "Two months of home exercises", "months"),
        f("conservative_therapy_contraindicated", False, "No contraindication to therapy."),
        f("symptom_duration_months", 7, "Axial low back pain for 7 months", "months"),
        f("active_spinal_infection", True, "considers the spinal infection active and ongoing"),
        f("active_malignancy_at_level", False, "mild multilevel facet arthropathy"),
    ],
    "DENY", "active_infection",
    "Three independent failures: no covered indication, two months of conservative care, "
    "and an active spinal infection. A reviewer would cite the active infection first as an "
    "absolute contraindication.",
)

# ===========================================================================
# home oxygen
# ===========================================================================

case(
    "home_oxygen_01", "home_oxygen", "74F, COPD, Group II with cor pulmonale",
    """
PULMONARY CLINIC NOTE — SYNTHETIC TEACHING CASE

74-year-old woman with GOLD stage III COPD, seen for evaluation for home oxygen.

HPI: Progressive exertional dyspnoea. Ex-smoker, quit 6 years ago. No angina. She is
not on hospice and has no terminal diagnosis.

TESTING: Room-air arterial blood gas drawn in clinic today during a period of clinical
stability shows PO2 of 57 mm Hg. Resting pulse oximetry on room air 90%. Testing was
performed at the time of need, with the prescription written the same day.

EXAMINATION: Bilateral pitting ankle oedema to mid-shin. JVP elevated. Echocardiogram last
month estimated pulmonary artery systolic pressure of 48 mm Hg, consistent with pulmonary
hypertension and cor pulmonale. Haematocrit 44%.

VASCULAR: No severe peripheral vascular disease; pedal pulses palpable bilaterally.

ASSESSMENT: COPD with borderline hypoxaemia and cor pulmonale. Home oxygen prescribed at
2 L/min continuous.
""",
    [
        f("arterial_po2_rest_mmhg", 57, "PO2 of 57 mm Hg", "mm Hg"),
        f("oxygen_saturation_rest_percent", 90, "Resting pulse oximetry on room air 90%", "%"),
        f("test_at_time_of_need", True, "Testing was\nperformed at the time of need"),
        f("dependent_edema", True, "Bilateral pitting ankle oedema to mid-shin"),
        f("pulmonary_hypertension_or_cor_pulmonale", True, "consistent with pulmonary\nhypertension and cor pulmonale"),
        f("hematocrit_percent", 44, "Haematocrit 44%", "%"),
        f("angina_without_hypoxemia", False, "No angina."),
        f("breathlessness_without_cor_pulmonale", False, "consistent with pulmonary\nhypertension and cor pulmonale."),
        f("severe_peripheral_vascular_disease", False, "No severe peripheral vascular disease"),
        f("terminal_illness_not_affecting_breathing", False, "has no terminal diagnosis"),
    ],
    "APPROVE", None,
)

case(
    "home_oxygen_02", "home_oxygen", "69M, breathlessness without qualifying hypoxaemia",
    """
PULMONARY CLINIC NOTE — SYNTHETIC TEACHING CASE

69-year-old man requesting home oxygen for breathlessness on exertion.

HPI: Reports dyspnoea climbing one flight of stairs, present for about a year. Deconditioned
since retirement. No chest pain and no angina. Not terminally ill.

TESTING: Room-air arterial blood gas today shows PO2 of 68 mm Hg. Resting oximetry on room
air 94%. Six-minute walk performed the same visit with continuous oximetry: lowest recorded
saturation 91% at the end of the walk, with no desaturation below that. Studies were
obtained at the time of need.

EXAMINATION: No peripheral oedema. Echocardiogram six weeks ago showed normal right
ventricular size and function with no pulmonary hypertension. Haematocrit 43%. Pedal pulses
intact with no severe peripheral vascular disease.

ASSESSMENT: Exertional breathlessness without cor pulmonale and without hypoxaemia meeting
the coverage thresholds. Recommend pulmonary rehabilitation.
""",
    [
        f("arterial_po2_rest_mmhg", 68, "PO2 of 68 mm Hg", "mm Hg"),
        f("oxygen_saturation_rest_percent", 94, "Resting oximetry on room\nair 94%", "%"),
        f("oxygen_saturation_exercise_percent", 91, "lowest recorded\nsaturation 91% at the end of the walk", "%"),
        f("test_at_time_of_need", True, "Studies were\nobtained at the time of need"),
        f("dependent_edema", False, "No peripheral oedema."),
        f("pulmonary_hypertension_or_cor_pulmonale", False, "no pulmonary hypertension"),
        f("hematocrit_percent", 43, "Haematocrit 43%", "%"),
        f("angina_without_hypoxemia", False, "No chest pain and no angina."),
        f("breathlessness_without_cor_pulmonale", True, "Exertional breathlessness without cor pulmonale"),
        f("severe_peripheral_vascular_disease", False, "no severe peripheral vascular disease"),
        f("terminal_illness_not_affecting_breathing", False, "Not terminally ill."),
    ],
    "DENY", "sat_rest",
    "No limb of the hypoxaemia criteria is met; the reviewer would cite the resting "
    "saturation of 94% against the 88% threshold.",
)

case(
    "home_oxygen_03", "home_oxygen", "77F, oximetry undated, testing conditions not documented",
    """
DISCHARGE SUMMARY — SYNTHETIC TEACHING CASE

77-year-old woman discharged after an admission for a COPD exacerbation.

HOSPITAL COURSE: Treated with systemic corticosteroids, nebulised bronchodilators and a
five-day course of antibiotics. Weaned from 4 L/min to 2 L/min by day three.

TESTING: A pulse oximetry reading of 87% is recorded in the chart. The entry does not state
whether the patient was on room air or supplemental oxygen at the time, and the date and
time of the reading are not recorded. No arterial blood gas was obtained during this
admission.

EXAMINATION AT DISCHARGE: No peripheral oedema. No documented echocardiogram this
admission. Haematocrit 41%. No angina. No severe peripheral vascular disease. Not
terminally ill.

PLAN: Discharge home with the oxygen concentrator she arrived with, pending outpatient
retesting on room air at the time of need.
""",
    [
        f("oxygen_saturation_rest_percent", 87, "A pulse oximetry reading of 87% is recorded in the chart", "%"),
        f("dependent_edema", False, "No peripheral oedema."),
        f("hematocrit_percent", 41, "Haematocrit 41%", "%"),
        f("angina_without_hypoxemia", False, "No angina."),
        f("severe_peripheral_vascular_disease", False, "No severe peripheral vascular disease."),
        f("terminal_illness_not_affecting_breathing", False, "Not\nterminally ill."),
    ],
    "INDETERMINATE", "time_of_need",
    "The saturation would qualify, but the note never establishes that the test was taken at "
    "the time of need on room air, so the record cannot support a decision either way.",
)

# ===========================================================================
# bariatric surgery
# ===========================================================================

case(
    "bariatric_01", "bariatric_surgery", "52F, BMI 41, type 2 diabetes, RYGB requested",
    """
BARIATRIC SURGERY EVALUATION — SYNTHETIC TEACHING CASE

52-year-old woman presenting for surgical management of obesity with co-morbid disease.

MEASUREMENTS: Weight 112 kg, height 165 cm, body mass index 41.1 kg/m2, stable over the
past year.

CO-MORBIDITIES: Type 2 diabetes mellitus diagnosed 7 years ago, currently on metformin and
semaglutide with HbA1c 7.9%. Obstructive sleep apnoea on CPAP. Hypertension on two agents.

WEIGHT MANAGEMENT HISTORY: Completed a 12-month medically supervised weight management
programme with dietitian review, documented food diaries and two pharmacotherapy trials.
Maximum recorded loss 6 kg, since regained. Medical management of obesity has therefore been
unsuccessful.

INDICATION: Surgery is being offered for treatment of her co-morbid conditions related to
obesity, not for weight loss alone.

PLAN: Laparoscopic Roux-en-Y gastric bypass. Anaesthetic review completed, no
contraindication identified.
""",
    [
        f("bmi", 41.1, "body mass index 41.1 kg/m2", "kg/m2"),
        f("type_2_diabetes", True, "Type 2 diabetes mellitus diagnosed 7 years ago"),
        f("obstructive_sleep_apnea", True, "Obstructive sleep apnoea on CPAP"),
        f("hypertension", True, "Hypertension on two agents"),
        f("medical_weight_management_failed", True, "Medical management of obesity has therefore been\nunsuccessful"),
        f("procedure", "roux_en_y_gastric_bypass", "Laparoscopic Roux-en-Y gastric bypass"),
        f("indication_is_obesity_alone", False, "not for weight loss alone"),
    ],
    "APPROVE", None,
)

case(
    "bariatric_02", "bariatric_surgery", "44M, BMI 32.4, below threshold",
    """
BARIATRIC SURGERY EVALUATION — SYNTHETIC TEACHING CASE

44-year-old man self-referred for sleeve gastrectomy.

MEASUREMENTS: Weight 99 kg, height 175 cm, body mass index 32.4 kg/m2.

CO-MORBIDITIES: Type 2 diabetes mellitus on metformin, HbA1c 8.4%. No obstructive sleep
apnoea on a recent home sleep study. Blood pressure normal off medication, no hypertension.

WEIGHT MANAGEMENT HISTORY: Eighteen months with a commercial programme and a further
9-month supervised course with dietetics; weight has not fallen below 96 kg. Medical
weight management is documented as unsuccessful.

INDICATION: Surgery proposed to improve glycaemic control, not for weight loss alone.

PLAN: Laparoscopic sleeve gastrectomy discussed. Patient counselled that his body mass
index is below the threshold in the national coverage determination.
""",
    [
        f("bmi", 32.4, "body mass index 32.4 kg/m2", "kg/m2"),
        f("type_2_diabetes", True, "Type 2 diabetes mellitus on metformin"),
        f("obstructive_sleep_apnea", False, "No obstructive sleep\napnoea on a recent home sleep study"),
        f("hypertension", False, "no hypertension"),
        f("medical_weight_management_failed", True, "Medical\nweight management is documented as unsuccessful"),
        f("procedure", "laparoscopic_sleeve_gastrectomy", "Laparoscopic sleeve gastrectomy discussed"),
        f("indication_is_obesity_alone", False, "not for weight loss alone"),
    ],
    "DENY", "bmi",
    "BMI 32.4 against a threshold of 35; every other criterion is met.",
)

case(
    "bariatric_03", "bariatric_surgery", "58F, BMI 38, weight management history not documented",
    """
BARIATRIC SURGERY EVALUATION — SYNTHETIC TEACHING CASE

58-year-old woman referred by her primary care physician for bariatric surgery.

MEASUREMENTS: Weight 104 kg, height 165 cm, body mass index 38.2 kg/m2.

CO-MORBIDITIES: Obstructive sleep apnoea confirmed on polysomnography, AHI 31, established
on CPAP. No diabetes on recent screening.

WEIGHT MANAGEMENT HISTORY: The patient reports "trying everything over the years". No
dietetic records, programme documentation or pharmacotherapy trials were available at the
time of this consultation. Records have been requested from the referring practice.

INDICATION: Surgery under consideration for co-morbid sleep apnoea rather than for weight
loss alone.

PLAN: Roux-en-Y gastric bypass provisionally planned. Decision deferred pending the weight
management documentation.
""",
    [
        f("bmi", 38.2, "body mass index 38.2 kg/m2", "kg/m2"),
        f("obstructive_sleep_apnea", True, "Obstructive sleep apnoea confirmed on polysomnography"),
        f("type_2_diabetes", False, "No diabetes on recent screening"),
        f("procedure", "roux_en_y_gastric_bypass", "Roux-en-Y gastric bypass provisionally planned"),
        f("indication_is_obesity_alone", False, "rather than for weight\nloss alone"),
    ],
    "INDETERMINATE", "prior_treatment",
    "Prior medical weight management is neither documented nor excluded; the record cannot "
    "support approval or denial.",
)

# ===========================================================================
# TAVR
# ===========================================================================

case(
    "tavr_01", "tavr", "81M, symptomatic severe AS, experienced programme",
    """
STRUCTURAL HEART CLINIC NOTE — SYNTHETIC TEACHING CASE

81-year-old man with severe symptomatic aortic stenosis.

HPI: Exertional syncope twice in the past three months, NYHA class III dyspnoea. Echo shows
aortic valve area 0.7 cm2, mean gradient 48 mm Hg. Symptomatic severe aortic stenosis
confirmed.

HEART TEAM: Independently examined face-to-face by the cardiac surgeon and by the
interventional cardiologist. Both have documented their rationale for recommending
transcatheter over surgical replacement and shared it with the heart team. Both will
participate jointly in the intra-operative technical aspects of the procedure.

DEVICE: Balloon-expandable valve and delivery system with FDA premarket approval for this
indication.

SITE: The hospital runs an established TAVR programme meeting the experienced-programme
volume qualifications, with on-site heart valve surgery and interventional cardiology
programmes and a cardiothoracic intensive care unit staffed by personnel experienced in
open-heart valve recovery.

PLAN: Proceed to transfemoral TAVR.
""",
    [
        f("symptomatic_aortic_stenosis", True, "Symptomatic severe aortic stenosis\nconfirmed"),
        f("fda_approved_system", True, "delivery system with FDA premarket approval for this\nindication"),
        f("cardiac_surgeon_examined", True, "Independently examined face-to-face by the cardiac surgeon"),
        f("interventional_cardiologist_examined", True, "and by the\ninterventional cardiologist"),
        f("heart_team_rationale_documented", True, "documented their rationale for recommending\ntranscatheter over surgical replacement"),
        f("joint_intraoperative_participation", True, "participate jointly in the intra-operative technical aspects"),
        f("onsite_valve_surgery_program", True, "on-site heart valve surgery"),
        f("onsite_interventional_cardiology_program", True, "interventional cardiology\nprogrammes"),
        f("post_procedure_icu", True, "cardiothoracic intensive care unit staffed by personnel experienced"),
        f("established_tavr_program", True, "established TAVR programme meeting the experienced-programme\nvolume qualifications"),
    ],
    "APPROVE", None,
)

case(
    "tavr_02", "tavr", "79F, new programme, volume figures not supplied",
    """
STRUCTURAL HEART CLINIC NOTE — SYNTHETIC TEACHING CASE

79-year-old woman with severe symptomatic aortic stenosis referred for TAVR.

HPI: NYHA class III dyspnoea and exertional angina. Aortic valve area 0.8 cm2, mean gradient
44 mm Hg. Symptomatic severe aortic stenosis.

HEART TEAM: Examined face-to-face by both the cardiac surgeon and the interventional
cardiologist, each independently. Rationale documented and circulated to the heart team.
Both will scrub jointly for the procedure.

DEVICE: Self-expanding valve system with FDA premarket approval.

SITE: This would be the first TAVR performed at this hospital; the programme is new and has
no prior TAVR experience. On-site heart valve surgery and interventional cardiology
programmes are in place and the intensive care unit is staffed by personnel experienced in
open-heart valve recovery. The institutional case volumes required for a new programme were
requested from the hospital's quality office and had not been supplied at the time of this
note.

PLAN: Proceed once the site qualification file is complete.
""",
    [
        f("symptomatic_aortic_stenosis", True, "Symptomatic severe aortic stenosis."),
        f("fda_approved_system", True, "Self-expanding valve system with FDA premarket approval"),
        f("cardiac_surgeon_examined", True, "Examined face-to-face by both the cardiac surgeon"),
        f("interventional_cardiologist_examined", True, "the interventional\ncardiologist, each independently"),
        f("heart_team_rationale_documented", True, "Rationale documented and circulated to the heart team"),
        f("joint_intraoperative_participation", True, "Both will scrub jointly for the procedure"),
        f("onsite_valve_surgery_program", True, "On-site heart valve surgery"),
        f("onsite_interventional_cardiology_program", True, "interventional cardiology\nprogrammes are in place"),
        f("post_procedure_icu", True, "intensive care unit is staffed by personnel experienced"),
        f("established_tavr_program", False, "the programme is new and has\nno prior TAVR experience"),
    ],
    "INDETERMINATE", "open_heart_volume",
    "The hospital cannot qualify on the experienced-programme route and the new-programme "
    "volumes are absent from the record, so the site question is unresolved rather than failed.",
)

case(
    "tavr_03", "tavr", "83M, two independent failures: no surgeon assessment, PCI volume short",
    """
STRUCTURAL HEART CLINIC NOTE — SYNTHETIC TEACHING CASE

83-year-old man with severe symptomatic aortic stenosis, referred for TAVR.

HPI: Two admissions with decompensated heart failure in four months. Aortic valve area
0.6 cm2, mean gradient 52 mm Hg, symptomatic severe aortic stenosis.

HEART TEAM: Seen and examined by the interventional cardiologist. The cardiac surgeon has
reviewed the imaging remotely but has not examined the patient face-to-face; a surgical
assessment has not yet taken place. The interventional cardiologist's rationale is
documented. The surgeon has confirmed availability to participate jointly in the procedure.

DEVICE: Balloon-expandable system with FDA premarket approval.

SITE: New TAVR programme with no prior TAVR experience. Institutional figures for the
preceding period: 62 open heart surgeries in the previous year, 24 aortic valve related
procedures over the previous two years, 3 physicians with cardiac surgery privileges,
2 physicians with interventional cardiology privileges, and 210 percutaneous coronary
interventions per year. On-site valve surgery and interventional cardiology programmes with
an experienced post-procedure intensive care unit.

ASSESSMENT: Neither the surgical assessment nor the institutional PCI volume meets the
coverage conditions.
""",
    [
        f("symptomatic_aortic_stenosis", True, "symptomatic severe aortic stenosis"),
        f("fda_approved_system", True, "Balloon-expandable system with FDA premarket approval"),
        f("cardiac_surgeon_examined", False, "has not examined the patient face-to-face"),
        f("interventional_cardiologist_examined", True, "Seen and examined by the interventional cardiologist"),
        f("heart_team_rationale_documented", True, "The interventional cardiologist's rationale is\ndocumented"),
        f("joint_intraoperative_participation", True, "confirmed availability to participate jointly in the procedure"),
        f("onsite_valve_surgery_program", True, "On-site valve surgery"),
        f("onsite_interventional_cardiology_program", True, "interventional cardiology programmes with\nan experienced post-procedure intensive care unit"),
        f("post_procedure_icu", True, "experienced post-procedure intensive care unit"),
        f("established_tavr_program", False, "New TAVR programme with no prior TAVR experience"),
        f("open_heart_surgeries_prior_year", 62, "62 open heart surgeries in the previous year", "cases"),
        f("aortic_valve_procedures_prior_2_years", 24, "24 aortic valve related\nprocedures over the previous two years", "cases"),
        f("cardiac_surgeons_on_staff", 3, "3 physicians with cardiac surgery privileges", "physicians"),
        f("interventional_cardiologists_on_staff", 2, "2 physicians with interventional cardiology privileges", "physicians"),
        f("pci_per_year", 210, "210 percutaneous coronary\ninterventions per year", "cases"),
    ],
    "DENY", "surgeon_exam",
    "Two independent failures: no face-to-face surgical assessment, and institutional PCI "
    "volume of 210 against a 300 threshold. The missing surgical assessment is the one a "
    "reviewer would cite, since it concerns the patient rather than the site.",
)

# ===========================================================================
# cochlear implant
# ===========================================================================

case(
    "cochlear_01", "cochlear_implant", "66F, bilateral SNHL, 38% sentence recognition",
    """
OTOLOGY CONSULTATION — SYNTHETIC TEACHING CASE

66-year-old woman with progressive bilateral hearing loss over 12 years.

AUDIOLOGY: Bilateral moderate-to-profound sensorineural hearing impairment. Best-aided
open-set sentence recognition 38% on recorded AzBio testing, unchanged after a 3-month
hearing aid trial with appropriately fitted devices.

COGNITION AND MOTIVATION: MoCA 28/30. She understands the rehabilitation commitment and is
willing to undertake an extended programme of aural rehabilitation.

EXAMINATION AND IMAGING: Tympanic membranes intact and dry, no middle ear infection. CT of
the temporal bones shows patent, normally formed cochleae with an accessible cochlear
lumen bilaterally. MRI shows intact cochlear nerves with no retrocochlear lesion.

ANAESTHETIC REVIEW: Fit for general anaesthesia, no contraindication to surgery.

DEVICE: Implantation planned with a device used according to its FDA-approved labelling.
""",
    [
        f("bilateral_sensorineural_hearing_loss", True, "Bilateral moderate-to-profound sensorineural hearing impairment"),
        f("best_aided_sentence_recognition_percent", 38, "open-set sentence recognition 38% on recorded AzBio testing", "%"),
        f("cognitive_ability_and_willingness", True, "willing to undertake an extended programme of aural rehabilitation"),
        f("middle_ear_infection", False, "no middle ear infection"),
        f("cochlear_lumen_accessible", True, "accessible cochlear\nlumen bilaterally"),
        f("auditory_nerve_lesion", False, "intact cochlear nerves with no retrocochlear lesion"),
        f("surgical_contraindication", False, "no contraindication to surgery"),
        f("fda_labeling_compliant", True, "used according to its FDA-approved labelling"),
    ],
    "APPROVE", None,
)

case(
    "cochlear_02", "cochlear_implant", "71M, 74% sentence recognition with aids",
    """
OTOLOGY CONSULTATION — SYNTHETIC TEACHING CASE

71-year-old man requesting cochlear implantation.

AUDIOLOGY: Bilateral moderate sensorineural hearing impairment. Best-aided open-set
sentence recognition 74% in the best-aided listening condition on recorded testing,
following optimisation of his current hearing aids.

COGNITION AND MOTIVATION: Cognitively intact and willing to commit to rehabilitation.

EXAMINATION AND IMAGING: No middle ear infection. Patent cochleae with accessible lumen on
CT. No auditory nerve or central lesion on MRI.

ANAESTHETIC REVIEW: No contraindication to surgery.

DEVICE: The device under consideration would be used in accordance with its FDA-approved
labelling.

ASSESSMENT: Hearing loss is real and disabling, but aided sentence recognition remains
above the threshold at which limited benefit from amplification is established. Continue
with optimised amplification and repeat testing in 12 months.
""",
    [
        f("bilateral_sensorineural_hearing_loss", True, "Bilateral moderate sensorineural hearing impairment"),
        f("best_aided_sentence_recognition_percent", 74, "sentence recognition 74% in the best-aided listening condition", "%"),
        f("cognitive_ability_and_willingness", True, "Cognitively intact and willing to commit to rehabilitation"),
        f("middle_ear_infection", False, "No middle ear infection."),
        f("cochlear_lumen_accessible", True, "Patent cochleae with accessible lumen on\nCT"),
        f("auditory_nerve_lesion", False, "No auditory nerve or central lesion on MRI"),
        f("surgical_contraindication", False, "No contraindication to surgery."),
        f("fda_labeling_compliant", True, "used in accordance with its FDA-approved\nlabelling"),
    ],
    "DENY", "sentence_score",
    "74% aided sentence recognition against a 60% ceiling.",
)

# ===========================================================================
# PET oncology
# ===========================================================================

case(
    "pet_01", "pet_oncology", "64F, biopsy-proven lung cancer, initial staging",
    """
ONCOLOGY CLINIC NOTE — SYNTHETIC TEACHING CASE

64-year-old woman with a newly diagnosed right upper lobe mass.

PATHOLOGY: CT-guided biopsy confirms non-small cell lung carcinoma, adenocarcinoma subtype.
Biopsy-proven malignancy.

CLINICAL QUESTION: Treatment planning depends on whether disease is confined to the chest.
FDG PET-CT is requested to determine the anatomic extent of tumour before committing to
definitive chemoradiotherapy versus surgical resection.

TREATMENT CONTEXT: This is the initial anti-tumour treatment strategy; the patient has not
received any anti-cancer therapy and has had no previous PET studies.

ASSESSMENT: Newly diagnosed NSCLC for staging prior to first-line treatment.
""",
    [
        f("biopsy_proven_cancer", True, "Biopsy-proven malignancy"),
        f("determines_tumor_extent", True, "determine the anatomic extent of tumour"),
        f("treatment_strategy", "initial", "This is the initial anti-tumour treatment strategy"),
        f("tumor_type", "non_small_cell_lung", "non-small cell lung carcinoma, adenocarcinoma subtype"),
        f("study_purpose", "distant_staging", "whether disease is confined to the chest"),
    ],
    "APPROVE", None,
)

case(
    "pet_02", "pet_oncology", "70M, prostate adenocarcinoma, initial strategy",
    """
ONCOLOGY CLINIC NOTE — SYNTHETIC TEACHING CASE

70-year-old man with newly diagnosed prostate cancer.

PATHOLOGY: Transrectal biopsy shows adenocarcinoma of the prostate, Gleason 4+3, in 7 of 12
cores. Biopsy-proven disease.

CLINICAL QUESTION: The multidisciplinary team asks for FDG PET-CT to determine the anatomic
extent of tumour before deciding between radical prostatectomy and radiotherapy.

TREATMENT CONTEXT: Initial anti-tumour treatment strategy. No prior anti-cancer therapy and
no previous PET imaging.

ASSESSMENT: Newly diagnosed prostate adenocarcinoma. FDG PET for the initial treatment
strategy in prostate adenocarcinoma is a nationally non-covered indication; a PSMA PET has
been requested instead.
""",
    [
        f("biopsy_proven_cancer", True, "Biopsy-proven disease"),
        f("determines_tumor_extent", True, "determine the anatomic\nextent of tumour"),
        f("treatment_strategy", "initial", "Initial anti-tumour treatment strategy"),
        f("tumor_type", "prostate_adenocarcinoma", "adenocarcinoma of the prostate, Gleason 4+3"),
        f("study_purpose", "distant_staging", "before deciding between radical prostatectomy and radiotherapy"),
    ],
    "DENY", "prostate",
    "Explicitly non-covered tumour type for the initial treatment strategy.",
)

# ===========================================================================
# power wheelchair
# ===========================================================================

case(
    "power_wheelchair_01", "power_wheelchair", "72M, post-stroke, power wheelchair",
    """
PHYSICAL MEDICINE AND REHABILITATION NOTE — SYNTHETIC TEACHING CASE

72-year-old man 8 months after a left middle cerebral artery infarct, assessed for mobility
equipment in the home.

FUNCTION: Dense right hemiparesis. He cannot cross his one-bedroom flat to reach the toilet
or kitchen without assistance and is unable to accomplish mobility-related activities of
daily living entirely on his own.

OTHER LIMITATIONS: Cognition intact, MoCA 27/30; vision corrected and adequate. No other
condition limits his participation in these activities.

TRIALS: A cane and a rollator were both trialled in the clinic gym and in the home; neither
resolved the functional mobility deficit, as he cannot maintain standing balance with
right-sided weakness. He is unable to self-propel a manual wheelchair, and he lives alone
with no caregiver available, willing and able to propel one for him. He could not maintain
the trunk control needed to operate a scooter safely.

ENVIRONMENT: Flat is single level with wide doorways; the home supports wheelchair use.

SAFETY: Demonstrated safe joystick control of a power wheelchair over two sessions. The
power wheelchair's seating and control features are needed for him to participate in these
activities.
""",
    [
        f("prevents_mradls", True, "unable to accomplish mobility-related activities of\ndaily living entirely"),
        f("other_limiting_conditions", False, "No other\ncondition limits his participation in these activities"),
        f("safe_operation_demonstrated", True, "Demonstrated safe joystick control of a power wheelchair"),
        f("cane_or_walker_sufficient", False, "neither\nresolved the functional mobility deficit"),
        f("home_environment_supports_wheelchair", True, "the home supports wheelchair use"),
        f("can_self_propel_manual_wheelchair", False, "He is unable to self-propel a manual wheelchair"),
        f("caregiver_available_for_manual_wheelchair", False, "no caregiver available, willing and able to propel one"),
        f("can_operate_pov", False, "could not maintain\nthe trunk control needed to operate a scooter safely"),
        f("power_features_needed", True, "seating and control features are needed"),
    ],
    "APPROVE", None,
)

case(
    "power_wheelchair_02", "power_wheelchair", "68F, two independent failures: walker suffices, caregiver available",
    """
PHYSICAL MEDICINE AND REHABILITATION NOTE — SYNTHETIC TEACHING CASE

68-year-old woman with osteoarthritis of both knees, requesting a power wheelchair.

FUNCTION: Reports needing to rest twice crossing her house. She cannot complete
mobility-related activities of daily living within a reasonable time frame without support.

OTHER LIMITATIONS: Cognition and vision intact; no other condition limits participation.

TRIALS: With a fitted four-wheeled walker she completed the kitchen-to-bathroom circuit in
under two minutes with no rest break and no loss of balance; the walker resolves her
functional mobility deficit. She was also able to self-propel a manual wheelchair 30 metres
indoors without difficulty. Her daughter lives in the same house and is available, willing
and able to assist with a manual wheelchair when needed.

ENVIRONMENT: Single-level home with adequate turning space; the environment supports
wheelchair use.

SAFETY: Operated a power wheelchair safely in the clinic.

ASSESSMENT: Mobility deficit is real but is resolved with a walker, and a manual wheelchair
with caregiver assistance is available.
""",
    [
        f("cannot_complete_mradls_timely", True, "cannot complete\nmobility-related activities of daily living within a reasonable time frame"),
        f("other_limiting_conditions", False, "no other condition limits participation"),
        f("safe_operation_demonstrated", True, "Operated a power wheelchair safely in the clinic"),
        f("cane_or_walker_sufficient", True, "the walker resolves her\nfunctional mobility deficit"),
        f("home_environment_supports_wheelchair", True, "the environment supports\nwheelchair use"),
        f("can_self_propel_manual_wheelchair", True, "able to self-propel a manual wheelchair 30 metres"),
        f("caregiver_available_for_manual_wheelchair", True, "available, willing\nand able to assist with a manual wheelchair"),
        f("power_features_needed", False, "Mobility deficit is real but is resolved with a walker"),
    ],
    "DENY", "cane_walker_insufficient",
    "Two independent failures: the walker resolves the deficit, and a manual wheelchair with "
    "an available caregiver is sufficient. The walker finding is the earlier step in the "
    "policy's own sequence.",
)

# ===========================================================================
# CGM
# ===========================================================================

case(
    "cgm_01", "cgm", "59F, type 1 diabetes on insulin, CGM requested",
    """
ENDOCRINOLOGY CLINIC NOTE — SYNTHETIC TEACHING CASE

59-year-old woman with type 1 diabetes mellitus of 31 years' duration.

TREATMENT: Multiple daily injections, four times daily, with insulin glargine and insulin
aspart. Seen in this clinic today by her treating endocrinologist.

GLYCAEMIC CONTROL: HbA1c 8.1%. Two episodes of level 2 hypoglycaemia in the past month, one
requiring assistance from her partner overnight.

DEVICE HISTORY: She has never been supplied with a continuous glucose monitor and does not
have an active device from another supplier.

TRAINING: Completed the structured device training session with the diabetes specialist
nurse at today's visit, including sensor insertion, alarm settings and data review.

PLAN: Continuous glucose monitor prescribed.
""",
    [
        f("diabetes_diagnosis", True, "type 1 diabetes mellitus of 31 years' duration"),
        f("insulin_treated", True, "Multiple daily injections, four times daily"),
        f("problematic_hypoglycemia_history", True, "Two episodes of level 2 hypoglycaemia in the past month"),
        f("months_since_practitioner_visit", 0, "Seen in this clinic today by her treating endocrinologist", "months"),
        f("device_training_completed", True, "Completed the structured device training session"),
        f("active_cgm_already_supplied", False, "does not\nhave an active device from another supplier"),
    ],
    "APPROVE", None,
)

case(
    "cgm_02", "cgm", "63M, type 2 diabetes, last practitioner visit undated",
    """
PHARMACY REFILL REVIEW — SYNTHETIC TEACHING CASE

63-year-old man with type 2 diabetes mellitus, reviewed for a continuous glucose monitor
request submitted by a supplier.

TREATMENT: On insulin degludec once daily plus metformin.

CLINICAL CONTACT: The supplier's form states that the patient is "under the care of his
family physician". No date of the most recent in-person or telehealth visit with the
treating practitioner appears anywhere in the supplied documentation, and no clinic note
accompanies the request.

DEVICE HISTORY: No active continuous glucose monitor from another supplier.

TRAINING: Device training is listed as scheduled but not yet completed; the training record
is not attached.

ASSESSMENT: Request cannot be adjudicated on the documentation supplied.
""",
    [
        f("diabetes_diagnosis", True, "type 2 diabetes mellitus"),
        f("insulin_treated", True, "On insulin degludec once daily plus metformin"),
        f("active_cgm_already_supplied", False, "No active continuous glucose monitor from another supplier"),
    ],
    "INDETERMINATE", "visit_recency",
    "Neither the visit date nor completed training is documented; the request is unresolvable "
    "as submitted rather than deniable.",
)


# ===========================================================================
# build
# ===========================================================================

def resolve_spans(note: str, raw_facts: List[Dict[str, Any]], case_id: str) -> List[Dict[str, Any]]:
    """Locate each fact's evidence in the note and record the real offsets.

    Matching ignores how whitespace happens to fall, so that rewrapping a note
    does not silently break every span, but the recorded ``evidence_text`` is
    the note's own text at those offsets — never the search string. An evidence
    phrase that is missing, or that matches in more than one place, is a build
    error rather than a guess.
    """
    facts = []
    problems = []
    for raw in raw_facts:
        evidence = raw["evidence"]
        pattern = r"\s+".join(re.escape(part) for part in evidence.split())
        matches = list(re.finditer(pattern, note))
        if not matches:
            problems.append("{0}/{1}: evidence not found in note: {2!r}".format(case_id, raw["key"], evidence))
            continue
        if len(matches) > 1:
            problems.append("{0}/{1}: evidence matches {2} places, span would be ambiguous: {3!r}".format(
                case_id, raw["key"], len(matches), evidence))
            continue
        start, end = matches[0].span()
        facts.append({
            "key": raw["key"],
            "value": raw["value"],
            "unit": raw["unit"],
            "confidence": raw["confidence"],
            "source_span": [start, end],
            "evidence_text": note[start:end],
        })
    if problems:
        raise SystemExit("\n".join(problems))
    return facts


def main() -> int:
    sys.path.insert(0, ROOT)
    from pipeline.evaluate import evaluate  # noqa: E402
    from pipeline.validate import validate_case  # noqa: E402

    policies = {}
    for name in os.listdir(POLICY_DIR):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(POLICY_DIR, name), "r", encoding="utf-8") as handle:
            policy = json.load(handle)
        policies[policy["policy_id"]] = policy

    os.makedirs(OUT_DIR, exist_ok=True)
    counts = {"APPROVE": 0, "DENY": 0, "INDETERMINATE": 0}
    label_mismatches = []
    attribution_mismatches = []

    for entry in CASES:
        policy = policies[entry["policy_id"]]
        note = entry["note_text"]
        facts = resolve_spans(note, entry["raw_facts"], entry["case_id"])
        case_json = {
            "case_id": entry["case_id"],
            "policy_id": entry["policy_id"],
            "title": entry["title"],
            "synthetic": True,
            "note_text": note,
            "facts": facts,
            "gold_decision": entry["gold_decision"],
            "gold_blocking_node": entry["gold_blocking_node"],
            "note_on_gold": entry["note_on_gold"],
        }
        errors = validate_case(case_json, policy)
        if errors:
            raise SystemExit("\n".join(errors))

        result = evaluate(policy, facts)
        if result["decision"] != entry["gold_decision"]:
            label_mismatches.append("{0}: evaluator says {1}, gold says {2}".format(
                entry["case_id"], result["decision"], entry["gold_decision"]))
        if entry["gold_blocking_node"] and result["blocking_node"] != entry["gold_blocking_node"]:
            attribution_mismatches.append("{0}: evaluator cites {1}, gold cites {2}".format(
                entry["case_id"], result["blocking_node"], entry["gold_blocking_node"]))

        counts[entry["gold_decision"]] += 1
        with open(os.path.join(OUT_DIR, "{0}.json".format(entry["case_id"])), "w", encoding="utf-8") as handle:
            json.dump(case_json, handle, indent=1)
            handle.write("\n")

    print("wrote {0} cases: {1} approve, {2} deny, {3} indeterminate".format(
        len(CASES), counts["APPROVE"], counts["DENY"], counts["INDETERMINATE"]))

    # A decision-label mismatch means the note and the gold label disagree, which is an
    # authoring bug — fix the note or the label. An attribution mismatch is a real
    # finding about the ranking rules and is reported, not silenced.
    if label_mismatches:
        print("\nDECISION MISMATCHES (authoring bugs, fix these):")
        for mismatch in label_mismatches:
            print("  - {0}".format(mismatch))
    if attribution_mismatches:
        print("\nattribution disagreements (kept; these show up in the eval as misses):")
        for mismatch in attribution_mismatches:
            print("  - {0}".format(mismatch))
    return 1 if label_mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
