open safety_protocol_core

pred rule {
  some p: Patron |
    p.age < 18 and
    p.onDeck = True and
    p.currentBehaviors = Hyperventilation and
    p.inWater in DeepZone
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
