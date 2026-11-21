"""Frame-rate-independent animation state. Short attention bursts leave room for idle life."""

import math
import random


class Behavior:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.now = 0.0
        self.look_x = 0.0
        self.look_y = 0.0
        self.mood = "idle"
        self.until = 0.0
        self.next_event = 3.0
        self.blink_at = 2.0
        self.blink = 0.0
        self.attention_until = 0.0
        self.last_mouse = None
        self.idle_target = (0.0, 0.0)
        self.busy = False
        self.speaking = False
        self.music = False
        self.beat = 0.0
        self.energy = 0.0
        self.low_battery = False

    def emotion(self, name, duration=3):
        self.mood = name
        self.until = self.now + duration

    def update(self, dt, mouse=None, energy=0.0):
        dt = max(0.0, min(dt, 0.1))
        self.now += dt
        t = self.now
        if mouse is not None and (self.last_mouse is None or math.dist(mouse, self.last_mouse) > 0.04):
            self.last_mouse = mouse
            self.attention_until = t + 1.8
        if self.until <= t and self.mood != "idle":
            self.mood = "idle"
        if not self.busy and not self.speaking and t >= self.next_event:
            self.next_event = t + self.rng.uniform(5, 10)
            self.emotion(
                self.rng.choice(["wink", "curious", "look", "sleep" if self.low_battery else "surprise"]),
                self.rng.uniform(1.5, 3.2),
            )
            self.idle_target = (self.rng.uniform(-0.85, 0.85), self.rng.uniform(-0.4, 0.4))
        target = mouse if mouse is not None and t < self.attention_until else self.idle_target
        if self.busy:
            target = (math.sin(t * 2) * 0.5, -0.15)
        k = 1 - math.exp(-dt * 8)
        self.look_x += (max(-1, min(1, target[0])) - self.look_x) * k
        self.look_y += (max(-1, min(1, target[1])) - self.look_y) * k
        if t >= self.blink_at:
            self.blink_at = t + self.rng.uniform(3, 6)
            self.blink = 0.16
        self.blink = max(0, self.blink - dt)
        self.energy = max(0, min(1, energy))
        self.beat += (self.energy - self.beat) * (1 - math.exp(-dt * (32 if self.energy > self.beat else 8)))

    def eyes(self):
        t = self.now
        h = 1.0
        other = 1.0
        tilt = 0
        if self.mood == "sleep":
            h = 0.16 + 0.025 * math.sin(t * 2)
            other = h
        elif self.mood == "wink":
            h = 0.12 if math.sin(t * 8) > 0 else 0.8
        elif self.mood == "curious":
            h = 1.15
            other = 0.65
        elif self.mood == "surprise":
            h = 1.3
            other = 1.3
        elif self.mood == "angry":
            h = 0.5
            other = 0.5
            tilt = 12
        if self.blink > 0:
            h *= 0.12
            other *= 0.12
        scale = 1 + min(0.26, self.beat * 0.8) if self.music else 1
        if self.speaking:
            scale *= 1 + 0.065 * math.sin(t * 18) + 0.025 * math.sin(t * 31)
        shake = math.sin(t * 35) * 1.5 if self.mood == "angry" else 0
        return h, other, tilt, scale, shake
