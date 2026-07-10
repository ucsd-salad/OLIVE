namespace List
def get? : List α → Nat → Option α
  | [], _ => none
  | a :: _, 0 => some a
  | _ :: as, n+1 => get? as n
end List

namespace GeneratedTriageSafety

inductive Confidence where
  | low | medium | high
deriving DecidableEq, BEq, Repr

inductive TriageCategory where
  | emergency | priority | nonUrgent
deriving DecidableEq, BEq, Repr

inductive AVPULevel where
  | alert | voice | pain | unresponsive
deriving DecidableEq, BEq, Repr

inductive EmergencySign where
  | airwayObstruction
  | centralCyanosis
  | notBreathing
  | severeRespiratoryDistress
  | circulatoryShock
  | coma
  | convulsing
  | severeDehydration
deriving DecidableEq, BEq, Repr

inductive PrioritySign where
  | tinyBaby
  | veryHot
  | trauma
  | severePallor
  | poisoning
  | severePain
  | restlessIrritableOrLethargic
  | urgentReferral
  | severeWasting
  | oedemaBothFeet
  | majorBurn
  | respiratoryDistress
  | moderateDehydration
deriving DecidableEq, BEq, Repr

inductive EmergencyAction where
  | startAirwayManagement
  | startBreathingSupport
  | startCirculatorySupport
  | manageComa
  | manageConvulsion
  | manageDehydration
  | callSenior
  | labInvestigations
deriving DecidableEq, BEq, Repr

structure TriageAssessment where
  ageMonths : Nat := 0
  airwayObstructed : Bool := false
  centralCyanosis : Bool := false
  notBreathing : Bool := false
  severeRespiratoryDistress : Bool := false
  warmHands : Bool := false
  capillaryRefillOver3sec : Bool := false
  weakAndFastPulse : Bool := false
  avpu : AVPULevel := AVPULevel.alert
  convulsing : Bool := false
  sunkenEyes : Bool := false
  slowSkinPinch : Bool := false
  diarrhea : Bool := false
  vomiting : Bool := false
  drinkingPoorly : Bool := false
  repeatedVomiting : Bool := false
  feelsVeryHot : Bool := false
  severeTraumaOrSurgical : Bool := false
  severePallor : Bool := false
  poisoning : Bool := false
  severePain : Bool := false
  restlessIrritableOrLethargic : Bool := false
  urgentReferral : Bool := false
  severeWasting : Bool := false
  oedemaBothFeet : Bool := false
  majorBurn : Bool := false
  confidence : Confidence := Confidence.high
  respiratoryDistress : Bool := false
  length : Nat := 0
deriving Repr

inductive Location where
  | OPD
  | emergencyRoom
  | wards
deriving DecidableEq, BEq, Repr

def validTriageLocation (l : Location) : Bool :=
  match l with
  | Location.OPD => true
  | Location.emergencyRoom => true
  | Location.wards => true

def isLethargic (avpu : AVPULevel) : Bool := avpu == AVPULevel.voice

def isComa (avpu : AVPULevel) : Bool := avpu == AVPULevel.pain || avpu == AVPULevel.unresponsive

def hasCirculatoryShock (a : TriageAssessment) : Bool :=
  (! a.warmHands) && a.capillaryRefillOver3sec && a.weakAndFastPulse

def dehydrationSignCount (a : TriageAssessment) : Nat :=
  let lethargicOrUnconscious := isComa a.avpu || isLethargic a.avpu
  (if lethargicOrUnconscious then 1 else 0) + (if a.sunkenEyes then 1 else 0) + (if a.slowSkinPinch then 1 else 0)

def fluidLossConcern (a : TriageAssessment) : Bool :=
  a.diarrhea || a.vomiting || a.drinkingPoorly || a.repeatedVomiting

def severeDehydrationPresent (a : TriageAssessment) : Bool :=
  dehydrationSignCount a ≥ 2

def moderateDehydrationPresent (a : TriageAssessment) : Bool :=
  fluidLossConcern a &&
  ! severeDehydrationPresent a &&
  ((dehydrationSignCount a == 1) || a.drinkingPoorly || a.repeatedVomiting)

def emergencySignList (a : TriageAssessment) : List EmergencySign :=
  (if a.airwayObstructed then [EmergencySign.airwayObstruction] else []) ++
  (if a.centralCyanosis then [EmergencySign.centralCyanosis] else []) ++
  (if a.notBreathing then [EmergencySign.notBreathing] else []) ++
  (if a.severeRespiratoryDistress then [EmergencySign.severeRespiratoryDistress] else []) ++
  (if hasCirculatoryShock a then [EmergencySign.circulatoryShock] else []) ++
  (if isComa a.avpu then [EmergencySign.coma] else []) ++
  (if a.convulsing then [EmergencySign.convulsing] else []) ++
  (if severeDehydrationPresent a then [EmergencySign.severeDehydration] else [])

def detectedPrioritySigns (a : TriageAssessment) : List PrioritySign :=
  (if a.ageMonths < 2 then [PrioritySign.tinyBaby] else []) ++
  (if a.feelsVeryHot then [PrioritySign.veryHot] else []) ++
  (if a.severeTraumaOrSurgical then [PrioritySign.trauma] else []) ++
  (if a.severePallor then [PrioritySign.severePallor] else []) ++
  (if a.poisoning then [PrioritySign.poisoning] else []) ++
  (if a.severePain then [PrioritySign.severePain] else []) ++
  (if a.restlessIrritableOrLethargic then [PrioritySign.restlessIrritableOrLethargic] else []) ++
  (if a.urgentReferral then [PrioritySign.urgentReferral] else []) ++
  (if a.severeWasting then [PrioritySign.severeWasting] else []) ++
  (if a.oedemaBothFeet then [PrioritySign.oedemaBothFeet] else []) ++
  (if a.majorBurn then [PrioritySign.majorBurn] else []) ++
  (if moderateDehydrationPresent a then [PrioritySign.moderateDehydration] else []) ++
  (if a.respiratoryDistress && ! a.severeRespiratoryDistress then [PrioritySign.respiratoryDistress] else [])

def requiredEmergencyActions (a : TriageAssessment) : List EmergencyAction :=
  let base : List EmergencyAction :=
    (if a.airwayObstructed || a.centralCyanosis || a.notBreathing then [EmergencyAction.startAirwayManagement] else []) ++
    (if a.severeRespiratoryDistress then [EmergencyAction.startBreathingSupport] else []) ++
    (if hasCirculatoryShock a then [EmergencyAction.startCirculatorySupport] else []) ++
    (if isComa a.avpu then [EmergencyAction.manageComa] else []) ++
    (if a.convulsing then [EmergencyAction.manageConvulsion] else []) ++
    (if severeDehydrationPresent a then [EmergencyAction.manageDehydration] else [])
  if (emergencySignList a).length > 0 then base ++ [EmergencyAction.callSenior, EmergencyAction.labInvestigations] else base

structure TriageResult where
  category : TriageCategory
  emergencySigns : List EmergencySign
  prioritySigns : List PrioritySign
  confidence : Confidence
  requiredActions : List EmergencyAction
  reassessFrequently : Bool
deriving Repr

def triageDecision (a : TriageAssessment) : TriageResult :=
  let emergSigns := emergencySignList a
  if emergSigns.length > 0 then
    {
      category := TriageCategory.emergency
      emergencySigns := emergSigns
      prioritySigns := []
      confidence := a.confidence
      requiredActions := requiredEmergencyActions a
      reassessFrequently := true
    }
  else
    let priorSigns := detectedPrioritySigns a
    if priorSigns.length > 0 then
      {
        category := TriageCategory.priority
        emergencySigns := []
        prioritySigns := priorSigns
        confidence := a.confidence
        requiredActions := []
        reassessFrequently := false
      }
    else
      {
        category := TriageCategory.nonUrgent
        emergencySigns := []
        prioritySigns := []
        confidence := a.confidence
        requiredActions := []
        reassessFrequently := false
      }

abbrev PatientAssessment := TriageAssessment

def triageCategory (p : PatientAssessment) : TriageCategory := (triageDecision p).category

def detectedEmergencySigns (a : TriageAssessment) : TriageAssessment := { a with length := (emergencySignList a).length }

theorem emergency_implies_call_senior_and_labs (a : TriageAssessment) (h : (emergencySignList a).length > 0) :
    EmergencyAction.callSenior ∈ requiredEmergencyActions a ∧ EmergencyAction.labInvestigations ∈ requiredEmergencyActions a := by
  have hcond : (emergencySignList a).length > 0 := h
  have hreq : requiredEmergencyActions a =
      ((if a.airwayObstructed || a.centralCyanosis || a.notBreathing then [EmergencyAction.startAirwayManagement] else []) ++
       (if a.severeRespiratoryDistress then [EmergencyAction.startBreathingSupport] else []) ++
       (if hasCirculatoryShock a then [EmergencyAction.startCirculatorySupport] else []) ++
       (if isComa a.avpu then [EmergencyAction.manageComa] else []) ++
       (if a.convulsing then [EmergencyAction.manageConvulsion] else []) ++
       (if severeDehydrationPresent a then [EmergencyAction.manageDehydration] else [])) ++
      [EmergencyAction.callSenior, EmergencyAction.labInvestigations] := by
    unfold requiredEmergencyActions
    rw [if_pos hcond]
  rw [hreq]
  constructor
  · apply List.mem_append_right; simp
  · apply List.mem_append_right; simp

theorem emergency_implies_reassess (a : TriageAssessment) (h : (emergencySignList a).length > 0) :
    (triageDecision a).reassessFrequently = true := by
  unfold triageDecision
  simp [h]

theorem no_signs_implies_non_urgent (a : TriageAssessment) (h0 : (emergencySignList a).length = 0) (h1 : (detectedPrioritySigns a).length = 0) :
    (triageDecision a).category = TriageCategory.nonUrgent := by
  unfold triageDecision
  simp [h0, h1]

end GeneratedTriageSafety
