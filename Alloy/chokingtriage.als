module checking 

-- ----------------- TIME -----------------

abstract sig Time {
    next: lone Time
}

one sig T1, T2, T3, T4 extends Time {}

-- ----------------- BOOLEAN VALUES -----------------

abstract sig Bool {}
one sig True, False extends Bool {}

-- ----------------- PERSON -----------------

abstract sig Person {}
one sig Infant, NonInfant extends Person {}

-- ----------------- AIRWAY -----------------

abstract sig Airway {}
one sig Partial, Complete extends Airway {}

-- ----------------- CONSCIOUSNESS -----------------

abstract sig Consciousness {}
one sig Conscious, Unconscious extends Consciousness {}

-- ----------------- ABILITY -----------------

abstract sig Ability {}
one sig CanCoughOrTalk, CannotCoughOrTalk extends Ability {}

-- ----------------- ACTIONS -----------------

abstract sig Action {}

one sig
    EncourageCoughing,
    BackBlows,
    AbdominalThrusts,
    ChestThrusts,
    CPR,
    CallEmergency
extends Action {}

-- ----------------- STATE -----------------

sig State {
    time: one Time,

    person: one Person,
    airway: one Airway,
    consciousness: one Consciousness,
    ability: one Ability,

    encourageCoughingDone: one Bool,
    backBlowsDone: one Bool,
    chestThrustsDone: one Bool,
    abdominalThrustsDone: one Bool,
    cprDone: one Bool,
    emergencyCalled: one Bool
}

one sig S1, S2, S3, S4 extends State {}

-- ----------------- DEPENDENCIES -----------------

sig Dependency {
    state: one Action,
    requires: set Action
}

pred Dependencies {

    some d: Dependency |
        d.state = BackBlows

    some d: Dependency |
        d.state = ChestThrusts
        and d.requires = BackBlows

    some d: Dependency |
        d.state = CPR
        and d.requires = CallEmergency
}

-- ----------------- PATIENT STATUS -----------------

sig PatientStatus {
    done: set Action,
    currentState: lone State
}

one sig P extends PatientStatus {}

-- ----------------- REFERENCE CONSTRAINTS -----------------

pred ReferenceConstraints {

    Dependencies

    all s: State | {

        // CASE 1

        (s.airway = Partial and
         s.ability = CanCoughOrTalk) implies {

            s.encourageCoughingDone = True

            s.backBlowsDone = False
            s.abdominalThrustsDone = False
            s.chestThrustsDone = False
            s.cprDone = False
        }

        // CASE 2

        (s.airway = Complete and
         s.consciousness = Conscious and
         s.person = Infant) implies {

            s.backBlowsDone = True
            s.chestThrustsDone = True
            s.abdominalThrustsDone = False
        }

        // CASE 3

        (s.airway = Complete and
         s.consciousness = Conscious and
         s.person = NonInfant) implies {

            s.backBlowsDone = True
            s.abdominalThrustsDone = True
        }

        // CASE 4

        (s.consciousness = Unconscious) implies {

            s.cprDone = True
        }

        // CASE 5

        (s.airway = Complete) implies {

            s.emergencyCalled = True
        }
    }
}

pred GeneratedPlan {

}

run {
    GeneratedPlan and not ReferenceConstraints
} for 10 State, 10 Action, 10 Dependency, 1 PatientStatus
