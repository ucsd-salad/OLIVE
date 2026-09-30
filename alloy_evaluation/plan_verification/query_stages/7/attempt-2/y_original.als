open safety_protocol_core
open query_ext

pred rule {
  some g: Patron, f: Facility, z: WaterZone, d: DiarrhealIncident |
    g.inWater = z and
    z in f.zones and
    z = f.(QueryExt.mainPool) and
    f.activeBiohazardIncident = d and
    d.minutesSinceIncident = 60
}

run Satisfiable { rule } for 5 but 9 Int
run Refutable { not rule } for 5 but 9 Int
