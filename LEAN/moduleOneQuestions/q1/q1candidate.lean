import Tutorial.Lean.moduleOneRevised

def examplePatient : Patient :=
{
  ageInMonth := some 36,              -- 3 years old = 36 months
  breathing := some true,             -- breathing is OK
  airwayObstructed := some false,     -- airway is OK
  centralCyanosis := some false,      -- airway assessment OK implies no central cyanosis
  capillaryRefill := some 1,          -- 1.5 seconds, represented as Nat (1); normal range
  avpu := some AVPU.Alert,            -- she is alert
  skinTurgor := some SpeedMeasurement.slow,  -- skin pinch takes 3 seconds = slow return
  oedema := none                      -- no information given about oedema
}

-- The skin pinch of 3 seconds indicates slow skin turgor → Dehydration is true → Emergency
-- Therefore triage should be Emergency.

theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Emergency := by
  -- Unfold all definitions and evaluate
  unfold TriageAssessment
  unfold Emergency
  unfold Airway
  unfold Breathing
  unfold SevereRespiratoryDistress
  unfold CirculationComaConulsion
  unfold CirculationProblems
  unfold Dehydration
  simp [examplePatient]
  simp [optionOrList, optionEq, optionGt, optionAndList]
