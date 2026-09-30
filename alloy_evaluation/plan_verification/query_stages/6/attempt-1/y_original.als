open safety_protocol_core

pred rule {
  some f: Facility, wp: WavePool, c: Patron, a: Adult |
    wp in f.zones and
    c.age < 18 and
    c.heightInches < 48 and
    c.chaperoneAdult = a and
    c.inWater = wp and
    a.inWaterSupervising = True and
    a.withinArmsReachOfWard = False and
    c.wearsUSCGLifeJacket = False
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
