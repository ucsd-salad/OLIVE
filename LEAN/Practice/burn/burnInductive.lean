/-- this apporach is inductive predicate where the rules
are defined inductively and sorted into propositions, the plans
are then propositions of the type IsValidPlan -/

inductive BurnDepth
| superficial
| superficialPartial
| deepPartial
| fullThickness
-- DecidableEq allows for equality checks, Repr allows for printing (used by #eval)
deriving DecidableEq, Repr

/-- Anatomical regions that affect referral decisions. -/
inductive BodyRegion
-- example: BodyRegion.face is a value
| face
| hand
| foot
| joint
| perineum
| trunk
| extremity
deriving DecidableEq, Repr

/-- all the possible treatment actions (to standardize the vocab)-/
inductive Treatment
| coolWater
| cleanse
| topicalAntibiotic
| dressing
| painManagement
| tetanusProphylaxis
| debridement
| admitHospital
| IVAntibiotics
| referBurnSurgeon
| transferBurnCenter
| ice
deriving DecidableEq, Repr

/-- Burn observations. -/
--medical record or a row in a database
structure Burn where
  depth : BurnDepth --example depth = deepPartial
  sizePercentTBSA : Rat -- Total Body Surface Area (in percentage)
  largestFullThicknessCm : Rat -- rational numbers
  location : List BodyRegion
  epithelializationStarted : Bool -- would healing process
  infected : Bool
  necrotic : Bool -- premature death of the cells

/-- Patient information. -/
structure Patient where
  burn : Burn
  tetanusCurrent : Bool -- whether tenanus immnunization is up to date. if not, it should be given
  painControlled : Bool -- important for follow-up logic
  daySinceInjury : Nat  -- since the care is time sensitive
  competentDressingCare : Bool -- whether the patient can manage wound at home (if not, follow up or admission
  significantComorbidities : Bool -- whether the patient has other health risks (diabetes, etc)

/-- burn classificaiton predicates (adding logic) -/
def isSuperficial (b : Burn) : Prop :=
  b.depth = BurnDepth.superficial

def isSuperficialB (b : Burn) : Bool :=
  b.depth = BurnDepth.superficial

def isNonSuperficial (b : Burn) : Prop :=
  b.depth ≠ BurnDepth.superficial

def isNonSuperficialB (b : Burn) : Bool :=
  b.depth != BurnDepth.superficial

/-- encoding the clinical rules from UpToDate as a logic statement-/
def needsDressing (b : Burn) : Prop :=
  b.depth = BurnDepth.superficialPartial ∨
  b.depth = BurnDepth.deepPartial ∨
  b.depth = BurnDepth.fullThickness

def needsDressingB (b : Burn) : Bool :=
  b.depth = BurnDepth.superficialPartial ∨
  b.depth = BurnDepth.deepPartial ∨
  b.depth = BurnDepth.fullThickness

abbrev Plan := List Treatment

/--
`IsValidTreatmentPlan p plan` holds when `plan` can be built up one action at a time
for a given patient `p`, where each constructor encodes a clinical rule:

  • `nil` — the empty plan is always valid
  • `coolWater / cleanse / painManagement` — always allowed first-line actions
  • `tetanusProphylaxis` — allowed if patient is not up to date
  • `topicalAntibiotic` — allowed for non-superficial burns
  • `dressing` — required if `needsDressingB` holds
  • `admitHospital / IVAntibiotics` — only if infection is present

A plan is valid exactly when there is a derivation using these rules
that constructs the full treatment list.
-/
inductive IsValidTreatmentPlan : Patient → Plan → Prop where
  -- null plan is valid
  | nil (p : Patient) :
      IsValidTreatmentPlan p []

  -- base care (always allowed)
  | coolWater {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      IsValidTreatmentPlan p (plan ++ [Treatment.coolWater])

  | cleanse {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      IsValidTreatmentPlan p (plan ++ [Treatment.cleanse])

  | painManagement {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      IsValidTreatmentPlan p (plan ++ [Treatment.painManagement])

  -- tetanus only if not current
  | tetanusProphylaxis {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      p.tetanusCurrent = false →
      IsValidTreatmentPlan p (plan ++ [Treatment.tetanusProphylaxis])

  -- antibiotic rule for deeper burns
  | topicalAntibiotic {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      isNonSuperficialB p.burn →
      IsValidTreatmentPlan p (plan ++ [Treatment.topicalAntibiotic])

  -- dressing rule from clinical guideline encoding
  | dressing {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      needsDressingB p.burn →
      IsValidTreatmentPlan p (plan ++ [Treatment.dressing])

  -- infection escalation rules
  | admitHospital {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      p.burn.infected →
      IsValidTreatmentPlan p (plan ++ [Treatment.admitHospital])

  | IVAntibiotics {p : Patient} {plan : Plan} :
      IsValidTreatmentPlan p plan →
      p.burn.infected →
      IsValidTreatmentPlan p (plan ++ [Treatment.IVAntibiotics])


/-- proving an invalid plan (example intuition: antibiotic without indication) -/
example (p : Patient) (hInf : p.burn.infected = false) :
  ¬ IsValidTreatmentPlan p [Treatment.IVAntibiotics] := by
  intro h
  cases h with
  | nil => simp
  | coolWater hplan =>
      simp at hplan
  | cleanse hplan =>
      simp at hplan
  | painManagement hplan =>
      simp at hplan
  | tetanusProphylaxis hplan ht =>
      simp at ht
  | topicalAntibiotic hplan hcond =>
      simp at hcond
  | dressing hplan hcond =>
      simp at hcond
  | admitHospital hplan hinf =>
      simp at hinf at hInf
  | IVAntibiotics hplan hinf =>
      simp at hinf at hInf
