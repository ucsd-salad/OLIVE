import Tutorial.Lean.moduleOneRevised

-- The signs of malnutrition checked during triage are:
-- 1. Visible severe wasting (marasmus) - captured by `wasting`
-- 2. Oedema of both feet (kwashiorkor) - captured by `oedema` containing `BodyPart.feet`

-- Example patient showing wasting (marasmus) with all fields provided
def examplePatientWasting : Patient :=
{
  ageInMonth := some 24
  breathing := some true
  airwayObstructed := some false
  centralCyanosis := some false
  severeChestIndrawing := some false
  accessoryMuscleUseBreating := some false
  unableToTalkEatFeed := some false
  veryFastBreathing := some false
  breatingIsTiring := some false
  capillaryRefill := some 2
  pulse := some Pulse.normal
  avpu := some AVPU.Alert
  sunkenEyes := some false
  skinTurgor := some SpeedMeasurement.normal
  temperature := some Temperature.normal
  fracture := some false
  headInjury := some false
  acuateAbdominalPain := some false
  whitePalm := some false
  poison := some false
  agony := some false
  urgentReferral := some false
  wasting := some true
  oedema := some []
  burn := some false
}

-- Example patient showing oedema of feet (kwashiorkor) - partial info
def examplePatientOedema : Patient :=
{
  oedema := some [BodyPart.feet]
}

-- A patient with no malnutrition signs and no other priority/emergency signs goes to Queue
def examplePatientNoMalnutrition : Patient :=
{
  ageInMonth := some 24
  breathing := some true
  airwayObstructed := some false
  centralCyanosis := some false
  smiling := some true
  crying := some false
  severeChestIndrawing := some false
  accessoryMuscleUseBreating := some false
  unableToTalkEatFeed := some false
  veryFastBreathing := some false
  breatingIsTiring := some false
  capillaryRefill := some 2
  pulse := some Pulse.normal
  avpu := some AVPU.Alert
  sunkenEyes := some false
  skinTurgor := some SpeedMeasurement.normal
  temperature := some Temperature.normal
  fracture := some false
  headInjury := some false
  acuateAbdominalPain := some false
  whitePalm := some false
  poison := some false
  agony := some false
  urgentReferral := some false
  wasting := some false
  oedema := some []
  burn := some false
}

-- Wasting triggers Priority triage (sign of malnutrition - marasmus)
theorem ValidPlan :
  TriageAssessment examplePatientWasting = Triage.Priority := by native_decide

-- Oedema of feet with partial info triggers askForInfo
theorem oedemaFeetIsPriority :
  TriageAssessment examplePatientOedema = Triage.askForInfo := by native_decide

-- When oedema info is fully known along with other fields, oedema of feet gives Priority
def examplePatientOedemaFull : Patient :=
{
  ageInMonth := some 24
  breathing := some true
  airwayObstructed := some false
  centralCyanosis := some false
  severeChestIndrawing := some false
  accessoryMuscleUseBreating := some false
  unableToTalkEatFeed := some false
  veryFastBreathing := some false
  breatingIsTiring := some false
  capillaryRefill := some 2
  pulse := some Pulse.normal
  avpu := some AVPU.Alert
  sunkenEyes := some false
  skinTurgor := some SpeedMeasurement.normal
  temperature := some Temperature.normal
  fracture := some false
  headInjury := some false
  acuateAbdominalPain := some false
  whitePalm := some false
  poison := some false
  agony := some false
  urgentReferral := some false
  wasting := some false
  oedema := some [BodyPart.feet]
  burn := some false
}

theorem oedemaFeetFullPriority :
  TriageAssessment examplePatientOedemaFull = Triage.Priority := by native_decide

-- Without malnutrition signs (and no other issues), patient goes to Queue
theorem noMalnutritionQueue :
  TriageAssessment examplePatientNoMalnutrition = Triage.Queue := by native_decide