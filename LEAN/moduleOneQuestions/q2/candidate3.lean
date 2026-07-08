import Tutorial.Lean.moduleOneRevised

def examplePatient : Patient :=
{
  ageInMonth := some 48,               -- 4 years old = 48 months
  breathing := some true,              -- breathing
  airwayObstructed := some false,      -- no airway obstruction mentioned
  centralCyanosis := some false,       -- no cyanosis
  smiling := some false,               -- not specified
  crying := some false,                -- not specified
  severeChestIndrawing := some false,  -- no respiratory distress
  accessoryMuscleUseBreating := some false, -- no respiratory distress
  unableToTalkEatFeed := some false,   -- responds to questions
  veryFastBreathing := some false,     -- breathing fast but not "very fast breathing" in distress sense
  breatingIsTiring := some false,      -- no respiratory distress
  capillaryRefill := some 2,           -- normal (no circulation issues mentioned)
  pulse := some Pulse.normal,          -- no abnormal pulse mentioned
  avpu := some AVPU.Alert,             -- responds quickly to questions
  sunkenEyes := some false,            -- no dehydration signs
  skinTurgor := some SpeedMeasurement.normal, -- no dehydration
  temperature := some Temperature.highFever,  -- feels very hot
  fracture := some false,              -- no other major symptom
  headInjury := some false,            -- no other major symptom
  acuateAbdominalPain := some false,   -- no other major symptom
  whitePalm := some false,             -- no other major symptom
  poison := some false,                -- no other major symptom
  agony := some false,                 -- no other major symptom
  urgentReferral := some false,        -- no other major symptom
  wasting := some false,               -- no other major symptom
  oedema := some [],                   -- no oedema
  burn := some false                   -- no other major symptom
}

theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Priority := by
  native_decide