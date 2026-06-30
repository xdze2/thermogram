elements = geometrical and physical description of a building/room

- IndoorMass, OuterWall, Window, Partition, Floor, HeatSource

Each element type are assigned to one or many Topology module,
aka channels,
for instance Window: DirectSolarGain + DirectConduction

Light or Heavy wall should actually be two different elements type...
with a tool to transform one to another ?

Elements are also assigned signals: measure, or inputs

Module[Signal] are unique and regroup all corresponding element's channel

(could be generalized to Module[src, Signals] for multiroom)

The goals of this are:

- to build the minimal model RC topology
- to derive priors for RC parameters from the physical model

Modules could:

- have parameters, for Nbr nodes for heavywall
- be duplicated, for instance for inner-mass: fast vs slow mass ?

About derived signal, i am not sure,
could be integrated in the RC topology, if linear

or hard coded, as for SolarGain\_{orientation} ?

or T_soil, but this will require a preprocessing step
(importing yearly data)
