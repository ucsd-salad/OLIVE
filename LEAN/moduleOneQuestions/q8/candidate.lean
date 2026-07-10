import Tutorial.Lean.moduleOneRevised

-- A patient with a priority sign (burn) but no emergency signs
def examplePatient : Patient :=
{
  ageInMonth := some 24,          -- not a tiny baby
  breathing := some true,         -- breathing (no airway emergency)
  airwayObstructed := some false,
  centralCyanosis := some false,
  emotion := none,
  severeChestIndrawing := some false,
  accessoryMuscleUseBreating := some false,
  unableToTalkEatFeed := some false,
  veryFastBreathing := some false,
  breatingIsTiring := some false,
  capillaryRefill := some 2,      -- normal (not > 3)
  pulse := some Pulse.normal,
  avpu := some AVPU.Alert,
  sunkenEyes := some false,
  skinTurgor := some SpeedMeasurement.normal,
  temperature := some Temperature.normal,
  fracture := some false,
  headInjury := some false,
  acuateAbdominalPain := some false,
  whitePalm := some false,
  poison := some false,
  agony := some false,
  urgentReferral := some false,
  wasting := some false,
  oedema := some [],
  burn := some true              -- priority sign: burn
}

-- If the child has a priority sign (and no emergency signs), they should be triaged as Priority
theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Priority := by
  -- Unfold all definitions and let Lean evaluate
  native_decide