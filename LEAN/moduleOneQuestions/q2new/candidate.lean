import Tutorial.Lean.moduleOneRevised


def examplePatient : Patient :=
{
  ageInMonth := some 48,
  breathing := some true,
  airwayObstructed := some false,
  centralCyanosis := some false,
  severeChestIndrawing := some false,
  accessoryMuscleUseBreating := some false,
  unableToTalkEatFeed := some false,
  veryFastBreathing := some true,
  breatingIsTiring := some false,
  capillaryRefill := some 2,
  pulse := some Pulse.normal,
  avpu := some AVPU.Alert,
  sunkenEyes := some false,
  skinTurgor := some SpeedMeasurement.normal,
  temperature := some Temperature.highFever,
  fracture := some false,
  headInjury := some false,
  acuateAbdominalPain := some false,
  whitePalm := some false,
  poison := some false,
  agony := some false,
  urgentReferral := some false,
  wasting := some false,
  oedema := some [],
  burn := some false
}

theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Priority := by
  native_decide