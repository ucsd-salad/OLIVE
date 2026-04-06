```alloy
module reference

-- ----------------- SYMPTOMS -----------------

abstract sig Symptom {}

one sig VertebralPain extends Symptom {}
one sig SensoryChange extends Symptom {}
one sig WeaknessOrParalysis extends Symptom {}

----------------STATE------------------------
abstract sig PatState {}

one sig SpineInjurySuspected extends PatState {}
one sig NoSpineInjury extends PatState {}

abstract sig MovementState extends PatState {}
one sig CanMoveSpine extends MovementState {}
one sig CannotMoveSpine extends MovementState {}

-- was fact → now predicate
pred MovementStateConsistency {
    all p: PatientStatus |
        SpineInjurySuspected in p.states implies
            lone (p.states & MovementState)
}

----------------- ACTION DEFS -----------------

abstract sig Action {}
one sig ProtectHeadAndSpine extends Action {}
one sig CheckCSM_Initial extends Action {}
one sig BeamLiftOrLogRoll extends Action {}
one sig MaintainHeadStabilization extends Action {}
one sig CheckCSM_Recheck extends Action {}
one sig Evacuate extends Action {}
one sig Immobilize extends Action {}
one sig AskForInfo extends Action {}
one sig AskForSymptoms extends Action {}

-- CSM sub-actions
abstract sig CSM_Step extends Action {}
one sig CirculatoryCheck extends CSM_Step {}
one sig SensationCheck extends CSM_Step {}
one sig MotorCheck extends CSM_Step {}
one sig StrokeGripCheck extends CSM_Step {}

-- ----------------- DEPENDENCIES -----------------

sig Dependency {
    state: one Action,
    requires: set Action
}

-- was fact → now predicate
pred Dependencies {
    some d: Dependency | d.state = ProtectHeadAndSpine
    some d: Dependency | d.state = CheckCSM_Initial and d.requires = ProtectHeadAndSpine
    some d: Dependency | d.state = CirculatoryCheck and d.requires = CheckCSM_Initial
    some d: Dependency | d.state = SensationCheck and d.requires = CirculatoryCheck
    some d: Dependency | d.state = MotorCheck and d.requires = SensationCheck
    some d: Dependency | d.state = StrokeGripCheck and d.requires = MotorCheck
    some d: Dependency | d.state = BeamLiftOrLogRoll and d.requires = StrokeGripCheck + CirculatoryCheck + SensationCheck
    some d: Dependency | d.state = MaintainHeadStabilization and d.requires = BeamLiftOrLogRoll
    some d: Dependency | d.state = CheckCSM_Recheck and d.requires = MaintainHeadStabilization
    some d: Dependency | d.state = Evacuate and d.requires = StrokeGripCheck + CheckCSM_Recheck
}

-- ----------------- PATIENT STATUS -----------------
sig PatientStatus {
    done: set Action,
    symptoms: set Symptom,
    states: set PatState
}

one sig P extends PatientStatus {}

-- was fact → now predicate
pred NoContradictoryStates {
    all p: PatientStatus |
        not (SpineInjurySuspected in p.states and NoSpineInjury in p.states)
}

-- ----------------- NEXT ACTION PREDICATE -----------------

pred NextActionToDo[a: Action] {

    ( no P.symptoms
      and a = AskForSymptoms
      and a not in P.done
    )

    or

    ( some P.symptoms
      and no (P.states & MovementState)
      and a = AskForInfo
      and a not in P.done
    )

    or

    ( some P.symptoms
      and CannotMoveSpine in P.states
      and a = Immobilize
      and a not in P.done
    )

    or

    ( some P.symptoms
      and CanMoveSpine in P.states