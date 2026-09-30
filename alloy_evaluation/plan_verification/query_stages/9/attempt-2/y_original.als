open safety_protocol_core
open query_ext

pred rule {
  some p: Patron, d: DivingArea, f: Facility |
    p.wristband = Yellow and
    p.chestHeightInches > 0 and
    p.(QueryExt.passedDeepWaterTest) = False and
    d in f.zones and
    d.depthInches > 120 and
    d.hasDivingBoard = True and
    p.onDeck = True and
    some a: Adult |
      a in p.chaperoneAdult and
      a.withinArmsReachOfWard = True
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
