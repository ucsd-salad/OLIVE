import Tutorial.Lean.moduleOneRevised

-- A patient with a priority sign (burn) but no emergency signs
def examplePatient : Patient :=
{
  -- No emergency signs
  breathing := some true,          -- breathing is fine (not false)
  airwayObstructed := some false,
  centralCyanosis := some false,
  unableToTalkEatFeed := some false,
  severeChestIndrawing := some false,
  accessoryMuscleUseBreating := some false,
  veryFastBreathing := some false,
  breatingIsTiring := some false,
  capillaryRefill := some 2,       -- normal (not > 3)
  pulse := some Pulse.normal,
  avpu := some AVPU.Alert,
  sunkenEyes := some false,
  skinTurgor := some SpeedMeasurement.normal,
  -- Priority sign: burn
  burn := some true,
  -- Other priority fields explicitly false to keep things clean
  ageInMonth := some 24,
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
}

-- When a child has a priority sign (and no emergency signs), they should be triaged as Priority
theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Priority := by
  native_decide