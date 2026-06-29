"""
Step 0 validation: eyeball plots for the forward simulation.

(a) T_ext +10 °C step  → caravan vs heavy T_room overlay (shows thermal inertia lag)
(b) Solar pulse        → T_room rise and relax (SolarGain path)

Run with:  uv run python notebooks/step0_validation.py
"""

import math

import matplotlib.pyplot as plt
import numpy as np

from thnodes import (
    Assembler,
    DirectLoss,
    HeavyWall,
    Layer,
    OuterWall,
    RoomMass,
    SolarGainModule,
    Window,
    forward_sim,
)

FLOOR_AREA = 20.0
DT = 3600.0
N_HOURS = 72


def build_caravan():
    win = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
    wall = OuterWall(area=10.0, orientation="S", layers=[Layer("insulation_mineral_wool", 0.1)])
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=FLOOR_AREA))
    asm.add_module(DirectLoss(), elements=[wall, win])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build()


def build_heavy():
    heavy = OuterWall(
        area=10.0, orientation="S",
        layers=[Layer("concrete", 0.2), Layer("insulation_mineral_wool", 0.1)],
    )
    win = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=FLOOR_AREA))
    asm.add_module(DirectLoss(), elements=[win])
    asm.add_module(HeavyWall(), elements=[heavy])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build()


def prior_means(sys):
    return {p: math.exp(mu) for p, (mu, _) in sys.priors.items()}


sys_c = build_caravan()
sys_h = build_heavy()
params_c = prior_means(sys_c)
params_h = prior_means(sys_h)

t_span = (0.0, N_HOURS * DT)
hours = np.arange(N_HOURS + 1)

# ── (a) T_ext step response ────────────────────────────────────────────────────

T_init = 15.0
T_ext_step = np.full(N_HOURS + 2, 25.0)  # +10 °C step from start
G_zero = np.zeros(N_HOURS + 2)

sigs_step = {"T_ext": T_ext_step, "G_sol": G_zero}

t_c, x_c = forward_sim(sys_c, sigs_step, t_span, np.array([T_init]), params_c, dt=DT)
t_h, x_h = forward_sim(sys_h, sigs_step, t_span, np.array([T_init, T_init]), params_h, dt=DT)

T_room_c = x_c[0]
T_room_h = x_h[-1]   # T_room is last state
T_wall_h = x_h[0]

# ── (b) Solar pulse ────────────────────────────────────────────────────────────

T_flat = np.full(N_HOURS + 2, 15.0)  # flat T_ext, no conduction gradient
G_pulse = np.zeros(N_HOURS + 2)
G_pulse[8:19] = 600.0  # W/m² daytime boxcar

sigs_pulse = {"T_ext": T_flat, "G_sol": G_pulse}

_, x_cp = forward_sim(sys_c, sigs_pulse, t_span, np.array([T_init]), params_c, dt=DT)
_, x_hp = forward_sim(sys_h, sigs_pulse, t_span, np.array([T_init, T_init]), params_h, dt=DT)

T_room_cp = x_cp[0]
T_room_hp = x_hp[-1]

# ── plots ──────────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(2, 1, figsize=(10, 8))

ax = axes[0]
ax.plot(hours, T_room_c, label="Caravan (T_room)", color="steelblue")
ax.plot(hours, T_room_h, label="Heavy (T_room)", color="firebrick")
ax.plot(hours, T_wall_h, label="Heavy (T_wall)", color="firebrick", linestyle="--", alpha=0.6)
ax.axhline(25.0, color="gray", linestyle=":", label="T_ext = 25 °C")
ax.set_xlabel("Time [h]")
ax.set_ylabel("Temperature [°C]")
ax.set_title("(a) T_ext +10 °C step: caravan vs heavy — heavy wall lags")
ax.legend()
ax.grid(True, alpha=0.3)

ax = axes[1]
ax2 = ax.twinx()
ax.plot(hours, T_room_cp, label="Caravan (T_room)", color="steelblue")
ax.plot(hours, T_room_hp, label="Heavy (T_room)", color="firebrick")
ax2.fill_between(hours, G_pulse[: N_HOURS + 1], alpha=0.15, color="orange", label="G_sol [W/m²]")
ax2.set_ylabel("G_sol [W/m²]", color="orange")
ax2.tick_params(axis="y", labelcolor="orange")
ax.set_xlabel("Time [h]")
ax.set_ylabel("Temperature [°C]")
ax.set_title("(b) Solar pulse hours 8–18: T_room rises then relaxes")
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("notebooks/step0_validation.png", dpi=120)
plt.show()
print("Saved: notebooks/step0_validation.png")
