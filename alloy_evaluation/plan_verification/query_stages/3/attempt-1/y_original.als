open safety_protocol_core

pred rule {
  some b: Patron, m: Adult, f: Adult, p: Facility |
    b.age < 12 and
    b.wearsUSCGLifeJacket = True and
    m.inWaterSupervising = True and
    b.chaperoneAdult = m and
    f != m and
    b.chaperoneAdult != f
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
