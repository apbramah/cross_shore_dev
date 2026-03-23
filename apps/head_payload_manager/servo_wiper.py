from machine import Pin, PWM


class WiperServo:
    def __init__(self, pin=15, freq_hz=50, min_us=500, max_us=2500):
        self._min_us = int(min_us)
        self._max_us = int(max_us)
        self._pwm = PWM(Pin(int(pin)))
        self._pwm.freq(int(freq_hz))
        self._angle_deg = 0
        self.set_angle(0)

    def set_angle(self, angle_deg):
        a = int(angle_deg)
        if a < 0:
            a = 0
        if a > 180:
            a = 180
        self._angle_deg = a
        pulse_us = self._min_us + ((self._max_us - self._min_us) * a) // 180
        duty_u16 = (pulse_us * 65535) // 20000  # 20ms period at 50Hz
        self._pwm.duty_u16(int(duty_u16))

    def get_angle(self):
        return int(self._angle_deg)
