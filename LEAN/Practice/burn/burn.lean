namespace BurnProtocol
-- constraints based on: https://www.uptodate.com/contents/treatment-of-minor-thermal-burns?search=burn%20treatment&source=search_result&selectedTitle=1~150&usage_type=default&display_rank=1&searchCorrelationId=96d95265-c362-40f5-a5f5-becc88e05385&searchCorrelationTerm=burn%20treatment
-- Burn depth classification
-- using inductive instead of enum to allow for future extensibility, and so that Lean knows these are the only possible values
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


/-- burn classificaiton predicates (adding logic)-/
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


/-- def is a computable, executable object: since treamtnet is something we compute-/
-- input is Patient p and output is list of treamtnets
def initialTreatment (p : Patient) : List Treatment := -- := separates decleration v definition
-- let is a temp variable (base here is a local var of initialTreament)
  let base :=
  [
    Treatment.coolWater,
    Treatment.cleanse,
    Treatment.painManagement
  ]
  -- lean variables are immutable, so here we are building new base variables
  let base :=
    if p.tetanusCurrent then base
    else Treatment.tetanusProphylaxis :: base -- :: adds to front of the list

  let base :=
    if isNonSuperficialB p.burn then -- isNonSuperficial takes a burn and returns a boolean
      Treatment.topicalAntibiotic :: base
    else base

  if needsDressingB p.burn then
    Treatment.dressing :: base
  else base



def infectionTreatment (p : Patient) : List Treatment :=
if p.burn.infected then
[
  Treatment.admitHospital,
  Treatment.IVAntibiotics
]
else
[]


/-- return type is a Prop since referral is a logical criterion, not an action
 question: should referral be required? -/
def referralRequired (p : Patient) : Prop :=
-- means no epithelialization after one week OR thickness burn more than 2cm OR
-- necrosis OR infection
    (¬ p.burn.epithelializationStarted ∧ p.daySinceInjury ≥ 7)
 ∨ p.burn.largestFullThicknessCm > 2
 ∨ p.burn.necrotic
 ∨ p.burn.infected
 -- v operates on propositions


/-- inducttive: new data type, 3 possible outcomes-/
inductive FollowUp
| nextDay
| weekly
| frequent

def followup (p : Patient) : FollowUp :=
if p.daySinceInjury = 0 then
    FollowUp.nextDay
else if
     p.significantComorbidities
  || p.burn.infected   -- || operates on booleans
  || ¬ p.competentDressingCare then
    FollowUp.frequent
else
    FollowUp.weekly

def treatmentPlan (p : Patient) : List Treatment :=
  initialTreatment p ++ infectionTreatment p


/-- no longer computing anything, but theorem is asserting that something must be true -/
theorem nonSuperficialGetsAntibiotic
  (p : Patient)
  (h : isNonSuperficialB p.burn = true) : -- -- h means an assumption/hypothesis that the patient has a non-superficial burn
  Treatment.topicalAntibiotic ∈ initialTreatment p := by
    unfold initialTreatment -- replaces initialTreatment p with its definition
    simp only [h] -- replaces isNonSuperficialB p.burn with true
    by_cases dressing : needsDressingB p.burn = true <;> simp [dressing] -- replaces needsDressingB p.burn with true or false depending on the case
    -- <;> means run the same tactic in both branches automatically

theorem superficialNoDressing
  (p : Patient)
  (h : isSuperficial p.burn) :
  Treatment.dressing ∉ initialTreatment p := by
  unfold initialTreatment
  have hnd : needsDressingB p.burn = false := by --prove a lemma within the greater proof
    unfold needsDressingB isSuperficial at * --unfolds needsDressingB and any occurances of isSuperficial with its def (* means do it everywhere you can, including h)
    simp [h] -- replaces isSuperficial p.burn with true
  simp only [hnd] --replaces needsDressingB p.burn with false
  by_cases htet : p.tetanusCurrent <;>
  by_cases hab : isNonSuperficialB p.burn <;>
  simp [htet, hab]

theorem infectionRequiresAdmission
  (p : Patient)
  (h : p.burn.infected) :
  Treatment.admitHospital ∈ infectionTreatment p := by
  unfold infectionTreatment
  simp [h] -- plug in the assumption that p.burn.infected is true

theorem iceNeverRecommended (p : Patient) :
  Treatment.ice ∉ initialTreatment p ∧ Treatment.ice ∉ infectionTreatment p := by
  -- here, the constructor tactic breaks (here, And.intro) and makes 2 new goals (left and right hand side)
  constructor
  -- the bullet points are used since we have 2 differnt goals we are trying to prove
  -- one bullet for each goal
  · unfold initialTreatment
    by_cases htet : p.tetanusCurrent <;>
    by_cases hab : isNonSuperficialB p.burn <;>
    by_cases hnd : needsDressingB p.burn <;>
    simp [htet, hab, hnd]
  · unfold infectionTreatment
    by_cases hinf : p.burn.infected <;>
    simp [hinf]

/-- a candidate patient for testing -/
def candidatePatient : Patient :=
{ burn :=
  { depth := BurnDepth.superficial,
    sizePercentTBSA := 2,
    largestFullThicknessCm := 1,
    location := [BodyRegion.hand],
    epithelializationStarted := false,
    infected := false,
    necrotic := false },
  tetanusCurrent := true,
  painControlled := true,
  daySinceInjury := 0,
  competentDressingCare := true,
  significantComorbidities := false }

/-- a candidate plan that is unsafe -/
def candidatePlan : List Treatment :=
[
  Treatment.coolWater,
  Treatment.cleanse,
  Treatment.painManagement,
  Treatment.topicalAntibiotic
]

#eval treatmentPlan candidatePatient
