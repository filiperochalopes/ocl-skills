# Choosing `concept_class` and `datatype`

Every concept needs both. Neither should be defaulted into: `Misc` and `N/A` are
legitimate answers, but only when someone decided they are the right ones. A value that
merely fell through is reported as `concept-class-unclassified` /
`datatype-unclassified` and shows up in the review CSV as `Misc (UNCLASSIFIED)`.

Classify from the concept's name and description, then record the reasoning in the
concept's `note` field so the reviewer can check the judgement rather than re-derive it.

---

## 1. `concept_class` — what kind of thing is this?

Ask first: **is this a question someone answers, a thing that exists, or a grouping?**

### Questions and their answers

| Class | Use for | Example |
| --- | --- | --- |
| `Test` | a laboratory or diagnostic measurement | Serum creatinine; Malaria rapid diagnostic test |
| `Question` | a non-test question on a form | Reason for visit; Highest education level |
| `Procedure` | an action performed on a patient | Appendectomy; Wound dressing |
| `Radiology/Imaging Procedure` | imaging specifically | Chest X-ray, PA view |
| `Misc Order` | an orderable that is not a test, drug or procedure | Physiotherapy referral |

### Clinical statements

| Class | Use for | How to tell it apart |
| --- | --- | --- |
| `Diagnosis` | a disease or disorder a clinician can diagnose | Would appear on a problem list |
| `Finding` | an objective clinical observation, not a formal diagnosis | Observed by the clinician |
| `Symptom` | subjective, reported by the patient | Reported, not observed |
| `Symptom/Finding` | genuinely either, or the source does not distinguish | Use when forcing a choice would be wrong |

When a term could be `Diagnosis` or `Finding`, ask whether it names a disease entity
(`Diagnosis`) or describes an observation (`Finding`). "Malaria" is a diagnosis;
"Splenomegaly" is a finding.

### Things

| Class | Use for |
| --- | --- |
| `Anatomy` | body structures |
| `Organism` | pathogens and other organisms |
| `Specimen` | sample types — whole blood, CSF |
| `Drug` | a specific drug product or formulation |
| `Pharmacologic Drug Class` | a drug class — ACE inhibitors |
| `Drug form`, `Dose Form Group` | tablet, suspension; and their groupings |
| `Medical supply` | consumables and devices |
| `Frequency` | dosing frequencies — twice daily |
| `Units of Measure` | units used by numeric concepts |

### Groupings (sets)

| Class | Use for |
| --- | --- |
| `LabSet` | a panel of test results reported together |
| `MedSet` | a grouping of drugs |
| `ConvSet` | a convenience set — the concepts on one form or section |
| `InteractSet` | interaction sets |

A set class **requires** `CONCEPT-SET` member mappings (CE-04 under the CIEL profile) —
so only choose one when the members are actually part of the batch or already exist.

### Program and reporting

| Class | Use for |
| --- | --- |
| `Program`, `Workflow`, `State` | program enrolment modelling |
| `Indicator`, `Aggregate Measurement` | aggregate reporting |
| `Health Care Monitoring Topics` | monitoring topics |

### `Misc`

The honest answer when nothing above fits. Set it explicitly and say why in `note`.

---

## 2. `datatype` — what shape is the answer?

**`datatype` only carries meaning for question-like concepts.** For everything else —
diagnoses, findings, anatomy, organisms, drugs, sets — the answer is `N/A`, stated
explicitly.

| Datatype | Use when the answer is | Notes |
| --- | --- | --- |
| `Coded` | one of a fixed set of concepts | The default for most `Test` and `Question` concepts |
| `Numeric` | a number | Needs numeric metadata; a `Test` also needs `extras.units` |
| `Text` | free text | |
| `Boolean` | strictly true/false | Many dictionaries prefer `Coded` with Yes/No concepts — follow the source's convention |
| `Date`, `Datetime`, `Time` | a point in time | |
| `Complex`, `Document` | an attachment or structured blob | |
| `Structured Numeric` | a numeric expression such as a titre | |
| `Rule`, `N/A` | a computed rule; or not applicable | |

### The decision in one pass

1. Is the concept a `Test` or `Question`? If not → `N/A`.
2. Does it yield a measured number? → `Numeric`, and supply units for a `Test`.
3. Does it yield one of a known set of answers? → `Coded`.
4. Free text, a date, or a file? → `Text` / `Date` / `Complex`.
5. Otherwise → `N/A`, explicitly.

A `Numeric` concept without units is the single most common classification mistake. If
the units are unknown, that is a question for the curator, not a field to leave blank.

---

## 3. Worked examples

| Name | `concept_class` | `datatype` | Why |
| --- | --- | --- | --- |
| Serum creatinine | `Test` | `Numeric` | measured quantity; units mg/dL |
| Malaria rapid diagnostic test, P. falciparum | `Test` | `Coded` | the answer is positive/negative/indeterminate |
| Malaria RDT panel | `LabSet` | `N/A` | groups the individual results |
| Malaria | `Diagnosis` | `N/A` | a disease entity, not a question |
| Splenomegaly | `Finding` | `N/A` | an observation |
| Headache | `Symptom` | `N/A` | patient-reported |
| Plasmodium falciparum | `Organism` | `N/A` | a thing, not a question |
| Whole blood | `Specimen` | `N/A` | sample type |
| Date of last menstrual period | `Question` | `Date` | a form question yielding a date |
| Artemether/lumefantrine 20/120 mg tablet | `Drug` | `N/A` | a drug product |

---

## 4. When confidence is low

Do not guess silently. Two options, in order of preference:

1. **Ask the user**, when a handful of rows are unclear and the answer changes the
   concept's meaning.
2. **Classify with your best judgement and flag it**, when the batch is large: put the
   uncertainty in `note` ("class uncertain: could be Finding or Diagnosis") and say in
   the handover which rows the reviewer should look at hardest.

Both are better than a silent `Misc`. The CSV gate exists precisely so a human can
overrule a classification before anything is imported — but only if the classification
is visible and the doubt is written down.
