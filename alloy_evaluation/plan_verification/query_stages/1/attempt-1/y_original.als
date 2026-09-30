open safety_protocol_core

pred rule {
  some p: Patron, z: ShallowZone |
    p.age = 13 and
    p.inWater = z and
    DivingInShallowWater in p.currentBehaviors
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
