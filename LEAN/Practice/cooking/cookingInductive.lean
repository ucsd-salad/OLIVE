/-- this approach is inductive predicate since the rules are defined inductively
and sorted into Propositions, the plans themselves are then propositions of the type IsValidPlan -/

-- inductive defined a new datatype, list of possible actions
inductive Action where
  | washHand
  | cook
  | eat
deriving DecidableEq, Repr -- decidableEq is a typeclass, allows for equality computation, Repr allows for printing of the values

-- abbrev is a type alias, Plan is a list of actions
abbrev Plan := List Action

/--
`IsValidPlan p` holds when `p` can be build up one action at a time,
where each constructor is a rule for what's allowed to come next:
  • `nil`      — the empty plan is always valid
  • `washHand` — you can always add a wash to any valid plan
  • `cook`     — you can add a cook if a valid plan contains `washHand` somewhere
  • `eat`      — you can add an eat if a valid plan contains `cook` somewhere
A plan is valid exactly when there's a derivation (chain of these
rules) that produces it.
IsValidPlan is datatype that takes a Plan and returns a Prop (true/false)
-/
inductive IsValidPlan : Plan → Prop where
  | nil :
      IsValidPlan []
  | washHand {p : Plan} : -- {} mean argument is implicit
      IsValidPlan p →
      IsValidPlan (p ++ [Action.washHand])
  | cook {p : Plan} :
      IsValidPlan p →
      Action.washHand ∈ p →
      IsValidPlan (p ++ [Action.cook])
  | eat {p : Plan} :
      IsValidPlan p →
      Action.cook ∈ p →
      IsValidPlan (p ++ [Action.eat])

-- A hand-built derivation showing [washHand, cook, eat] is valid.
-- This is literally "applying the rules" to produce the plan.
example : IsValidPlan [Action.washHand, Action.cook, Action.eat] :=
  .eat (.cook (.washHand .nil) (by simp)) (by simp) -- by simp proves the membership goals
  -- ex: washHand is in [washHand] is obv and proven by simp

-- The same proof, written step by step instead of nested:
example : IsValidPlan [Action.washHand, Action.cook, Action.eat] := by
  have h0 : IsValidPlan [] := .nil --creates first proof
  have h1 : IsValidPlan [Action.washHand] := .washHand h0 --usees the WashHand rule
  have h2 : IsValidPlan [Action.washHand, Action.cook] := .cook h1 (by simp) -- uses Cook rule
  have h3 : IsValidPlan [Action.washHand, Action.cook, Action.eat] := .eat h2 (by simp) -- uses Eat rule
  exact h3-- return the proof


/-- proving the negation means an implication on false, P -> False
therefore, -/
example : ¬(IsValidPlan [Action.cook]) := by
  intro h -- assumes h: IsValidPlan [cook] is true
  generalize h' : [Action.cook] = g at h -- replaces [Action.cook] inside h with g
  cases h with -- divides goals into the 4 possible cases (from the constructors of IsValidPlan)

  | nil => grind -- if the proof ended with nil, g=[] but from h', g = [cook], so contradiction, grind solves automatically
  -- OR | nil => simp at h'

  | washHand a => -- supposing washHand was used last, then g = p ++ [washHand]
    rename_i p -- renames the implicit variable so it can be used
    cases p with -- split into 2 cases, p is empty and not
    | nil => simp at h' -- if p is empty, then g = [washHand] but from h', g = [cook], so contradiction
    | cons first rest => simp at h' -- if p is not empty, then g has at least 2 elements and ends in washHand but from h', g = [cook], so contradiction

  | cook prev wash => -- supposing cook was used last, we need proof that earlier plan was valid (prev) and earlier plan contains washHand (wash)
    rename_i p
    cases p with -- split on previous plan
    | nil => -- if empty before, then now [cook] which is good so far
      simp at h' -- we need to prove that [cook] contains washHand
      simp at wash -- derives the contradiction
    | cons first rest => simp at h' -- if prev plan not empty, g has at least two elements, but contradiction

  | eat prev cook => -- supposing eat was used last
    rename_i p
    cases p with -- split on previous plan
    | nil => simp at h' -- if empty before, p = [], end up with [eat] but from h', g = [cook], so contradiction
    | cons first rest => simp at h' -- if prev plan not empty, p = first :: rest g has at least two elements, but contradiction
    -- first : the first action (the head), rest: list of the rest of the actions (the tail)
    -- g = (first :: rest) + [Action.eat]
    -- h' becomes (first :: rest) + [Action.eat] = [Action.cook] which is false
    -- simp at h' unfolds list append --> first :: (rest ++ [Action.eat]) = [Action.cook]
