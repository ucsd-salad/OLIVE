import Tutorial.Lean.moduleOneRevised

def examplePatient : Patient :=
{
  ageInMonth := some 48,                        -- 4 years = 48 months
  breathing := some true,                        -- he is breathing (breathing fast)
  centralCyanosis := some false,                 -- no cyanosis
  severeChestIndrawing := some false,            -- no respiratory distress
  accessoryMuscleUseBreating := some false,      -- no respiratory distress
  unableToTalkEatFeed := some false,             -- responds quickly to questions, no respiratory distress
  veryFastBreathing := some true,                -- breathing fast
  breatingIsTiring := some false,                -- no respiratory distress
  temperature := some Temperature.highFever,     -- feels very hot
  avpu := some AVPU.Alert,                       -- responds quickly to questions
  oedema := none,                                -- not mentioned
}

-- Since Emergency returns none (missing circulation/dehydration info), triage is askForInfo
theorem ValidPlan :
  TriageAssessment examplePatient = Triage.askForInfo := by
  native_decide