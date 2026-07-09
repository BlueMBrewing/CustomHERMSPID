# cbpi4-PIDHermsMashDelta

A CraftBeerPi4 Kettle Logic plugin for HERMS systems, based on the design of
[PiBrewing/cbpi4-PIDHerms](https://github.com/PiBrewing/cbpi4-PIDHerms), rewritten
to run on Python 3.13 (Raspberry Pi 5) with no external PID dependency.

## How it works

- **Mash sensor is the process variable.** The Kettle you attach this logic to
  should have its **Sensor** set to your mash-tun probe, and its **Actor** set to
  your HLT heating element. The PID loop drives HLT heater power to bring the
  *mash* temperature to the Kettle's target temperature — exactly like a normal
  Kettle PID, just with the heater physically located in the HLT.
- **HLT sensor is a safety monitor**, configured separately as a plugin property.
  It is *not* the PID's input — it only guards against the HLT running away from
  the mash (which risks scorching wort / stuck sparges / uneven mash temps).
- **Delta protection:** every cycle, the plugin computes
  `delta = HLT_temp - Mash_target_temp`.
  - If `delta > DeltaTemp`, the heater is forced **off** immediately (independent
    of what the PID is requesting) and the PID's integral term is reset so it
    doesn't "remember" a large error while the heater was disabled.
  - The heater stays off until `delta <= (DeltaTemp - ResumeHysteresis)`, at
    which point PID control resumes automatically. The hysteresis prevents
    rapid on/off chatter right at the boundary.

## Parameters

| Setting | Description |
|---|---|
| P | Proportional gain of the Mash PID |
| I | Integral gain of the Mash PID |
| D | Derivative gain of the Mash PID |
| Max_Output | Max heater power (%) the PID may request |
| HLT_Sensor | Sensor that reads HLT (HERMS coil) temperature |
| DeltaTemp | Max allowed `HLT temp - Mash target temp` before the heater is cut |
| ResumeHysteresis | Delta must drop this far below DeltaTemp before resuming |
| SampleTime | PID recalculation interval, in seconds (2 or 5) |

Tuning tip: you can derive P/I/D starting values the same way as for the
original plugin — e.g. with a PID autotune plugin — then adjust `DeltaTemp`
based on how aggressively your HLT can outrun your coil's ability to transfer
heat into the mash.

## Installation

On your Raspberry Pi 5, from your CBPi4 install directory (adjust the venv
path if yours differs):

```bash
sudo pip3 install ./cbpi4-PIDHermsMashDelta --break-system-packages
# or, if CBPi4 is in a virtualenv:
source ./venv/bin/activate
pip3 install ./cbpi4-PIDHermsMashDelta
```

Then enable it like any other plugin:

```bash
cbpi add cbpi4-PIDHermsMashDelta
```

Restart CBPi4, then go to **Hardware/Kettle configuration** in the UI, create
or edit a Kettle, set:
- Sensor → your mash probe
- Actor → your HLT element
- Logic → `PIDHermsMashDelta`

...and fill in the plugin properties (P/I/D, HLT_Sensor, DeltaTemp, etc.) in
the Kettle Logic config panel.

## Raspberry Pi 5 / Python 3.13 notes

- This plugin itself has **no external dependencies** beyond CBPi4 core
  (`asyncio`, `logging` only), so there's nothing extra to install for the
  logic to run under Python 3.13.
- The Pi 5 uses a different GPIO chip (RP1) than earlier Pi models. The
  classic `RPi.GPIO` library **does not work on Pi 5**. If your *actor* or
  *sensor* plugins (e.g. GPIO relay actors, DS18B20/OneWire, PT100/1000
  boards) depend on `RPi.GPIO`, install `rpi-lgpio` (a drop-in replacement)
  or switch to plugins/backends built on `lgpio` / `gpiozero` with the
  `lgpio` pin factory. This is unrelated to this Kettle Logic plugin, but
  it's the most common thing that breaks a fresh CBPi4-on-Pi5 setup.
- Make sure CBPi4 core itself is a recent enough version to run cleanly on
  Python 3.13 — check the CBPi4 release notes if you hit `asyncio` deprecation
  errors at startup.

## Safety note

This delta-cutoff is a *process* safety feature (protecting your mash/wort
quality), not an electrical/thermal-runaway safety system. Keep your normal
hardware-level safeguards (thermal fuses/cutoffs on heating elements, GFCI,
etc.) in place regardless of this plugin's logic.
