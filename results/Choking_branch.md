# Choking Results

## Prompt #1

Prompt: "A baby is choking and cannot breathe properly and they're not awake, what do i do?"

### Pipeline Output
From Generated Plan predicate:
```
pred GeneratedPlan {
    ReferenceConstraints
    some s: State |
        s.person = Infant
        and s.airway = Complete
        and s.consciousness = Unconscious
        and s.ability = CannotCoughOrTalk
        and s.emergencyCalled = True
        and s.cprDone = True
        and s.encourageCoughingDone = False
        and s.backBlowsDone = False
        and s.chestThrustsDone = False
        and s.abdominalThrustsDone = False
}
```
+ Recognizes that the person is an infant
+ Knows that they're unconcious and that their airway is completely blocked, meaning they cannot cough or talk
+ Knows that this means that CPR and emergency needs to be called
### Chat-GPT Output
