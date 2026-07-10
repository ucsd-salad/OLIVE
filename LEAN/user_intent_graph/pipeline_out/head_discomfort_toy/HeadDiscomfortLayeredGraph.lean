namespace HeadDiscomfortLayeredGraph

/-!
A compact layered event graph for:

  "I have head discomfort and feel a little nauseous."

The graph keeps the random-walk flavor: each path moves one layer at a time,
and nodes in later layers are shared by several earlier branches.

Layer sizes are intentionally small:
  - one input node
  - three complaint-focus nodes
  - three shared-event nodes
  - three course-detail nodes
  - three diagnostic-hypothesis nodes
  - three diagnostic-stratum nodes
  - three terminal decision nodes
-/

inductive Layer where
  | input
  | complaintFocus
  | sharedEventSignal
  | courseDetail
  | diagnosticHypothesis
  | diagnosticStratum
  | finalDecision
deriving DecidableEq, BEq, Repr

inductive ComplaintFocus where
  | mainlyHeadache
  | dizzinessOrVertigo
  | unclearButConcerning
deriving DecidableEq, BEq, Repr

inductive SharedEventSignal where
  | suddenSevereOrNeverBefore
  | neurologicOrVisualAbnormality
  | systemicTraumaOrCourseSignal
deriving DecidableEq, BEq, Repr

inductive CourseDetail where
  | acuteDangerFeature
  | persistentNoEmergencyFeature
  | mildStableImprovingFeature
deriving DecidableEq, BEq, Repr

inductive DiagnosticHypothesis where
  | vascularOrIntracranialBleedingPossible
  | centralInfectionOrHeadInjuryPossible
  | commonNonAcuteHeadacheDizzinessPossible
deriving DecidableEq, BEq, Repr

inductive DiagnosticStratum where
  | emergencyDiagnosticLayer
  | priorityDiagnosticLayer
  | lowRiskDiagnosticLayer
deriving DecidableEq, BEq, Repr

inductive FinalDecision where
  | emergency
  | priority
  | nonUrgent
deriving DecidableEq, BEq, Repr

inductive GraphNode where
  | inputHeadDiscomfortWithNausea
  | focusMainlyHeadache
  | focusDizzinessOrVertigo
  | focusUnclearButConcerning
  | eventSuddenSevereOrNeverBefore
  | eventNeurologicOrVisualAbnormality
  | eventSystemicTraumaOrCourseSignal
  | courseAcuteDangerFeature
  | coursePersistentNoEmergencyFeature
  | courseMildStableImprovingFeature
  | diagnosisVascularOrIntracranialBleedingPossible
  | diagnosisCentralInfectionOrHeadInjuryPossible
  | diagnosisCommonNonAcuteHeadacheDizzinessPossible
  | stratumEmergencyDiagnosticLayer
  | stratumPriorityDiagnosticLayer
  | stratumLowRiskDiagnosticLayer
  | decisionEmergency
  | decisionPriority
  | decisionNonUrgent
deriving DecidableEq, BEq, Repr

def nodeLayer : GraphNode -> Layer
  | .inputHeadDiscomfortWithNausea => .input
  | .focusMainlyHeadache => .complaintFocus
  | .focusDizzinessOrVertigo => .complaintFocus
  | .focusUnclearButConcerning => .complaintFocus
  | .eventSuddenSevereOrNeverBefore => .sharedEventSignal
  | .eventNeurologicOrVisualAbnormality => .sharedEventSignal
  | .eventSystemicTraumaOrCourseSignal => .sharedEventSignal
  | .courseAcuteDangerFeature => .courseDetail
  | .coursePersistentNoEmergencyFeature => .courseDetail
  | .courseMildStableImprovingFeature => .courseDetail
  | .diagnosisVascularOrIntracranialBleedingPossible => .diagnosticHypothesis
  | .diagnosisCentralInfectionOrHeadInjuryPossible => .diagnosticHypothesis
  | .diagnosisCommonNonAcuteHeadacheDizzinessPossible => .diagnosticHypothesis
  | .stratumEmergencyDiagnosticLayer => .diagnosticStratum
  | .stratumPriorityDiagnosticLayer => .diagnosticStratum
  | .stratumLowRiskDiagnosticLayer => .diagnosticStratum
  | .decisionEmergency => .finalDecision
  | .decisionPriority => .finalDecision
  | .decisionNonUrgent => .finalDecision

def nodeFullName : GraphNode -> String
  | .inputHeadDiscomfortWithNausea =>
      "User reports head discomfort with mild nausea"
  | .focusMainlyHeadache =>
      "Main complaint is headache"
  | .focusDizzinessOrVertigo =>
      "Main complaint is dizziness or room-spinning vertigo"
  | .focusUnclearButConcerning =>
      "Complaint is unclear but feels obviously wrong"
  | .eventSuddenSevereOrNeverBefore =>
      "Sudden severe symptom or never-before pattern"
  | .eventNeurologicOrVisualAbnormality =>
      "Neurologic or visual abnormality"
  | .eventSystemicTraumaOrCourseSignal =>
      "Fever, infection, head trauma, persistent course, or low-risk course signal"
  | .courseAcuteDangerFeature =>
      "Acute danger feature is present"
  | .coursePersistentNoEmergencyFeature =>
      "Persistent or recurrent feature is present, without an immediate emergency feature"
  | .courseMildStableImprovingFeature =>
      "Mild, stable, and improving feature is present"
  | .diagnosisVascularOrIntracranialBleedingPossible =>
      "Vascular or intracranial bleeding diagnosis is possible"
  | .diagnosisCentralInfectionOrHeadInjuryPossible =>
      "Central infection or head injury diagnosis is possible"
  | .diagnosisCommonNonAcuteHeadacheDizzinessPossible =>
      "Common non-acute headache or dizziness diagnosis is possible"
  | .stratumEmergencyDiagnosticLayer =>
      "Emergency diagnostic stratum"
  | .stratumPriorityDiagnosticLayer =>
      "Priority diagnostic stratum"
  | .stratumLowRiskDiagnosticLayer =>
      "Low-risk diagnostic stratum"
  | .decisionEmergency =>
      "Emergency"
  | .decisionPriority =>
      "Priority or urgent but not immediate emergency"
  | .decisionNonUrgent =>
      "Non-urgent"

def focusNode : ComplaintFocus -> GraphNode
  | .mainlyHeadache => .focusMainlyHeadache
  | .dizzinessOrVertigo => .focusDizzinessOrVertigo
  | .unclearButConcerning => .focusUnclearButConcerning

def eventNode : SharedEventSignal -> GraphNode
  | .suddenSevereOrNeverBefore => .eventSuddenSevereOrNeverBefore
  | .neurologicOrVisualAbnormality => .eventNeurologicOrVisualAbnormality
  | .systemicTraumaOrCourseSignal => .eventSystemicTraumaOrCourseSignal

def courseNode : CourseDetail -> GraphNode
  | .acuteDangerFeature => .courseAcuteDangerFeature
  | .persistentNoEmergencyFeature => .coursePersistentNoEmergencyFeature
  | .mildStableImprovingFeature => .courseMildStableImprovingFeature

def diagnosisNode : DiagnosticHypothesis -> GraphNode
  | .vascularOrIntracranialBleedingPossible =>
      .diagnosisVascularOrIntracranialBleedingPossible
  | .centralInfectionOrHeadInjuryPossible =>
      .diagnosisCentralInfectionOrHeadInjuryPossible
  | .commonNonAcuteHeadacheDizzinessPossible =>
      .diagnosisCommonNonAcuteHeadacheDizzinessPossible

def stratumNode : DiagnosticStratum -> GraphNode
  | .emergencyDiagnosticLayer => .stratumEmergencyDiagnosticLayer
  | .priorityDiagnosticLayer => .stratumPriorityDiagnosticLayer
  | .lowRiskDiagnosticLayer => .stratumLowRiskDiagnosticLayer

def decisionNode : FinalDecision -> GraphNode
  | .emergency => .decisionEmergency
  | .priority => .decisionPriority
  | .nonUrgent => .decisionNonUrgent

/-!
The visual graph edges. These edges make the cross-layer interaction explicit.
Clinical validity for a full path is checked below by `validWalk`.
-/
def graphEdge : GraphNode -> GraphNode -> Bool
  | .inputHeadDiscomfortWithNausea, .focusMainlyHeadache => true
  | .inputHeadDiscomfortWithNausea, .focusDizzinessOrVertigo => true
  | .inputHeadDiscomfortWithNausea, .focusUnclearButConcerning => true

  | .focusMainlyHeadache, .eventSuddenSevereOrNeverBefore => true
  | .focusMainlyHeadache, .eventNeurologicOrVisualAbnormality => true
  | .focusMainlyHeadache, .eventSystemicTraumaOrCourseSignal => true
  | .focusDizzinessOrVertigo, .eventSuddenSevereOrNeverBefore => true
  | .focusDizzinessOrVertigo, .eventNeurologicOrVisualAbnormality => true
  | .focusDizzinessOrVertigo, .eventSystemicTraumaOrCourseSignal => true
  | .focusUnclearButConcerning, .eventSuddenSevereOrNeverBefore => true
  | .focusUnclearButConcerning, .eventNeurologicOrVisualAbnormality => true
  | .focusUnclearButConcerning, .eventSystemicTraumaOrCourseSignal => true

  | .eventSuddenSevereOrNeverBefore, .courseAcuteDangerFeature => true
  | .eventNeurologicOrVisualAbnormality, .courseAcuteDangerFeature => true
  | .eventSystemicTraumaOrCourseSignal, .courseAcuteDangerFeature => true
  | .eventSystemicTraumaOrCourseSignal, .coursePersistentNoEmergencyFeature => true
  | .eventSystemicTraumaOrCourseSignal, .courseMildStableImprovingFeature => true

  | .courseAcuteDangerFeature, .diagnosisVascularOrIntracranialBleedingPossible => true
  | .courseAcuteDangerFeature, .diagnosisCentralInfectionOrHeadInjuryPossible => true
  | .coursePersistentNoEmergencyFeature, .diagnosisCentralInfectionOrHeadInjuryPossible => true
  | .coursePersistentNoEmergencyFeature, .diagnosisCommonNonAcuteHeadacheDizzinessPossible => true
  | .courseMildStableImprovingFeature, .diagnosisCommonNonAcuteHeadacheDizzinessPossible => true

  | .diagnosisVascularOrIntracranialBleedingPossible, .stratumEmergencyDiagnosticLayer => true
  | .diagnosisCentralInfectionOrHeadInjuryPossible, .stratumEmergencyDiagnosticLayer => true
  | .diagnosisCentralInfectionOrHeadInjuryPossible, .stratumPriorityDiagnosticLayer => true
  | .diagnosisCommonNonAcuteHeadacheDizzinessPossible, .stratumPriorityDiagnosticLayer => true
  | .diagnosisCommonNonAcuteHeadacheDizzinessPossible, .stratumLowRiskDiagnosticLayer => true

  | .stratumEmergencyDiagnosticLayer, .decisionEmergency => true
  | .stratumPriorityDiagnosticLayer, .decisionPriority => true
  | .stratumLowRiskDiagnosticLayer, .decisionNonUrgent => true
  | _, _ => false

structure ClinicalObservation where
  focus : ComplaintFocus
  suddenSevereOrNeverBefore : Bool := false
  neurologicOrVisualAbnormality : Bool := false
  feverInfectionOrHeadTrauma : Bool := false
  severeInfectionOrTraumaFeature : Bool := false
  recurrentOrPersistentWithoutEmergency : Bool := false
  mildStableImproving : Bool := false
deriving DecidableEq, Repr

structure LayeredClinicalWalk where
  focus : ComplaintFocus
  eventSignal : SharedEventSignal
  courseDetail : CourseDetail
  diagnosis : DiagnosticHypothesis
  stratum : DiagnosticStratum
  decision : FinalDecision
deriving DecidableEq, Repr

def eventSignalFromObservation (o : ClinicalObservation) : SharedEventSignal :=
  if o.suddenSevereOrNeverBefore then
    .suddenSevereOrNeverBefore
  else if o.neurologicOrVisualAbnormality then
    .neurologicOrVisualAbnormality
  else
    .systemicTraumaOrCourseSignal

def courseDetailFromObservation (o : ClinicalObservation) : CourseDetail :=
  if o.suddenSevereOrNeverBefore ||
     o.neurologicOrVisualAbnormality ||
     o.severeInfectionOrTraumaFeature then
    .acuteDangerFeature
  else if o.feverInfectionOrHeadTrauma ||
          o.recurrentOrPersistentWithoutEmergency then
    .persistentNoEmergencyFeature
  else
    .mildStableImprovingFeature

def diagnosisFromObservation (o : ClinicalObservation) : DiagnosticHypothesis :=
  if o.suddenSevereOrNeverBefore || o.neurologicOrVisualAbnormality then
    .vascularOrIntracranialBleedingPossible
  else if o.feverInfectionOrHeadTrauma || o.severeInfectionOrTraumaFeature then
    .centralInfectionOrHeadInjuryPossible
  else
    .commonNonAcuteHeadacheDizzinessPossible

def stratumFromDiagnosisAndCourse
    (d : DiagnosticHypothesis)
    (c : CourseDetail) :
    DiagnosticStratum :=
  match d, c with
  | .vascularOrIntracranialBleedingPossible, _ =>
      .emergencyDiagnosticLayer
  | .centralInfectionOrHeadInjuryPossible, .acuteDangerFeature =>
      .emergencyDiagnosticLayer
  | .centralInfectionOrHeadInjuryPossible, _ =>
      .priorityDiagnosticLayer
  | .commonNonAcuteHeadacheDizzinessPossible, .mildStableImprovingFeature =>
      .lowRiskDiagnosticLayer
  | .commonNonAcuteHeadacheDizzinessPossible, _ =>
      .priorityDiagnosticLayer

def decisionFromStratum : DiagnosticStratum -> FinalDecision
  | .emergencyDiagnosticLayer => .emergency
  | .priorityDiagnosticLayer => .priority
  | .lowRiskDiagnosticLayer => .nonUrgent

def walkFromObservation (o : ClinicalObservation) : LayeredClinicalWalk :=
  let e := eventSignalFromObservation o
  let c := courseDetailFromObservation o
  let d := diagnosisFromObservation o
  let s := stratumFromDiagnosisAndCourse d c
  {
    focus := o.focus
    eventSignal := e
    courseDetail := c
    diagnosis := d
    stratum := s
    decision := decisionFromStratum s
  }

def focusEventAllowed
    (_focus : ComplaintFocus)
    (_event : SharedEventSignal) :
    Bool :=
  true

def eventCourseAllowed : SharedEventSignal -> CourseDetail -> Bool
  | .suddenSevereOrNeverBefore, .acuteDangerFeature => true
  | .neurologicOrVisualAbnormality, .acuteDangerFeature => true
  | .systemicTraumaOrCourseSignal, .acuteDangerFeature => true
  | .systemicTraumaOrCourseSignal, .persistentNoEmergencyFeature => true
  | .systemicTraumaOrCourseSignal, .mildStableImprovingFeature => true
  | _, _ => false

def eventCourseDiagnosisAllowed
    (e : SharedEventSignal)
    (c : CourseDetail)
    (d : DiagnosticHypothesis) :
    Bool :=
  match e, c, d with
  | .suddenSevereOrNeverBefore,
    .acuteDangerFeature,
    .vascularOrIntracranialBleedingPossible => true
  | .neurologicOrVisualAbnormality,
    .acuteDangerFeature,
    .vascularOrIntracranialBleedingPossible => true
  | .systemicTraumaOrCourseSignal,
    .acuteDangerFeature,
    .centralInfectionOrHeadInjuryPossible => true
  | .systemicTraumaOrCourseSignal,
    .persistentNoEmergencyFeature,
    .centralInfectionOrHeadInjuryPossible => true
  | .systemicTraumaOrCourseSignal,
    .persistentNoEmergencyFeature,
    .commonNonAcuteHeadacheDizzinessPossible => true
  | .systemicTraumaOrCourseSignal,
    .mildStableImprovingFeature,
    .commonNonAcuteHeadacheDizzinessPossible => true
  | _, _, _ => false

def diagnosisCourseStratumAllowed
    (d : DiagnosticHypothesis)
    (c : CourseDetail)
    (s : DiagnosticStratum) :
    Bool :=
  match d, c, s with
  | .vascularOrIntracranialBleedingPossible,
    _,
    .emergencyDiagnosticLayer => true
  | .centralInfectionOrHeadInjuryPossible,
    .acuteDangerFeature,
    .emergencyDiagnosticLayer => true
  | .centralInfectionOrHeadInjuryPossible,
    .persistentNoEmergencyFeature,
    .priorityDiagnosticLayer => true
  | .commonNonAcuteHeadacheDizzinessPossible,
    .persistentNoEmergencyFeature,
    .priorityDiagnosticLayer => true
  | .commonNonAcuteHeadacheDizzinessPossible,
    .mildStableImprovingFeature,
    .lowRiskDiagnosticLayer => true
  | _, _, _ => false

def stratumDecisionAllowed : DiagnosticStratum -> FinalDecision -> Bool
  | .emergencyDiagnosticLayer, .emergency => true
  | .priorityDiagnosticLayer, .priority => true
  | .lowRiskDiagnosticLayer, .nonUrgent => true
  | _, _ => false

def validWalk (w : LayeredClinicalWalk) : Bool :=
  focusEventAllowed w.focus w.eventSignal &&
  eventCourseAllowed w.eventSignal w.courseDetail &&
  eventCourseDiagnosisAllowed w.eventSignal w.courseDetail w.diagnosis &&
  diagnosisCourseStratumAllowed w.diagnosis w.courseDetail w.stratum &&
  stratumDecisionAllowed w.stratum w.decision

def walkUsesGraphEdges (w : LayeredClinicalWalk) : Bool :=
  graphEdge .inputHeadDiscomfortWithNausea (focusNode w.focus) &&
  graphEdge (focusNode w.focus) (eventNode w.eventSignal) &&
  graphEdge (eventNode w.eventSignal) (courseNode w.courseDetail) &&
  graphEdge (courseNode w.courseDetail) (diagnosisNode w.diagnosis) &&
  graphEdge (diagnosisNode w.diagnosis) (stratumNode w.stratum) &&
  graphEdge (stratumNode w.stratum) (decisionNode w.decision)

def headacheSuddenEmergency : LayeredClinicalWalk :=
  {
    focus := .mainlyHeadache
    eventSignal := .suddenSevereOrNeverBefore
    courseDetail := .acuteDangerFeature
    diagnosis := .vascularOrIntracranialBleedingPossible
    stratum := .emergencyDiagnosticLayer
    decision := .emergency
  }

def headacheNeuroVisualEmergency : LayeredClinicalWalk :=
  {
    focus := .mainlyHeadache
    eventSignal := .neurologicOrVisualAbnormality
    courseDetail := .acuteDangerFeature
    diagnosis := .vascularOrIntracranialBleedingPossible
    stratum := .emergencyDiagnosticLayer
    decision := .emergency
  }

def headacheMildImprovingNonUrgent : LayeredClinicalWalk :=
  {
    focus := .mainlyHeadache
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .mildStableImprovingFeature
    diagnosis := .commonNonAcuteHeadacheDizzinessPossible
    stratum := .lowRiskDiagnosticLayer
    decision := .nonUrgent
  }

def dizzinessNeuroVisualEmergency : LayeredClinicalWalk :=
  {
    focus := .dizzinessOrVertigo
    eventSignal := .neurologicOrVisualAbnormality
    courseDetail := .acuteDangerFeature
    diagnosis := .vascularOrIntracranialBleedingPossible
    stratum := .emergencyDiagnosticLayer
    decision := .emergency
  }

def dizzinessInfectionTraumaEmergency : LayeredClinicalWalk :=
  {
    focus := .dizzinessOrVertigo
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .acuteDangerFeature
    diagnosis := .centralInfectionOrHeadInjuryPossible
    stratum := .emergencyDiagnosticLayer
    decision := .emergency
  }

def dizzinessInfectionTraumaPriority : LayeredClinicalWalk :=
  {
    focus := .dizzinessOrVertigo
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .persistentNoEmergencyFeature
    diagnosis := .centralInfectionOrHeadInjuryPossible
    stratum := .priorityDiagnosticLayer
    decision := .priority
  }

def dizzinessPersistentPriority : LayeredClinicalWalk :=
  {
    focus := .dizzinessOrVertigo
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .persistentNoEmergencyFeature
    diagnosis := .commonNonAcuteHeadacheDizzinessPossible
    stratum := .priorityDiagnosticLayer
    decision := .priority
  }

def unclearSuddenEmergency : LayeredClinicalWalk :=
  {
    focus := .unclearButConcerning
    eventSignal := .suddenSevereOrNeverBefore
    courseDetail := .acuteDangerFeature
    diagnosis := .vascularOrIntracranialBleedingPossible
    stratum := .emergencyDiagnosticLayer
    decision := .emergency
  }

def unclearInfectionTraumaEmergency : LayeredClinicalWalk :=
  {
    focus := .unclearButConcerning
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .acuteDangerFeature
    diagnosis := .centralInfectionOrHeadInjuryPossible
    stratum := .emergencyDiagnosticLayer
    decision := .emergency
  }

def unclearInfectionTraumaPriority : LayeredClinicalWalk :=
  {
    focus := .unclearButConcerning
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .persistentNoEmergencyFeature
    diagnosis := .centralInfectionOrHeadInjuryPossible
    stratum := .priorityDiagnosticLayer
    decision := .priority
  }

def unclearMildStableNonUrgent : LayeredClinicalWalk :=
  {
    focus := .unclearButConcerning
    eventSignal := .systemicTraumaOrCourseSignal
    courseDetail := .mildStableImprovingFeature
    diagnosis := .commonNonAcuteHeadacheDizzinessPossible
    stratum := .lowRiskDiagnosticLayer
    decision := .nonUrgent
  }

example : validWalk headacheSuddenEmergency = true := by native_decide
example : validWalk headacheNeuroVisualEmergency = true := by native_decide
example : validWalk headacheMildImprovingNonUrgent = true := by native_decide
example : validWalk dizzinessNeuroVisualEmergency = true := by native_decide
example : validWalk dizzinessInfectionTraumaEmergency = true := by native_decide
example : validWalk dizzinessInfectionTraumaPriority = true := by native_decide
example : validWalk dizzinessPersistentPriority = true := by native_decide
example : validWalk unclearSuddenEmergency = true := by native_decide
example : validWalk unclearInfectionTraumaEmergency = true := by native_decide
example : validWalk unclearInfectionTraumaPriority = true := by native_decide
example : validWalk unclearMildStableNonUrgent = true := by native_decide

example : walkUsesGraphEdges headacheSuddenEmergency = true := by native_decide
example : walkUsesGraphEdges dizzinessPersistentPriority = true := by native_decide
example : walkUsesGraphEdges unclearMildStableNonUrgent = true := by native_decide

def observationHeadacheSudden : ClinicalObservation :=
  {
    focus := .mainlyHeadache
    suddenSevereOrNeverBefore := true
  }

def observationDizzinessPersistent : ClinicalObservation :=
  {
    focus := .dizzinessOrVertigo
    recurrentOrPersistentWithoutEmergency := true
  }

def observationUnclearMildStable : ClinicalObservation :=
  {
    focus := .unclearButConcerning
    mildStableImproving := true
  }

example :
    (walkFromObservation observationHeadacheSudden).decision =
      FinalDecision.emergency := by
  native_decide

example :
    (walkFromObservation observationDizzinessPersistent).decision =
      FinalDecision.priority := by
  native_decide

example :
    (walkFromObservation observationUnclearMildStable).decision =
      FinalDecision.nonUrgent := by
  native_decide

end HeadDiscomfortLayeredGraph
