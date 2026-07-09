import asyncio
import logging

from cbpi.api import *
from cbpi.api.dataclasses import NotificationType


class MashPID:
    """
    Small, dependency-free discrete PID controller.
    - Integral term is clamped to the output range to avoid windup.
    - reset() clears accumulated state (used whenever the delta-safety
      lockout engages so the PID doesn't "remember" a huge error while
      the heater was forced off).
    """

    def __init__(self, p, i, d, sample_time=5, output_limits=(0, 100)):
        self.Kp = p
        self.Ki = i
        self.Kd = d
        self.sample_time = sample_time
        self.min_output, self.max_output = output_limits
        self._integral = 0.0
        self._last_input = None

    def reset(self):
        self._integral = 0.0
        self._last_input = None

    def compute(self, setpoint, current_value):
        error = setpoint - current_value

        # Integral, clamped to output range (anti-windup)
        self._integral += self.Ki * error * self.sample_time
        self._integral = max(self.min_output, min(self.max_output, self._integral))

        # Derivative on measurement (avoids "derivative kick" on setpoint changes)
        derivative = 0.0
        if self._last_input is not None:
            derivative = (current_value - self._last_input) / self.sample_time

        output = (self.Kp * error) + self._integral - (self.Kd * derivative)
        output = max(self.min_output, min(self.max_output, output))

        self._last_input = current_value
        return output


@parameters([
    Property.Number(
        label="P", configurable=True, default_value=60,
        description="Proportional term of the Mash PID"),
    Property.Number(
        label="I", configurable=True, default_value=2,
        description="Integral term of the Mash PID"),
    Property.Number(
        label="D", configurable=True, default_value=0,
        description="Derivative term of the Mash PID"),
    Property.Number(
        label="Max_Output", configurable=True, default_value=100,
        description="Maximum heater power (%) the PID is allowed to request"),
    Property.Sensor(
        label="HLT_Sensor",
        description="Sensor that measures the HLT (HERMS coil) temperature"),
    Property.Number(
        label="DeltaTemp", configurable=True, default_value=10,
        description=("Maximum allowed difference between HLT temperature and the "
                      "Mash target temperature. If HLT temp exceeds "
                      "(Mash target + DeltaTemp), the heater is forced off.")),
    Property.Number(
        label="ResumeHysteresis", configurable=True, default_value=1,
        description=("Delta must drop to (DeltaTemp - this value) before the heater "
                      "is allowed to resume, to prevent rapid on/off cycling at the "
                      "boundary.")),
    Property.Select(
        label="SampleTime", options=[2, 5],
        description="PID recalculation interval in seconds"),
])
class PIDHermsMashDelta(CBPiKettleLogic):
    """
    HERMS Kettle Logic:
      - Process variable (input) = the Kettle's own assigned sensor, which
        should be configured as the MASH sensor. Setpoint = the Kettle's
        target temperature (set as usual from the Kettle UI / brew step).
      - Output = power applied to the Kettle's assigned actor, which should
        be the HLT heating element.
      - Safety: a second, independently-configured HLT sensor is monitored.
        If HLT temperature rises more than DeltaTemp above the Mash target,
        the heater is forced off (and PID state reset) regardless of what
        the PID wants, until HLT temp falls back within
        (DeltaTemp - ResumeHysteresis) of the Mash target, at which point
        normal PID control resumes automatically.
    """

    async def on_start(self):
        self.kettle = self.get_kettle(self.id)
        self.heater = self.kettle.heater
        self.mash_sensor = self.kettle.sensor

        self.p = float(self.props.get("P", 60))
        self.i = float(self.props.get("I", 2))
        self.d = float(self.props.get("D", 0))
        self.max_output = float(self.props.get("Max_Output", 100))
        self.hlt_sensor_id = self.props.get("HLT_Sensor", None)
        self.delta_temp = float(self.props.get("DeltaTemp", 10))
        self.resume_hysteresis = float(self.props.get("ResumeHysteresis", 1))
        self.sample_time = float(self.props.get("SampleTime", 5))

        if self.resume_hysteresis >= self.delta_temp:
            # Guard against a nonsensical config that would make resuming impossible
            self.resume_hysteresis = 0

        self.pid = MashPID(
            self.p, self.i, self.d,
            sample_time=self.sample_time,
            output_limits=(0, self.max_output),
        )

        self.delta_lockout = False

        if not self.hlt_sensor_id:
            logging.warning(
                "PIDHermsMashDelta: No HLT_Sensor configured - running as a plain "
                "mash PID with NO delta safety protection.")

    async def run(self):
        await self.on_start()
        try:
            while self.running:
                target_temp = self.get_kettle_target_temp(self.id)
                mash_reading = self.get_sensor_value(self.mash_sensor)
                mash_temp = mash_reading.get("value") if mash_reading else None

                if target_temp is None or mash_temp is None:
                    await asyncio.sleep(self.sample_time)
                    continue

                target_temp = float(target_temp)
                mash_temp = float(mash_temp)

                hlt_temp = None
                if self.hlt_sensor_id:
                    hlt_reading = self.get_sensor_value(self.hlt_sensor_id)
                    if hlt_reading is not None and hlt_reading.get("value") is not None:
                        hlt_temp = float(hlt_reading.get("value"))

                # --- Delta safety check ---
                if hlt_temp is not None:
                    delta = hlt_temp - target_temp

                    if not self.delta_lockout and delta > self.delta_temp:
                        self.delta_lockout = True
                        self.pid.reset()
                        await self.actor_off(self.heater)
                        await self.cbpi.notify(
                            "HERMS Delta Protection",
                            "HLT temp {:.1f} is {:.1f} above Mash target {:.1f} "
                            "(limit {:.1f}). Heater disabled.".format(
                                hlt_temp, delta, target_temp, self.delta_temp),
                            NotificationType.WARNING,
                        )

                    elif self.delta_lockout and delta <= (self.delta_temp - self.resume_hysteresis):
                        self.delta_lockout = False
                        await self.cbpi.notify(
                            "HERMS Delta Protection",
                            "HLT temp back within delta ({:.1f}). Resuming PID control.".format(delta),
                            NotificationType.INFO,
                        )

                # --- Apply control ---
                if self.delta_lockout:
                    await self.actor_off(self.heater)
                else:
                    power = self.pid.compute(target_temp, mash_temp)
                    power = round(power)
                    if power > 0:
                        await self.actor_set_power(self.heater, power)
                        await self.actor_on(self.heater)
                    else:
                        await self.actor_off(self.heater)

                await asyncio.sleep(self.sample_time)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error("PIDHermsMashDelta Error: {}".format(e))
        finally:
            self.running = False
            try:
                await self.actor_off(self.heater)
            except Exception:
                pass


def setup(cbpi):
    cbpi.plugin.register("PIDHermsMashDelta", PIDHermsMashDelta)
