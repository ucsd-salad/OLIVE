open safety_protocol_core
open query_ext

pred rule {
  some m: Patron, s: Spa, a: Adult |
    m.age = 1 and
    m.(QueryExt.patronAgeMonths) = 16 and
    m.inWater = s and
    a.inWaterSupervising = True and
    m.chaperoneAdult = a and
    s.(QueryExt.spaMinimumAge) > m.age and
    m.(QueryExt.submergedIn) = s and
    m.wearsUSCGLifeJacket = False
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
