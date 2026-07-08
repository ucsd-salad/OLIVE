import Tutorial.Lean.moduleOneRevised

-- The answer is: below 2 months of age, a child is always a priority.
-- This comes from the Priority function's first condition: optionLt p.ageInMonth 2

def examplePatientWasting : Patient :=
{
  ageInMonth := some 1
  oedema := some []
}

-- A cleaner theorem: below 2 months, Priority assessment is always true
theorem ValidPlanClean :
  ∀ (p : Patient), ∀ (n : Nat), p.ageInMonth = some n → n < 2 →
    Priority p = some true := by
  intro p n hAge hLt
  unfold Priority
  have hOptLt : optionLt p.ageInMonth 2 = some true := by
    unfold optionLt; rw [hAge]; simp; exact hLt
  unfold optionOrList
  simp [hOptLt]