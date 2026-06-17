webapp front, with backend

svelte, fastapi python

tool to study thermal properties of building, house,

simple, aka not a full simulation profesional tool
more like a webapp assistant, to get the order of magnitudes

RC lumped model

The user builds, aka describe, a room:

- dimension, orientation
- walls: layer stack, thickness, material
- floor and ceiling
- windows
- heat and cooling input (hvac, heater)
- adjacent rooms
- other ?

- set a time range: week, month or a year

- Weather data (T°, solar radiation, wind?) are provided by the user, or fetched

Then the model compute:

- indoor temperature (30min steps)
- a summary of the thermal properties of the room (TBD...)

The user provide a temperature measurement, (+in futur energy measurement...)
then parameters are estimated (fit, mcmc)

- User also could input the uncertainity on each parameter (Baysian estimation)

there is 3 data structure:

- Physical description of the house elements (geometry, materials)
- minimal lumped model: reduced model used for parameter estimation identification (elements are grouped)
- atomic RC model: the one used by the solver (node as mass, links as resistor)

the goal is to provide to the user a very simple tool to think about the thermal props of his house:
for instance help him answer question like:

- What if I use a external shutter on this window ? how much make it a difference in T° ?
- what if I isolated this wall ? or should i better focus on the window frame ?
- What the tradoff between summer and winter comfort ?

it should be accessible to a non expert, ideally
