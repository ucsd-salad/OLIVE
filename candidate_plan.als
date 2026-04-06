```alloy
module reference

-- ----------------- SYMPTOMS -----------------

abstract sig Symptom {}

one sig VertebralPain extends Symptom {}
one sig SensoryChange extends Symptom {}
one sig WeaknessOrParalysis extends Symptom {}

-- ----------------STATE------------------------
abstract sig PatState {}

one sig SpineInjurySuspected extends PatState {}
one sig NoSpineInjury extends PatState {}

abstract sig MovementState extends PatState {}
one sig CanMoveSpine extends MovementState {}
one sig CannotMoveSpine extends MovementState {}

sig PatientStatus {
    states: set PatState
}

-- was fact -> now predicate
pred MovementStateConsistency {
    all p: PatientStatus |
        SpineInjurySuspected in p.states implies