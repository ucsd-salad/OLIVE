-- possible actions
inductive Action where
  | washHand
  | cook
  | eat
deriving DecidableEq, Repr

abbrev Plan := List Action

/--
Fold over the plan left-to-right, tracking two flags:
  `washed` — has a `washHand` happened so far?
  `cooked` — has a `cook` happened so far?
A `cook` is only allowed once `washed = true`.
An `eat` is only allowed once `cooked = true`.
`washHand` is always allowed and sets `washed := true`.
-/
def isValidAux : List Action → Bool → Bool → Bool
  | [],                   _,      _      => true
  | Action.washHand :: t, _,      cooked => isValidAux t true cooked
  | Action.cook :: t,     washed, _ => washed && isValidAux t washed true
  | Action.eat :: t,      washed, cooked => cooked && isValidAux t washed cooked

/-- Top-level check: is this an arbitrary `Plan` allowed by the constraints? -/
def isValid (plan : Plan) : Bool :=
  isValidAux plan false false

-- ── sanity checks ──────────────────────────────────────────────
#eval isValid [Action.washHand, Action.cook, Action.eat]                                  -- true
#eval isValid [Action.cook, Action.eat]                                                   -- false, no wash before cook
#eval isValid [Action.washHand, Action.eat]                                               -- false, no cook before eat
#eval isValid [Action.eat]                                                                -- false
#eval isValid ([] : Plan)                                                                 -- true, empty plan is fine
#eval isValid [Action.washHand, Action.cook, Action.washHand, Action.cook, Action.eat]     -- true, repeats are fine
#eval isValid [Action.washHand, Action.cook, Action.eat, Action.eat]                       -- true, can eat twice after one cook
#eval isValid [Action.eat, Action.washHand, Action.cook]                                   -- false, eat came first
