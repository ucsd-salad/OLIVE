open safety_protocol_core
open query_ext

pred rule {
  some f: Facility, p: Patron |
    f.lightningDetected = False and
    f.lastThunderMinutesAgo = 30 and
    f.(QueryExt.deckClearanceOrdered) = True and
    p.(QueryExt.patronObjecting) = True
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
