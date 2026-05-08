module checking

-- ----------------- TIME -----------------

abstract sig Time {
  next: lone Time
}

one sig T1, T2, T3, T4, T5, T6 extends Time {}

-- ----------------- PERSONS -----------------

abstract sig Person {}
one sig R extends Responder {}
one sig V extends Victim {}

abstract sig Responder extends Person {}
abstract sig Victim extends Person {}

-- ----------------- EQUIPMENT -----------------

abstract sig Equipment {}

abstract sig PPE extends Equipment {}
abstract sig AED extends Equipment {}
abstract sig BarrierDevice extends Equipment {}

one sig PPE1 extends PPE {}
one sig AED1 extends AED {}
one sig BarrierDevice1 extends BarrierDevice {}

-- ----------------- ENVIRONMENT -----------------

abstract sig Environment {}
one sig Safe, Unsafe extends Environment {}

-- ----------------- BOOLEAN VALUES -----------------

abstract sig Bool {}
one sig True, False extends Bool {}

-- ----------------- ASSESSMENT RESULTS -----------------

abstract sig VictimCondition {}
one sig Responsive, Unresponsive extends VictimCondition {}

abstract sig BreathingStatus {}
one sig NormalBreathing, NotBreathing, AbnormalBreathing extends BreathingStatus {}

abstract sig BleedingStatus {}
one sig NoBleeding, MinorBleeding, SevereBleeding extends BleedingStatus {}

-- ----------------- SURFACE TYPES -----------------

abstract sig Surface {}
one sig FirmFlat, NotFirmFlat extends Surface {}

-- ----------------- BODY POSITION -----------------

abstract sig BodyPosition {}
one sig FaceUp, NotFaceUp extends BodyPosition {}

-- ----------------- AIRWAY STATUS -----------------

abstract sig AirwayStatus {}
one sig Open, Closed, PartiallyOpen extends AirwayStatus {}

-- ----------------- CHEST RISE -----------------

abstract sig ChestRise {}
one sig Rising, NotRising extends ChestRise {}

-- ----------------- ACTION DEFS -----------------

abstract sig Action {}

one sig CheckScene extends Action {}
one sig UsePPE extends Action {}
one sig AssessVictim extends Action {}
one sig CallEmergency extends Action {}
one sig RequestAED extends Action {}
one sig PositionVictim extends Action {}
one sig StartCompressions extends Action {}
one sig OpenAirway extends Action {}
one sig GiveRescueBreaths extends Action {}
one sig ApplyAED extends Action {}

-- ----------------- DEPENDENCIES -----------------

sig Dependency {
    state: one Action,
    requires: set Action
}

pred Dependencies {
    some d: Dependency | d.state = CheckScene
    some d: Dependency | d.state = UsePPE and d.requires = CheckScene
    some d: Dependency | d.state = AssessVictim and d.requires = CheckScene + UsePPE
    some d: Dependency | d.state = CallEmergency and d.requires = AssessVictim
    some d: Dependency | d.state = RequestAED and d.requires = CallEmergency
    some d: Dependency | d.state = PositionVictim and d.requires = CallEmergency + RequestAED
    some d: Dependency | d.state = StartCompressions and d.requires = PositionVictim
    some d: Dependency | d.state = OpenAirway and d.requires = StartCompressions
    some d: Dependency | d.state = GiveRescueBreaths and d.requires = OpenAirway
    some d: Dependency | d.state = ApplyAED and d.requires = RequestAED
}

-- ----------------- STATE -----------------

abstract sig State {
  time: one Time,
  
  environment: one Environment,
  ppeAvailable: one Bool,
  ppeUsed: one Bool,
  
  victimCondition: one VictimCondition,
  victimBreathing: one BreathingStatus,
  victimBleeding: one BleedingStatus,
  
  surface: lone Surface,
  bodyPosition: lone BodyPosition,
  responderKneeling: one Bool,
  
  sceneChecked: one Bool,
  victimAssessed: one Bool,
  emergencyCalled: one Bool,
  aedRequested: one Bool,
  victimPositioned: one Bool,
  
  compressionsStarted: one Bool,
  compressionCount: lone Int,
  rescueBreathsGiven: one Bool,
  breathCount: lone Int,
  
  handPosition: one Bool,
  shouldersOverHands: one Bool,
  elbowsStraight: one Bool,
  compressionRate: lone Int,
  compressionDepth: lone Int,
  chestRecoil: one Bool,
  
  airwayStatus: lone AirwayStatus,
  headTilted: one Bool,
  chinLifted: one Bool,
  nosePinched: one Bool,
  mouthSealed: one Bool,
  breathDuration: lone Int,
  chestRise: lone ChestRise,
  
  aedApplied: one Bool,
  
  interruptionTime: one Int,
  cycleCount: lone Int
}

one sig S1, S2, S3, S4, S5, S6 extends State {}

-- ----------------- PATIENT STATUS -----------------

sig PatientStatus {
    done: set Action,
    currentState: lone State
}

one sig P extends PatientStatus {}

-- ----------------- ORIGINAL FACTS AS PREDICATES -----------------

pred TimeStructure {
  all t: Time | lone t.~next
  no t: Time | t in t.^next

  T1.next = T2
  T2.next = T3
  T3.next = T4
  T4.next = T5
  T5.next = T6
  no T6.next
}

pred StateTimeMapping {
  S1.time = T1
  S2.time = T2
  S3.time = T3
  S4.time = T4
  S5.time = T5
  S6.time = T6
}

pred IntegerDefaults {
  all s: State | {
    s.compressionsStarted = False implies no s.compressionCount

    s.rescueBreathsGiven = False implies no s.breathCount

    s.compressionsStarted = False implies {
      no s.compressionRate
      no s.compressionDepth
    }

    s.rescueBreathsGiven = False implies no s.breathDuration

    s.victimPositioned = False implies {
      no s.surface
      no s.bodyPosition
    }

    s.rescueBreathsGiven = False implies no s.airwayStatus
    s.rescueBreathsGiven = False implies no s.chestRise
  }
}

pred NeverProceedIfUnsafe {
  all s: State | 
    s.environment = Unsafe implies {
      s.victimAssessed = False
      s.compressionsStarted = False
      s.victimPositioned = False
      s.rescueBreathsGiven = False
    }
}

pred ProtocolOrder {
  all s, snext: State | snext.time = s.time.next implies {
    s.sceneChecked = True implies snext.sceneChecked = True
    s.victimAssessed = True implies snext.victimAssessed = True
    s.emergencyCalled = True implies snext.emergencyCalled = True

    snext.rescueBreathsGiven = True implies s.compressionsStarted = True
    
    snext.victimAssessed = True implies s.sceneChecked = True
    snext.emergencyCalled = True implies s.victimAssessed = True
    snext.victimPositioned = True implies s.emergencyCalled = True
    snext.compressionsStarted = True implies s.victimPositioned = True
  }
}

pred CPRRequiresPrerequisites {
  all s: State | s.compressionsStarted = True implies {
    s.sceneChecked = True
    s.environment = Safe
    s.victimAssessed = True
    s.emergencyCalled = True
    s.victimPositioned = True
  }
}

pred BreathsRequireCompressions {
  all s: State | s.rescueBreathsGiven = True implies {
    s.compressionsStarted = True
  }
}

-- ----------------- NEXT ACTION PREDICATE -----------------

pred NextActionToDo[a: Action] {
    a not in P.done
    and some d: Dependency |
        d.state = a
        and d.requires in P.done
}

one sig NextSteps {
    actions: set Action
}

-- ----------------- VALID RESCUE SCENARIO -----------------

pred validRescueScenario {
  S2.time = S1.time.next
  S3.time = S2.time.next
  S4.time = S3.time.next
  S5.time = S4.time.next
  S6.time = S5.time.next
  
  S1.sceneChecked = True
  S1.environment = Safe
  S1.victimAssessed = False
  S1.emergencyCalled = False
  S1.victimPositioned = False
  S1.compressionsStarted = False
  S1.rescueBreathsGiven = False
  
  S2.sceneChecked = True
  S2.victimAssessed = True
  S2.victimCondition = Unresponsive
  S2.victimBreathing = NotBreathing
  S2.victimBleeding = NoBleeding
  S2.emergencyCalled = False
  S2.victimPositioned = False
  S2.compressionsStarted = False
  
  S3.sceneChecked = True
  S3.victimAssessed = True
  S3.emergencyCalled = True
  S3.aedRequested = True
  S3.victimPositioned = False
  S3.compressionsStarted = False
  
  S4.sceneChecked = True
  S4.victimAssessed = True
  S4.emergencyCalled = True
  S4.victimPositioned = True
  S4.responderKneeling = True
  S4.surface = FirmFlat
  S4.bodyPosition = FaceUp
  S4.compressionsStarted = False
  
  S5.sceneChecked = True
  S5.victimAssessed = True
  S5.emergencyCalled = True
  S5.victimPositioned = True
  S5.compressionsStarted = True
  S5.handPosition = True
  S5.shouldersOverHands = True
  S5.elbowsStraight = True
  S5.compressionRate = 110
  S5.compressionDepth = 2
  S5.chestRecoil = True
  S5.compressionCount = 30
  S5.rescueBreathsGiven = False
  
  S6.sceneChecked = True
  S6.victimAssessed = True
  S6.emergencyCalled = True
  S6.victimPositioned = True
  S6.compressionsStarted = True
  S6.compressionCount = 30
  S6.rescueBreathsGiven = True
  S6.headTilted = True
  S6.chinLifted = True
  S6.nosePinched = True
  S6.mouthSealed = True
  S6.airwayStatus = Open
  S6.breathCount = 2
  S6.breathDuration = 1
  S6.chestRise = Rising
}

pred simpleScenario {
  some s: State | {
    s.sceneChecked = True
    s.environment = Safe
  }
}

-- ----------------- WRAPPER PREDICATE -----------------

pred ReferenceConstraints {
    TimeStructure
    StateTimeMapping
    IntegerDefaults
    NeverProceedIfUnsafe
    ProtocolOrder
    Dependencies
    CPRRequiresPrerequisites
    BreathsRequireCompressions
}

-- ----------------- GENERATED PLAN -----------------

pred GeneratedPlan {

}

-- ----------------- COUNTEREXAMPLE SEARCH -----------------

run {
    GeneratedPlan
    and not ReferenceConstraints
} for 10 Action, 10 Dependency, 1 PatientStatus