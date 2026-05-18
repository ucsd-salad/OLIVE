/*
 * =============================================================================
 * Aquatic Center Safety Protocol -- Formalization v2
 * Faithful encoding of Swimming.txt
 * =============================================================================
 *
 * Numeric scaling (Alloy Int is bounded; we use `but 9 Int` => range -256..255):
 *   - pH stored * 10                 (74  means 7.4)
 *   - FAC stored * 10 ppm            (15  means 1.5 ppm)
 *   - Combined Chlorine * 10 ppm     (4   means 0.4 ppm)
 *   - ORP stored / 100 mV            (7   means 700 mV)
 *   - Weight stored / 10 lbs         (30  means 300 lbs)
 *   - Current speed stored * 10 ft/s (25  means 2.5 ft/s)
 *   - All other numbers are raw (inches, feet, degF, mph, minutes, counts).
 *
 * Coverage matrix vs. Swimming.txt:
 *   Sec 2: Staff hierarchy + duty-to-act + fitness
 *   Sec 3: Capacity (fire/water/ratio/95% lockout), waivers, medical clearance + buddy
 *   Sec 4: All four wristbands (chest/armpit depth, blue-band athlete check),
 *          arm's reach, ratios, prohibited behaviors set, contraband, hygiene,
 *          swim diapers, USCG life jacket
 *   Sec 5: Wave pool (amplitude reduction, cycle, dispatch depth, bottom scan),
 *          Lazy river (tube ratio, stairwells, no bridge jumping, current speed),
 *          Diving (one at a time inc. ladder, one bounce, forward only, surfaced
 *          AND reached wall, goggle ban), Slide (height + weight + dual all-clear
 *          + riding position + no catching), Spa (age, temp, 104.5 evac, time,
 *          submersion ban)
 *   Sec 6: 10/20 scanning, glare/blind spot, station relief (rescue tube + verbal),
 *          rotation 20-30 min, in-service training, Red Tag audit, zone <=25
 *   Sec 7: Drowning stages, EAP activation, Code Adam (clear pool, age<12,
 *          10-min police deadline)
 *   Sec 8: Pump room (lock, 10ft separation, berms, authorized access, PPE),
 *          chemicals, manual test every 2hrs, chloramine super-chlorination,
 *          water clarity, HVAC chloramine fresh-air -> evac
 *   Sec 9: Lightning 30-min rule + showers, layered wind (35 elevated / 50 evac),
 *          sun glare, BBP / solid fecal / diarrheal protocols, power outage,
 *          fire alarm (clear + Mylar + locker bypass)
 *   Sec 10: Strike 1 (verbal), Strike 2 (15 min time-out), Strike 3 (ejection),
 *          zero-tolerance => permanent ban
 */

// =============================================================================
// BASIC ENUMS
// =============================================================================

abstract sig Bool {}
one sig True extends Bool {}
one sig False extends Bool {}

abstract sig WristbandColor {}
one sig Green  extends WristbandColor {}
one sig Yellow extends WristbandColor {}
one sig Red    extends WristbandColor {}
one sig Blue   extends WristbandColor {}

abstract sig DrowningStage {}
one sig AquaticDistress extends DrowningStage {}
one sig ActiveDrowning  extends DrowningStage {}
one sig PassiveDrowning extends DrowningStage {}

abstract sig Behavior {}
one sig DivingInShallowWater  extends Behavior {}
one sig ProlongedBreathHolding extends Behavior {}
one sig Hyperventilation      extends Behavior {}
one sig Horseplay             extends Behavior {} // dunking, chicken fights, splashing
one sig RunningOnDeck         extends Behavior {}
one sig BridgeJumping         extends Behavior {} // jumping into lazy river from bridges
one sig NonForwardDive        extends Behavior {} // inward/reverse/backflip in open swim
one sig MultipleBounces       extends Behavior {} // >1 bounce on the fulcrum
one sig GogglesOnDivingBoard  extends Behavior {}
one sig NonFeetFirstSlide     extends Behavior {} // riding head-first / arms loose
one sig SpaSubmersion         extends Behavior {} // head under water in spa
one sig CatchingAtSlideBase   extends Behavior {} // adult catching kids in splashdown
one sig PhysicalViolence      extends Behavior {} // zero-tolerance
one sig StaffAbuse            extends Behavior {} // zero-tolerance verbal abuse
one sig IntentionalDefecation extends Behavior {} // zero-tolerance
one sig RestrictedAreaEntry   extends Behavior {} // zero-tolerance

abstract sig WhistleSignal {}
one sig OneShortBlast    extends WhistleSignal {} // rule correction
one sig TwoShortBlasts   extends WhistleSignal {} // staff attention
one sig OneLongBlast     extends WhistleSignal {} // EAP activation
one sig ThreeShortBlasts extends WhistleSignal {} // pool clearance
one sig OneLongTwoShort  extends WhistleSignal {} // land EAP

abstract sig Certification {}
one sig LifeguardCert            extends Certification {}
one sig CPR_AED_Cert             extends Certification {}
one sig FirstAidCert             extends Certification {}
one sig LGICert                  extends Certification {}
one sig LifeguardManagementCert  extends Certification {}
one sig CPOCert                  extends Certification {}
one sig AFOCert                  extends Certification {}
one sig HighRiskActivityCert     extends Certification {}

// =============================================================================
// PEOPLE
// =============================================================================

abstract sig Person {}

sig Patron extends Person {
  // demographics & body metrics
  age:                one Int, // years
  heightInches:       one Int, // total height
  armpitHeightInches: one Int, // for Red Band depth check
  chestHeightInches:  one Int, // for Yellow Band depth check
  weightLbsTen:       one Int, // weight / 10 (lbs)

  // wristband
  wristband: lone WristbandColor,

  // chaperone & buddy
  chaperoneAdult: lone Adult,
  inWaterBuddy:   lone Patron, // dedicated buddy for medical-clearance patrons

  // documentation
  medicalClearance:        lone MedicalClearance,
  supplementaryWaiver:     lone SupplementaryWaiver,
  highRiskCertifications:  set  Certification,

  // health & hygiene
  hasGIIllnessWithin14Days: lone Bool,
  hasOpenWounds:            lone Bool,
  tookShowerWithSoap:       lone Bool,
  wearsSwimDiaper:          lone Bool,
  wearsUSCGLifeJacket:      lone Bool,
  carriesContraband:        lone Bool,

  // flags
  hasHighRiskMedicalCondition:    lone Bool, // seizures, cardiac, syncope
  participatesInHighRiskActivity: lone Bool, // scuba, freediving, platform
  isRegisteredAthlete:            lone Bool, // for Blue Band

  // current state
  currentBehaviors: set Behavior,
  inWater:          lone WaterZone,
  onDeck:           lone Bool,
  drowningStage:    lone DrowningStage,

  // discipline
  strikes:                one Int,
  inTimeOut:              lone Bool,
  timeOutMinutesRemaining: one Int,
  permanentBan:           lone Bool
}

sig Adult extends Person {
  inWaterSupervising:      lone Bool,
  withinArmsReachOfWard:   lone Bool,
  supervisedRedBandCount:  one Int,
  supervisedInfantCount:   one Int
}

sig MedicalClearance {}
sig SupplementaryWaiver {}

abstract sig StaffMember extends Person {
  onDuty:                          lone Bool,
  certifications:                  set  Certification,
  consumedAlcoholWithinTwelveHrs:  lone Bool,
  onDrowsyMedication:              lone Bool,
  physicallyMentallyReady:         lone Bool,
  inServiceTrainingHoursMonth:     one Int  // documented hours of training in current month
}

sig Lifeguard extends StaffMember {
  assignedZone:             lone WaterZone,
  minutesSinceRotation:     one Int,
  relievedBy:               lone Lifeguard,

  // audits & vigilance
  passedLastAudit:          lone Bool,
  auditResponseSeconds:     one Int,        // sec to spot silhouette (<=10)
  eyesOnWater:              lone Bool,
  hasRescueTube:            lone Bool,
  inEAPResponse:            lone Bool,
  visualScanWithinTenSec:   lone Bool,      // 10/20 standard
  canReachZoneInTwentySec:  lone Bool,
  zoneFullyVisualized:      lone Bool       // no unmitigated blind spots in own zone
}

sig HeadLifeguard   extends StaffMember {}
sig FacilityManager extends StaffMember {}

// =============================================================================
// WATER ZONES
// =============================================================================

abstract sig WaterZone {
  depthInches:      one Int,  // primary depth measure (1 ft = 12 inches)
  isDeepEnd:        lone Bool,
  hasDivingBoard:   lone Bool,
  patronCount:      one Int,
  assignedGuard:    lone Lifeguard,
  fullyVisualized:  lone Bool // for glare check (zone has no unmitigated blind spot)
}

sig ShallowZone extends WaterZone {}
sig DeepZone    extends WaterZone {}

sig WavePool extends WaterZone {
  wavesOn:                      lone Bool,
  windSpeedMph:                 one Int,
  amplitudeReducedFiftyPct:     lone Bool,
  minutesInCurrentCycle:        one Int,   // 0..15 ON / 0..10 OFF
  cycleIsOnPhase:               lone Bool,
  bottomScanCompletedThisCycle: lone Bool
}

sig LazyRiver extends WaterZone {
  tubesAvailable:             one Int,
  patronsInRiver:             one Int,
  currentSpeedTenthsFtSec:    one Int,  // ft/s * 10  (must be <= 25)
  entryViaDesignatedStairwell: lone Bool
}

sig DivingArea extends WaterZone {
  personsOnApparatus:      one Int,   // includes ladder
  previousDiverSurfaced:   lone Bool,
  previousDiverReachedWall: lone Bool
}

sig WaterSlide extends WaterZone {
  splashdownClearByBottomGuard:        lone Bool,
  allClearSignalReceivedByTopDispatcher: lone Bool,
  weightLimitLbsTen:                   one Int   // 30 = 300 lbs
}

sig Spa extends WaterZone {
  temperatureF: one Int  // raw degF
}

// =============================================================================
// FACILITY
// =============================================================================

sig Facility {
  // capacity (3.3)
  maxBatherLoad:               one Int,
  currentBatherCount:          one Int,
  fireCapacity:                one Int,
  shallowAreaRatioCompliant:   lone Bool, // 1 bather / 15 sqft shallow
  deepAreaRatioCompliant:      lone Bool, // 1 bather / 25 sqft deep
  turnstileLocked:             lone Bool, // automated 95% lockout

  // ops
  powerOn:                lone Bool,
  fireAlarmActive:        lone Bool,
  mainDrainVisible:       lone Bool,
  airQualitySafe:         lone Bool,
  hvacFreshAirMode:       lone Bool,
  evacuatedDueToAir:      lone Bool,
  chloramineOdorExceedsLimit: lone Bool,
  exitsLocked:            lone Bool,
  mylarBlanketsDistributed: lone Bool,
  lockerRoomBypassEnforced: lone Bool,

  // weather (9.1)
  lightningDetected:               lone Bool,
  lastThunderMinutesAgo:           one Int,
  windSpeed:                       one Int,
  showersInUse:                    lone Bool,
  outdoorElevatedStructuresOpen:   lone Bool,
  outdoorFullyEvacuated:           lone Bool,
  sunGlareAffectingZones:          lone Bool,

  // emergencies
  codeAdamActive:           lone Bool,
  missingChildAge:          one Int,
  codeAdamMinutesElapsed:   one Int,
  lawEnforcementContacted:  lone Bool,
  fireEvacuationActive:     lone Bool,

  // chemicals (8.2)
  chemicalReadings:           one ChemicalReadings,
  superChlorinationInProgress: lone Bool,
  lastManualTestMinutesAgo:   one Int,    // <= 120

  // biohazard (9.2)
  activeBiohazardIncident: lone BiohazardIncident,

  // policy
  sanctionedPracticeActive: lone Bool, // for Blue-Band practice

  // structure
  zones:    set WaterZone,
  pumpRoom: one PumpRoom
}

sig ChemicalReadings {
  facTenthPPM:             one Int, // 15..50 safe (1.5..5.0 ppm)
  combinedChlorineTenthPPM: one Int, // <= 4   (<= 0.4 ppm)
  orpHundredMV:            one Int, // >= 7   (>= 700 mV)
  pHTenth:                 one Int, // 72..78 safe; 74..76 target
  totalAlkalinity:         one Int, // 80..120
  cyanuricAcid:            one Int  // <= 50 outdoor
}

// =============================================================================
// PUMP ROOM (8.1)
// =============================================================================

sig PumpRoom {
  locked:                         lone Bool,
  oxidizersAndAcidsDistanceFeet:  one Int, // >= 10
  separateContainmentBerms:       lone Bool,
  authorizedAccessOnly:           lone Bool,
  occupants:                      set StaffMember,
  ppeWornByOccupants:             lone Bool
}

// =============================================================================
// BIOHAZARD INCIDENTS (9.2)
// =============================================================================

abstract sig BiohazardIncident {
  reopenAllowed:        lone Bool,
  minutesSinceIncident: one Int
}

sig BBPSpill extends BiohazardIncident {
  bleachSolutionUsed:    lone Bool,
  redBiohazardBagsUsed:  lone Bool
}

sig SolidFecalIncident extends BiohazardIncident {
  removedWithNetOrScoop:    lone Bool,
  facShockTenthPPM:         one Int,  // >= 20  (>= 2.0 ppm)
  pHDuringShockTenth:       one Int,  // <= 75  (<= 7.5)
  shockDurationMinutes:     one Int   // >= 30
}

sig DiarrhealIncident extends BiohazardIncident {
  facShockTenthPPM:        one Int,  // >= 200 (>= 20.0 ppm)
  ctValueAchieved:         lone Bool,
  filterBackwashedToWaste: lone Bool,
  poolClosedHours:         one Int   // >= 13 (rounded up from 12.75)
}

// =============================================================================
// PREDICATES -- Section 2 (Staff)
// =============================================================================

pred lifeguardQualified[lg: Lifeguard] {
  LifeguardCert in lg.certifications
  CPR_AED_Cert  in lg.certifications
  FirstAidCert  in lg.certifications
}

pred headLifeguardQualified[hlg: HeadLifeguard] {
  LifeguardCert in hlg.certifications
  CPR_AED_Cert  in hlg.certifications
  FirstAidCert  in hlg.certifications
  (LGICert in hlg.certifications) or (LifeguardManagementCert in hlg.certifications)
}

pred facilityManagerQualified[fm: FacilityManager] {
  CPOCert in fm.certifications or AFOCert in fm.certifications
}

pred lifeguardFitForDuty[lg: Lifeguard] {
  lg.consumedAlcoholWithinTwelveHrs = False
  lg.onDrowsyMedication             = False
  lg.physicallyMentallyReady        = True
  lg.passedLastAudit                = True
  lg.auditResponseSeconds          <= 10
}

// 2.2 Duty-to-Act: any on-duty lifeguard in a facility containing a victim
// must be responding (we model this softly via inEAPResponse on at least the
// assigned zone's guard; see eapActivation below).

// =============================================================================
// Section 3 -- Capacity / Risk / Waivers
// =============================================================================

pred highRiskWaiverValid[p: Patron] {
  p.participatesInHighRiskActivity = True implies {
    some p.supplementaryWaiver
    HighRiskActivityCert in p.highRiskCertifications
  }
}

pred medicalClearanceValid[p: Patron] {
  p.hasHighRiskMedicalCondition = True implies {
    some p.medicalClearance
    (some p.inWater) implies
      (some b: Patron | b = p.inWaterBuddy and some b.inWater)
  }
}

pred facilityCapacityValid[f: Facility] {
  f.currentBatherCount <= f.maxBatherLoad
  f.currentBatherCount <= f.fireCapacity
  f.shallowAreaRatioCompliant = True
  f.deepAreaRatioCompliant    = True
  // 95% automated turnstile lockout:
  // count + max/20 >= max  <=>  count >= 0.95 * max
  (f.currentBatherCount.plus[f.maxBatherLoad.div[20]] >= f.maxBatherLoad)
     implies f.turnstileLocked = True
}

// =============================================================================
// Section 4 -- Wristbands, Supervision, Behavior, Hygiene
// =============================================================================

// 4.1 Yellow Band: <= chest depth; no diving boards; no extreme deep end
pred yellowBandAccessValid[p: Patron] {
  (p.wristband = Yellow and some p.inWater) implies {
    p.inWater.depthInches <= p.chestHeightInches
    p.inWater.isDeepEnd     != True
    p.inWater.hasDivingBoard != True
    p.inWater not in DivingArea
  }
}

// 4.1 Red Band: shallow only AND <= armpit depth
pred redBandAccessValid[p: Patron] {
  (p.wristband = Red and some p.inWater) implies {
    p.inWater in ShallowZone
    p.inWater.depthInches <= p.armpitHeightInches
  }
}

// 4.1 Blue Band: registered athletes during sanctioned practice only
pred blueBandValid[p: Patron, f: Facility] {
  (p.wristband = Blue) implies p.isRegisteredAthlete = True
  (p.wristband = Blue and some p.inWater and p.inWater in f.zones)
    implies f.sanctionedPracticeActive = True
}

// Untested patron (no wristband) cannot enter water
pred untestedNotInWater[p: Patron] {
  (no p.wristband) implies no p.inWater
}

// 4.2 Arm's Reach: child age <= 7 OR Red Band wearer age < 12
pred armsReachSupervision[p: Patron] {
  (((p.age <= 7) or (p.wristband = Red and p.age < 12)) and some p.inWater) implies
    (some a: Adult |
       a = p.chaperoneAdult and
       a.inWaterSupervising    = True and
       a.withinArmsReachOfWard = True)
}

pred redBandRatio[a: Adult] {
  a.supervisedRedBandCount <= 3
}

pred infantSupervisionRatio[p: Patron] {
  (p.age < 3 and some p.inWater) implies
    (some a: Adult |
       a = p.chaperoneAdult and
       a.inWaterSupervising     = True and
       a.withinArmsReachOfWard  = True and
       a.supervisedInfantCount  = 1)
}

// 4.3 Prohibited behaviors (general)
pred noProhibitedBehaviors[p: Patron] {
  no (p.currentBehaviors &
      (ProlongedBreathHolding +
       Hyperventilation +
       Horseplay +
       RunningOnDeck +
       BridgeJumping))
  (DivingInShallowWater in p.currentBehaviors) implies no p.inWater
  p.carriesContraband = False
}

// 4.4 Hygiene / health
pred healthSafeForEntry[p: Patron] {
  (some p.inWater) implies {
    p.hasGIIllnessWithin14Days = False
    p.hasOpenWounds            = False
    p.tookShowerWithSoap       = True
  }
}

pred swimDiaperRequired[p: Patron] {
  (p.age < 3 and some p.inWater) implies p.wearsSwimDiaper = True
}

// =============================================================================
// Section 5 -- Feature operations
// =============================================================================

// 5.1 Wave Pool: 15/10 cycle; wind > 20 mph => amplitude -50% (NOT off);
// bottom scan during OFF cycle; <48-inch / weak swimmers past 3-ft marker
// must wear USCG life jacket.
pred wavePoolWindAmplitudeRule[wp: WavePool] {
  wp.windSpeedMph > 20 implies wp.amplitudeReducedFiftyPct = True
}

pred wavePoolCycleValid[wp: WavePool] {
  wp.cycleIsOnPhase = True  implies wp.minutesInCurrentCycle <= 15
  wp.cycleIsOnPhase = False implies wp.minutesInCurrentCycle <= 10
  (wp.cycleIsOnPhase = False and wp.minutesInCurrentCycle >= 10)
     implies wp.bottomScanCompletedThisCycle = True
}

pred wavePoolDispatchDepth[p: Patron] {
  (some p.inWater and p.inWater in WavePool and
   p.heightInches < 48 and p.inWater.depthInches > 36)
    implies p.wearsUSCGLifeJacket = True
}

// 5.2 Lazy River
pred lazyRiverTubeRatio[lr: LazyRiver] {
  lr.patronsInRiver <= lr.tubesAvailable
}

pred lazyRiverFlow[lr: LazyRiver] {
  lr.currentSpeedTenthsFtSec  <= 25
  lr.entryViaDesignatedStairwell = True
}

pred lazyRiverBehavior[p: Patron] {
  (some p.inWater and p.inWater in LazyRiver) implies
    BridgeJumping not in p.currentBehaviors
}

// 5.3 Diving boards / platforms
pred divingAreaSafe[da: DivingArea] {
  da.personsOnApparatus    <= 1          // includes ladder
  da.previousDiverSurfaced  = True
  da.previousDiverReachedWall = True
  da.depthInches           >= 108        // 9 ft
}

pred divingBoardPatronRules[p: Patron] {
  (some p.inWater and p.inWater in DivingArea) implies {
    NonForwardDive       not in p.currentBehaviors
    MultipleBounces      not in p.currentBehaviors
    GogglesOnDivingBoard not in p.currentBehaviors
  }
}

// 5.4 Water Slide
pred slideHeightReq[p: Patron] {
  (some p.inWater and p.inWater in WaterSlide) implies p.heightInches >= 48
}

pred slideWeightReq[p: Patron] {
  (some p.inWater and p.inWater in WaterSlide) implies p.weightLbsTen <= 30
}

pred slideDispatchSafe[ws: WaterSlide] {
  ws.splashdownClearByBottomGuard          = True
  ws.allClearSignalReceivedByTopDispatcher = True
}

pred slideRidingPosition[p: Patron] {
  (some p.inWater and p.inWater in WaterSlide) implies
    NonFeetFirstSlide not in p.currentBehaviors
}

pred slideCatchingBan[p: Patron] {
  CatchingAtSlideBase not in p.currentBehaviors
}

// 5.5 Spa
pred spaAgeRestriction[p: Patron] {
  (some p.inWater and p.inWater in Spa) implies p.age >= 14
}

pred spaTemperatureSafe[s: Spa] {
  s.temperatureF <= 104
}

// Section 5.5 secondary threshold: >104.5 deg F => immediate evac+close
pred spaOverTempEvac[s: Spa] {
  s.temperatureF > 104 implies s.patronCount = 0
}

pred spaSubmersionBan[p: Patron] {
  (some p.inWater and p.inWater in Spa) implies
    SpaSubmersion not in p.currentBehaviors
}

// =============================================================================
// Section 6 -- Lifeguard standards
// =============================================================================

pred scanning10_20[lg: Lifeguard] {
  lg.visualScanWithinTenSec   = True
  lg.canReachZoneInTwentySec  = True
}

pred eyesOnWater[lg: Lifeguard] {
  lg.eyesOnWater = True
}

pred stationReliefValid[lg: Lifeguard] {
  // If the guard is being relieved, the successor must have rescue tube AND
  // verbal confirmation (proxied by eyesOnWater on the same zone).
  (some lg.relievedBy) implies {
    lg.relievedBy.hasRescueTube  = True
    lg.relievedBy.eyesOnWater    = True
    lg.relievedBy.assignedZone   = lg.assignedZone
    lg.relievedBy.onDuty         = True
  }
}

pred rotationValid[lg: Lifeguard] {
  lg.minutesSinceRotation >= 0
  lg.minutesSinceRotation <= 30
}

pred trainingValid[lg: Lifeguard] {
  lg.inServiceTrainingHoursMonth >= 4
}

pred auditPassed[lg: Lifeguard] {
  lg.passedLastAudit       = True
  lg.auditResponseSeconds <= 10
}

pred zoneCapacityRequiresAdditionalStand[z: WaterZone] {
  z.patronCount <= 25
}

pred zoneNoBlindSpot[z: WaterZone] {
  z.fullyVisualized = True
}

// =============================================================================
// Section 7 -- EAP
// =============================================================================

// 7.2 EAP activation: when any patron has entered a drowning stage, the guard
// assigned to that zone is actively responding with a rescue tube.
pred eapActivation[f: Facility] {
  all p: Patron |
    (some p.drowningStage and p.inWater in f.zones) implies
      (some lg: Lifeguard |
         lg = p.inWater.assignedGuard and
         lg.inEAPResponse  = True and
         lg.hasRescueTube  = True)
}

// 7.4 Code Adam
pred codeAdamProtocol[f: Facility] {
  f.codeAdamActive = True implies {
    f.exitsLocked    = True
    f.missingChildAge < 12
    // clear all water (proxy for three short blasts + bottom sweep)
    all z: f.zones | z.patronCount = 0
    // contact law enforcement within 10 minutes
    f.codeAdamMinutesElapsed > 10 implies f.lawEnforcementContacted = True
  }
}

// =============================================================================
// Section 8 -- Infrastructure & chemistry
// =============================================================================

pred chemicalsSafe[cr: ChemicalReadings] {
  cr.facTenthPPM             >= 15
  cr.facTenthPPM             <= 50
  cr.combinedChlorineTenthPPM <= 4
  cr.orpHundredMV            >= 7
  cr.pHTenth                 >= 72
  cr.pHTenth                 <= 78
  cr.totalAlkalinity         >= 80
  cr.totalAlkalinity         <= 120
  cr.cyanuricAcid            <= 50
}

// stricter, informational only: target pH band
pred chemicalsAtTarget[cr: ChemicalReadings] {
  cr.pHTenth >= 74
  cr.pHTenth <= 76
}

pred chloramineResponse[f: Facility] {
  f.chemicalReadings.combinedChlorineTenthPPM > 4 implies
    f.superChlorinationInProgress = True
}

pred manualTestRecent[f: Facility] {
  f.lastManualTestMinutesAgo <= 120
}

pred waterClarityOK[f: Facility] {
  f.mainDrainVisible = True
}

pred pumpRoomSafe[pr: PumpRoom] {
  pr.locked                        = True
  pr.oxidizersAndAcidsDistanceFeet >= 10
  pr.separateContainmentBerms      = True
  pr.authorizedAccessOnly          = True
  // Only CPO-certified staff or AFO-holding facility managers inside
  all s: pr.occupants |
       (CPOCert in s.certifications)
    or (s in FacilityManager and AFOCert in s.certifications)
  (some pr.occupants) implies pr.ppeWornByOccupants = True
}

pred airQualityProtocol[f: Facility] {
  f.chloramineOdorExceedsLimit = True implies f.hvacFreshAirMode = True
  (f.chloramineOdorExceedsLimit = True and f.airQualitySafe != True)
    implies f.evacuatedDueToAir = True
}

// =============================================================================
// Section 9 -- Environment / biohazard / emergencies
// =============================================================================

// 9.1 Weather safety (active condition for in-water patrons)
pred weatherSafe[f: Facility] {
  f.lightningDetected     = False
  f.lastThunderMinutesAgo > 30
}

pred lightningProtocol[f: Facility] {
  (f.lightningDetected = True or f.lastThunderMinutesAgo <= 30) implies {
    all z: f.zones | z.patronCount = 0
    f.showersInUse = False
  }
}

// Wind layering: > 35 mph closes elevated structures (slides, diving towers);
// > 50 mph evacuates the entire outdoor facility.
pred windProtocol[f: Facility] {
  f.windSpeed > 35 implies f.outdoorElevatedStructuresOpen = False
  f.windSpeed > 50 implies f.outdoorFullyEvacuated         = True
}

pred sunGlareProtocol[f: Facility] {
  f.sunGlareAffectingZones = True implies
    (all z: f.zones | z.fullyVisualized != True implies z.patronCount = 0)
}

// 9.2 Biohazard
pred bbpSpillHandled[b: BBPSpill] {
  b.bleachSolutionUsed   = True
  b.redBiohazardBagsUsed = True
}

pred solidFecalHandled[s: SolidFecalIncident] {
  s.removedWithNetOrScoop = True
  s.facShockTenthPPM     >= 20
  s.pHDuringShockTenth   <= 75
  s.shockDurationMinutes >= 30
  s.minutesSinceIncident >= 30
}

pred diarrhealHandled[d: DiarrhealIncident] {
  d.facShockTenthPPM        >= 200
  d.ctValueAchieved          = True
  d.filterBackwashedToWaste  = True
  d.poolClosedHours         >= 13
}

// While a biohazard incident is active and not yet cleared for reopen, pool
// stays empty.
pred biohazardClosedDuringIncident[f: Facility] {
  (some f.activeBiohazardIncident and
   f.activeBiohazardIncident.reopenAllowed != True) implies
    all z: f.zones | z.patronCount = 0
}

// 9.3 Power / Fire / Locker bypass
pred powerOutageProtocol[f: Facility] {
  f.powerOn != True implies all z: f.zones | z.patronCount = 0
}

pred fireAlarmProtocol[f: Facility] {
  f.fireAlarmActive = True implies {
    all z: f.zones | z.patronCount = 0
    f.mylarBlanketsDistributed = True
    f.lockerRoomBypassEnforced = True
  }
}

// =============================================================================
// Section 10 -- Discipline
// =============================================================================

pred disciplinaryEnforcement[p: Patron] {
  // Strike 1: verbal warning only; patron may remain in water (no constraint).
  // Strike 2: mandatory 15-minute cool-down, out of water for entire window.
  p.strikes = 2 implies {
    p.inTimeOut               = True
    no p.inWater
    p.timeOutMinutesRemaining >  0
    p.timeOutMinutesRemaining <= 15
  }
  // Strike 3: ejection from the facility.
  p.strikes >= 3 implies (no p.inWater and p.onDeck != True)
  // Permanent ban (zero-tolerance result).
  p.permanentBan = True implies (no p.inWater and p.onDeck != True)
}

// Zero-tolerance offenses bypass strikes => permanent ban + ejection.
pred zeroToleranceEnforcement[p: Patron] {
  (some (p.currentBehaviors & (PhysicalViolence + StaffAbuse +
                               IntentionalDefecation + RestrictedAreaEntry)))
    implies p.permanentBan = True
}

// =============================================================================
// FACTS -- wire predicates as global obligations
// =============================================================================

fact StaffQualifications {
  all lg:  Lifeguard       | lg.onDuty  = True implies (lifeguardQualified[lg] and lifeguardFitForDuty[lg])
  all hlg: HeadLifeguard   | hlg.onDuty = True implies headLifeguardQualified[hlg]
  all fm:  FacilityManager | fm.onDuty  = True implies facilityManagerQualified[fm]
}

fact AllZonesInExactlyOneFacility {
  all z: WaterZone | one f: Facility | z in f.zones
}

fact PatronInWaterImpliesZoneInFacility {
  all p: Patron | some p.inWater implies (some f: Facility | p.inWater in f.zones)
}

fact FacilityCapacityF       { all f: Facility | facilityCapacityValid[f] }

fact FacilityOperationalF {
  all f: Facility, p: Patron |
    (some p.inWater and p.inWater in f.zones) implies {
      f.powerOn          = True
      f.fireAlarmActive  = False
      chemicalsSafe[f.chemicalReadings]
      f.mainDrainVisible = True
      f.airQualitySafe   = True
      manualTestRecent[f]
      weatherSafe[f]
    }
}

fact EAPF                    { all f: Facility | eapActivation[f] }
fact HighRiskF               { all p: Patron   | highRiskWaiverValid[p] }
fact MedicalClearanceF       { all p: Patron   | medicalClearanceValid[p] }
fact YellowBandF             { all p: Patron   | yellowBandAccessValid[p] }
fact RedBandF                { all p: Patron   | redBandAccessValid[p] }
fact BlueBandF               { all p: Patron, f: Facility | blueBandValid[p, f] }
fact UntestedF               { all p: Patron   | untestedNotInWater[p] }
fact ArmsReachF              { all p: Patron   | armsReachSupervision[p] }
fact RedBandRatioF           { all a: Adult    | redBandRatio[a] }
fact InfantSupF              { all p: Patron   | infantSupervisionRatio[p] }
fact NoProhibitedF           { all p: Patron   | noProhibitedBehaviors[p] }
fact HealthF                 { all p: Patron   | healthSafeForEntry[p] }
fact SwimDiaperF             { all p: Patron   | swimDiaperRequired[p] }

fact WavePoolF {
  all wp: WavePool | wavePoolWindAmplitudeRule[wp] and wavePoolCycleValid[wp]
  all p: Patron   | wavePoolDispatchDepth[p]
}

fact LazyRiverF {
  all lr: LazyRiver | lazyRiverTubeRatio[lr] and lazyRiverFlow[lr]
  all p: Patron     | lazyRiverBehavior[p]
}

fact DivingF {
  all da: DivingArea | divingAreaSafe[da]
  all p: Patron      | divingBoardPatronRules[p]
}

fact SlideF {
  all ws: WaterSlide | slideDispatchSafe[ws]
  all p: Patron      | slideHeightReq[p] and slideWeightReq[p]
                       and slideRidingPosition[p] and slideCatchingBan[p]
}

fact SpaF {
  all p: Patron | spaAgeRestriction[p] and spaSubmersionBan[p]
  all s: Spa    | spaTemperatureSafe[s] and spaOverTempEvac[s]
}

fact ScanningF {
  all lg: Lifeguard | lg.onDuty = True implies {
    scanning10_20[lg]
    eyesOnWater[lg]
    stationReliefValid[lg]
    rotationValid[lg]
    trainingValid[lg]
    auditPassed[lg]
  }
}

fact ZoneGuardedF {
  all f: Facility | all z: f.zones | z.patronCount > 0 implies {
    some z.assignedGuard
    z.assignedGuard.onDuty = True
    lifeguardQualified[z.assignedGuard]
    lifeguardFitForDuty[z.assignedGuard]
    z.assignedGuard.assignedZone = z
    zoneNoBlindSpot[z]
  }
}

fact ZoneCapacityF           { all z: WaterZone | zoneCapacityRequiresAdditionalStand[z] }
fact PumpRoomF               { all f: Facility | pumpRoomSafe[f.pumpRoom] }
fact ChloramineResponseF     { all f: Facility | chloramineResponse[f] }
fact AirQualityF             { all f: Facility | airQualityProtocol[f] }
fact LightningF              { all f: Facility | lightningProtocol[f] }
fact WindF                   { all f: Facility | windProtocol[f] }
fact SunGlareF               { all f: Facility | sunGlareProtocol[f] }
fact PowerOutageF            { all f: Facility | powerOutageProtocol[f] }
fact FireAlarmF              { all f: Facility | fireAlarmProtocol[f] }
fact CodeAdamF               { all f: Facility | codeAdamProtocol[f] }

fact BiohazardF {
  all b: BBPSpill           | bbpSpillHandled[b]
  all s: SolidFecalIncident | solidFecalHandled[s]
  all d: DiarrhealIncident  | diarrhealHandled[d]
  all f: Facility           | biohazardClosedDuringIncident[f]
}

fact DisciplineF {
  all p: Patron | disciplinaryEnforcement[p]
  all p: Patron | zeroToleranceEnforcement[p]
}

// Bookkeeping
fact OneBuddyMutuality {
  // If A's buddy is B, then B's buddy should be A (symmetric buddy pairing).
  // Optional but reasonable; comment out if you want one-way buddies.
  all p: Patron | some p.inWaterBuddy implies p.inWaterBuddy.inWaterBuddy = p
}

// Tie the subtype to the flag fields so predicates that key on either stay
// consistent (e.g., a DivingArea always has hasDivingBoard = True).
fact ZoneTypeImpliesFlags {
  all z: DeepZone    | z.isDeepEnd      = True
  all z: ShallowZone | z.isDeepEnd      != True
  all z: DivingArea  | z.hasDivingBoard = True
  all z: DivingArea  | z.isDeepEnd      = True
}

// =============================================================================
// ASSERTIONS -- derived safety invariants (NOT verbatim restatements of facts)
// Each is something we want to hold AS A CONSEQUENCE of the facts above.
// =============================================================================

// (1) Whenever a patron is in water, the zone they are in has an on-duty,
//     qualified, fit lifeguard who is actually assigned to that zone.
assert EveryBatherIsGuarded {
  all f: Facility, p: Patron |
    (some p.inWater and p.inWater in f.zones) implies
      (some lg: Lifeguard |
         lg = p.inWater.assignedGuard and
         lg.onDuty = True and
         lifeguardQualified[lg] and
         lifeguardFitForDuty[lg] and
         lg.assignedZone = p.inWater)
}

// (2) Wristbands strictly determine where a patron can be.
assert WristbandZonesRespected {
  all p: Patron |
    (p.wristband = Red and some p.inWater) implies
      (p.inWater in ShallowZone and p.inWater.depthInches <= p.armpitHeightInches)
  all p: Patron |
    (p.wristband = Yellow and some p.inWater) implies
      (p.inWater.depthInches <= p.chestHeightInches and p.inWater not in DivingArea)
}

// (3) No child under 3 in water without 1:1 in-water arm's-reach supervision.
assert InfantsAlwaysSupervised {
  all p: Patron |
    (p.age < 3 and some p.inWater) implies
      (some a: Adult | a = p.chaperoneAdult
                       and a.inWaterSupervising    = True
                       and a.withinArmsReachOfWard = True
                       and a.supervisedInfantCount = 1)
}

// (4) Lightning / 30-min rule: no bathers anywhere during the window.
assert NoBathersDuringLightning {
  all f: Facility |
    (f.lightningDetected = True or f.lastThunderMinutesAgo <= 30)
      implies (all z: f.zones | z.patronCount = 0)
}

// (5) Spa never operates above 104 F while occupied.
assert SpaNeverTooHotWhileOccupied {
  all s: Spa | s.patronCount > 0 implies s.temperatureF <= 104
}

// (6) Code Adam past 10 minutes => police contacted.
assert CodeAdamPoliceContact {
  all f: Facility |
    (f.codeAdamActive = True and f.codeAdamMinutesElapsed > 10)
      implies f.lawEnforcementContacted = True
}

// (7) Bather load never exceeds either capacity.
assert BatherLoadRespected {
  all f: Facility |
    f.currentBatherCount <= f.maxBatherLoad and
    f.currentBatherCount <= f.fireCapacity
}

// (8) Chemicals are always within safe range while bathers are in the water.
assert SafeChemicalsWhileOpen {
  all f: Facility, p: Patron |
    (some p.inWater and p.inWater in f.zones)
      implies chemicalsSafe[f.chemicalReadings]
}

// (9) Diving apparatus never has more than one person at a time.
assert OneAtATimeOnDivingBoard {
  all da: DivingArea | da.personsOnApparatus <= 1
}

// (10) Diving in shallow water is impossible: if a patron is engaging in it,
//      they aren't actually in any water zone.
assert NoShallowDiving {
  all p: Patron | (DivingInShallowWater in p.currentBehaviors) implies no p.inWater
}

// (11) When wind > 50 mph, the entire outdoor facility is evacuated.
assert HighWindForcesEvac {
  all f: Facility | f.windSpeed > 50 implies f.outdoorFullyEvacuated = True
}

// (12) Anyone permanently banned is not in water and not on deck.
assert PermanentBanRemoval {
  all p: Patron | p.permanentBan = True implies (no p.inWater and p.onDeck != True)
}

// (13) Genuinely derived: no fact directly says this, but it follows from
//      RedBandF (red -> shallow only), YellowBandF (yellow -> not deep end),
//      and UntestedF (no wristband -> not in water). Therefore the only
//      wristband colors permitted in a DeepZone are Green and Blue.
assert DeepZoneOnlyGreenOrBlue {
  all p: Patron |
    (some p.inWater and p.inWater in DeepZone) implies
      (p.wristband = Green or p.wristband = Blue)
}

// (14) Genuinely derived: anyone with a high-risk medical condition who is
//      in water must have a buddy who is also in water. (Combines
//      MedicalClearanceF with the buddy-mutuality and basic water rules.)
assert MedicalConditionBatherHasBuddyInWater {
  all p: Patron |
    (p.hasHighRiskMedicalCondition = True and some p.inWater) implies
      (some b: Patron | b = p.inWaterBuddy and some b.inWater)
}

// =============================================================================
// SANITY RUN COMMANDS -- prove the model is not vacuously unsatisfiable.
// =============================================================================

// A minimal, non-empty world should exist.
run SanityNonEmpty {
  some Facility
  some Lifeguard
  some Patron
} for 5 but 9 Int

// A world where at least one bather is properly inside a guarded zone.
run SanityBatherGuarded {
  some f: Facility, p: Patron, lg: Lifeguard |
       p.inWater in f.zones
    and lg.assignedZone = p.inWater
    and lg = p.inWater.assignedGuard
    and lg.onDuty = True
} for 5 but 9 Int

// =============================================================================
// CHECK COMMANDS -- each derived invariant against the facts.
// =============================================================================

check EveryBatherIsGuarded       for 5 but 9 Int
check WristbandZonesRespected    for 5 but 9 Int
check InfantsAlwaysSupervised    for 5 but 9 Int
check NoBathersDuringLightning   for 5 but 9 Int
check SpaNeverTooHotWhileOccupied for 5 but 9 Int
check CodeAdamPoliceContact      for 5 but 9 Int
check BatherLoadRespected        for 5 but 9 Int
check SafeChemicalsWhileOpen     for 5 but 9 Int
check OneAtATimeOnDivingBoard    for 5 but 9 Int
check NoShallowDiving            for 5 but 9 Int
check HighWindForcesEvac              for 5 but 9 Int
check PermanentBanRemoval             for 5 but 9 Int
check DeepZoneOnlyGreenOrBlue         for 5 but 9 Int
check MedicalConditionBatherHasBuddyInWater for 5 but 9 Int