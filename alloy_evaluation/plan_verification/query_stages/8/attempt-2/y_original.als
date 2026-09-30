open safety_protocol_core
open query_ext

pred rule {
  some p: Patron, f: Facility |
    p in f.(QueryExt.entrance) and
    p.(QueryExt.cooler) = p and
    p.(QueryExt.containsOutsideFood) = 1 and
    p.(QueryExt.containsAlcohol) = 1
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
