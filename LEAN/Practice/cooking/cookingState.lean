-- possible actions
inductive Action where
  | washHand
  | cook
  | eat
deriving DecidableEq, Repr

/-- the following is an ecoding of the rule:
  1) wash hands before cooking
  2) cook before eating
  3) wash hands whenever

-- -- name shortcut
-- abbrev Plan := List Action

-- -- rules for each action
-- structure Rule where
--   conclusion : Action
--   applicable : Plan → Bool

-- def washRule : Rule :=
-- {
--   conclusion := Action.washHand,
--   applicable := fun _ => true
-- }

-- def cookRule : Rule :=
-- {
--   conclusion := Action.cook,
--   applicable := fun plan =>
--     List.contains (plan.dropLast) Action.washHand
-- }

-- def eatRule : Rule :=
-- {
--   conclusion := Action.eat,
--   applicable := fun plan =>
--     List.contains (plan.dropLast) Action.washHand
-- }

-- -- list of all possible rules
-- def rules : List Rule :=
--   [washRule, cookRule, eatRule]


-- -- define when a rule can be applied
-- def applicableRules (prefix : Plan) (last : Action) : List Rule :=
--   rules.filter (fun r =>
--     r.conclusion = last ∧ r.applicable prefix
--   )

-- end safeCooking

-- A plan is valid if it can be built from left to right
-- where every action is justified by a rule whose preconditions hold.

-- -- validate any plan based on the constraints
-- validate(plan):

--     if empty
--         success

--     prefix,last := split(plan)

--     candidates := rules producing last

--     if no candidate succeeds
--         failure

--     recurse(prefix)
-/

-- This implementaiton focuses on figuring out which actions are
-- allowed based on the past actions.

abbrev Plan := List Action

inductive State where
  | dirty
  | washed
  | cooked
deriving DecidableEq, Repr

inductive Step : State → Action → State → Prop where
  | wash :
      Step State.dirty Action.washHand State.washed

  | cook :
      Step State.washed Action.cook State.cooked

  | eat :
      Step State.cooked Action.eat State.cooked

/--
start in s, run plan p, get to s'.
if you take one legal action, and the rest of the actions are legal, the
whole plan is legal
-/
inductive Exec : State → Plan → State → Prop where
  --start with s, do nothing, end in s --> always true
  | nil {state} :
      Exec state [] state

  -- to prove the following is true
  | cons {state action state' actions state''} :
      -- prove action a is legal
      Step state action state' →
      -- the remaining actions as take you from s' to s"
      Exec state' actions state'' →
      Exec state (action :: actions) state''

def ValidPlan (p : Plan) : Prop :=
  Exec State.dirty p State.cooked


example : ValidPlan [
  Action.washHand,
  Action.cook,
  Action.eat
] := by
  unfold ValidPlan
  apply Exec.cons
  · constructor   -- Step.dirty → washHand → washed
  · apply Exec.cons
    · constructor -- Step.washed → cook → cooked
    · apply Exec.cons
      · constructor -- Step.cooked → eat → cooked
      · constructor
