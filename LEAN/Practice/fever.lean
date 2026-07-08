structure Patient where
  age: Nat
  temp: Nat

structure Environment where
  temp: Nat

def feverThreshold (p : Patient) (env : Environment) : Nat :=
  if env.temp > 100 then
    if p.age >= 10 then
      105
    else
      100
  else
    if p.age >= 10 then
      100
    else
      95

def HasFever (p : Patient) (env:Environment) : Prop :=
  p.temp > feverThreshold p env


def LLMPlan (p : Patient) : Prop :=
  if p.age > 10 then
    p.temp > 100
  else
    p.temp > 95

theorem llm_correct :
  ∀ pat env, LLMPlan pat ↔ HasFever pat env := by
  sorry
  -- if you were to attempt to prove this, we would intro h
  -- intro h creates a new hypothesis and h is the assumption that LLM says patient has a fever
  -- h: LLMPlan pat
  -- |- HasFever pat env



-- define theoreom llm_wrong
theorem llm_wrong:
  -- there exists a patient where the two plans disagree (negation of the llm plan being equal to ground truth)
  ∃ pat env,
    (LLMPlan pat ∧ ¬ HasFever pat env)
    ∨
    (HasFever pat env ∧ ¬ LLMPlan pat) := by -- := by is indicating that tactics are going to be used to prove this theorem
  -- the proof begins here
  -- this line is providing the counter example in a tuple format
      -- patient age is 11, patient temp is 102, and outside temp is 101
  refine ⟨{ age := 11, temp := 102 }, { temp := 101 }, ?_⟩ -- ?_ means leave a hole here, Lean creates a new goal
  -- choosing to prove the left side of the theorem (LLM says fever and truth says no)
  left
  --splitting the conjuction into llm saying fever v actual truth saying no fever
  constructor -- creates two goals
  · unfold LLMPlan -- replaces LLMPlan with its definition (if 11 > 10 then 102 > 100 else 102 > 95)
    simp -- simplifies the goal to true
  · unfold HasFever feverThreshold -- same thing (if 11 > 10 then 102 > 105 else 102 > 100)
    simp -- simplifies the goal to false
  -- one true and one false so goal is accomplished
