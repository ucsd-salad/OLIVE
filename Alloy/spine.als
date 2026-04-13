module reference
// Action definitions

abstract sig Action {}

// Main flow actions
one sig AssessInjury_LAF extends Action {}      // Look, Ask, Feel
one sig CheckCSM extends Action {}
one sig TractionInLine extends Action {}       // optional if CSM compromised
one sig Splint extends Action {}
one sig OpenFractureCare extends Action {}     // only if fracture open
one sig ManagePain extends Action {}
one sig Evacuate extends Action {}             

// CSM sub-actions for checking during traction/splint
abstract sig CSM_Step extends Action {}
one sig CirculatoryCheck extends CSM_Step {}
one sig SensationCheck extends CSM_Step {}
one sig MotorCheck extends CSM_Step {}
one sig StrokeGripCheck extends CSM_Step {}

//  state model

sig State {
    action: one Action,
    nextState: lone State
}

// main flow

fact MainFlow {
    all s: State | some s.nextState implies {
        // 1. after evaluation, do CSM
        s.action = AssessInjury_LAF implies s.nextState.action = CheckCSM

        // 2. after CSM，either TIL or Splint
        s.action = CheckCSM implies s.nextState.action in (TractionInLine + Splint)

        // 3.must splint after TIL
        s.action = TractionInLine implies s.nextState.action = Splint

        // 4. branches after Splint
        s.action = Splint implies s.nextState.action in (CheckCSM + OpenFractureCare + ManagePain)

        // 5. manage fracture care after splint
        s.action = OpenFractureCare implies s.nextState.action = ManagePain

        // 6. evacuate
        s.action = ManagePain implies s.nextState.action = Evacuate
    }
}

fact EvacuationIsFinal {
    all s: State | s.action = Evacuate implies no s.nextState
}


fact NoCycles {
    no s: State | s in s.^nextState
}

// Execution

run {} for 20 State, 10 Action
