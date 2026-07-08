import Tutorial.Lean.moduleOneRevised

-- The answer to "Where do you look for signs of severe wasting?" is:
-- Look rapidly at the arms, legs, and chest to assess wasting (marasmus).
-- This is documented in the `wasting` field of the Patient structure.
-- A patient with visible severe wasting is triaged as Priority.

def examplePatientWasting : Patient :=
{
  -- Patient presents with visible severe wasting
  -- (assessed by looking at arms, legs, chest)
  wasting := some true,

  -- No emergency signs (all ABCD criteria are false)
  breathing := some true,
  airwayObstructed := some false,
  centralCyanosis := some false,

  severeChestIndrawing := some false,
  accessoryMuscleUseBreating := some false,
  unableToTalkEatFeed := some false,
  veryFastBreathing := some false,
  breatingIsTiring := some false,

  capillaryRefill := some 2,
  pulse := some Pulse.normal,

  avpu := some AVPU.Alert,

  sunkenEyes := some false,
  skinTurgor := some SpeedMeasurement.normal,

  -- No other priority signs besides wasting
  ageInMonth := some 24,
  temperature := some Temperature.normal,
  fracture := some false,
  headInjury := some false,
  acuateAbdominalPain := some false,
  whitePalm := some false,
  poison := some false,
  agony := some false,
  urgentReferral := some false,
  oedema := some [],
  burn := some false,

  smiling := some false,
  crying := some false,
}

-- Prove that a patient with visible severe wasting is triaged as Priority
theorem ValidPlan :
  TriageAssessment examplePatientWasting = Triage.Priority := by
  native_decide