module generated
open reference

pred GeneratedPlan {

    -- We have asked for symptoms and called 911
    P.done = AskForSymptoms

    -- Symptoms consistent with possible spine injury
    P.symptoms = VertebralPain

    -- Movement state still unknown
    P.states = none

    -- Next step from the original plan: Do NOT move the person.
    -- Closest matching Action in the reference model: ProtectHeadAndSpine
    some a: Action | NextActionToDo[a] and a = AskForInfo
}