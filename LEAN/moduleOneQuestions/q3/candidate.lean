import Tutorial.Lean.moduleOneRevised

def examplePatient : Patient :=
{
  ageInMonth := some 12,          -- one year old = 12 months
  breathing := some true,          -- still breathing (wet and noisy, but breathing)
  airwayObstructed := some true,   -- wet noisy breathing with drooling suggests obstruction
  centralCyanosis := some true,    -- looking blue
  smiling := some false,
  crying := some false,
  severeChestIndrawing := none,
  accessoryMuscleUseBreating := none,
  unableToTalkEatFeed := none,
  veryFastBreathing := none,
  breatingIsTiring := none,
  capillaryRefill := none,
  pulse := none,
  avpu := some AVPU.Unresponsive,  -- became unconscious
  sunkenEyes := none,
  skinTurgor := none,
  temperature := none,
  fracture := none,
  headInjury := none,
  acuateAbdominalPain := none,
  whitePalm := none,
  poison := none,
  agony := none,
  urgentReferral := none,
  wasting := none,
  oedema := none,
  burn := none,
}

theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Emergency := by
  -- Central cyanosis is true, so Airway returns some true,
  -- which makes Emergency return some true,
  -- which makes TriageAssessment return Triage.Emergency
  native_decide