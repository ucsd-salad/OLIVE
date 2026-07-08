import Tutorial.Lean.moduleOneRevised

-- A two-year-old male is rushed to the clinic acutely convulsing.
-- Two years old = 24 months.
-- "Acutely convulsing" means the child is actively having a seizure.
-- A convulsing child is not alert - they are at best responsive to pain or unresponsive.
-- Per the ABCD triage system, a child who is only responsive to pain or unresponsive
-- falls under CirculationComaConulsion (C in ABCD), which triggers Emergency triage.
-- Convulsions indicate coma/altered consciousness, so AVPU would be Pain or Unresponsive.
-- We'll set AVPU to Pain (actively convulsing = responsive to pain at best).
-- This triggers Emergency triage.

def examplePatient : Patient :=
{
  ageInMonth := some 24
  avpu := some AVPU.Pain
  oedema := none
}

theorem ValidPlan :
  TriageAssessment examplePatient = Triage.Emergency := by
  native_decide