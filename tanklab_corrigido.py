"""Tank Lab — duelo de artilharia 2D com Arcade 3.3.3."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import arcade
from PIL import Image, ImageDraw, ImageFilter


WIDTH, HEIGHT = 1280, 800
GRAVITY = 9.81
WORLD_WIDTH = 106.0
PROJECTILE_RADIUS = 0.22
TANK_HEIGHT = 3.2
BARREL_LENGTH = 3.2
BARREL_PIVOT = 2.2

WALL_LEFT, WALL_RIGHT = 49.0, 56.0
LAYER_HEIGHT = 6.0
MOVE_DISTANCE = 8.0
ARMOR_MULTIPLIER = 0.65
BASE_DAMAGE, MAX_BONUS, BONUS_PER_METER = 26, 22, 0.27
ANGLE_MIN, ANGLE_MAX = 10.0, 85.0
SPEED_MIN, SPEED_MAX = 14.0, 60.0

BG = (13, 19, 22)
PANEL = (23, 32, 35)
INSET = (18, 25, 28)
LINE = (53, 67, 68)
WHITE = (239, 238, 222)
MUTED = (169, 182, 173)
TEAL = (115, 222, 186)
RED = (246, 145, 120)
GOLD = (246, 201, 119)
TEAM_COLORS = (TEAL, RED)

FONT = ("Barlow", "Segoe UI", "DejaVu Sans")
TITLE_FONT = ("Barlow Condensed", "Segoe UI", "DejaVu Sans")
MONO = ("IBM Plex Mono", "Consolas", "DejaVu Sans Mono")

ARENA = (24, 202, 888, 492)
GROUND_Y = 269
SKY_PIXELS = 377
WORLD_X = 48
PIXELS_X = 840 / WORLD_WIDTH

ANGLE_TRACK = (46, 132, 380)
SPEED_TRACK = (480, 132, 406)
BUTTONS = {
    "left": ((46, 61, 158, 42), "MOVER ←  [A]"),
    "right": ((215, 61, 158, 42), "MOVER →  [D]"),
    "fire": ((390, 61, 292, 42), "DISPARAR  [ESPAÇO]"),
    "pause": ((699, 61, 187, 42), "PAUSAR  [P]"),
}


@dataclass(frozen=True)
class Difficulty:
    label: str
    guide: float
    angle_step: int
    angle_error: float
    speed_error: float
    choice_pool: int
    move_chance: float
    time_cost: float


LEVELS = (
    Difficulty("Fácil", 2.00, 10, 5.8, 3.20, 8, 1.23, 2.15),
    Difficulty("Normal", 1.40, 5, 3.1, 2.95, 4, 0.53, 1.65),
    Difficulty("Difícil", 0.10, 1, 0.4, 0.18, 0.12, 0.05, 0.40),
)


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass
class Tank:
    x: float
    hp: int = 100
    angle: float = 52.0
    speed: float = 27.3
    armored: bool = False


@dataclass(frozen=True)
class Shot:
    x0: float
    y0: float
    vx: float
    vy0: float
    angle: float
    speed: float
    side: int

    @property
    def peak_time(self):
        return self.vy0 / GRAVITY

    @property
    def peak(self):
        return self.y(self.peak_time)

    def y(self, t):
        return self.y0 + self.vy0 * t - GRAVITY * t * t / 2

    def position(self, t):
        return self.x0 + self.vx * t, self.y(t)

    def fall(self, t):
        # A distância de queda começa no vértice da parábola.
        falling_time = max(0, t - self.peak_time)
        return GRAVITY * falling_time ** 2 / 2


@dataclass(frozen=True)
class Contact:
    kind: str
    time: float
    x: float
    y: float


def launch(tank_x, side, angle, speed):
    theta = math.radians(angle)
    facing = 1 if side == 0 else -1
    horizontal = facing * math.cos(theta)
    vertical = math.sin(theta)
    return Shot(
        tank_x + BARREL_LENGTH * horizontal,
        BARREL_PIVOT + BARREL_LENGTH * vertical,
        speed * horizontal,
        speed * vertical,
        angle,
        speed,
        side,
    )


def descending_time(shot, height):
    discriminant = shot.vy0 ** 2 + 2 * GRAVITY * (shot.y0 - height)
    if discriminant < 0:
        return math.inf
    return (shot.vy0 + math.sqrt(discriminant)) / GRAVITY


def contact_with_box(shot, left, right, top, deadline):
    """Objetos apoiados no chão. O instante de impacto vem da parábola."""
    r = PROJECTILE_RADIUS
    a = (left - r - shot.x0) / shot.vx
    b = (right + r - shot.x0) / shot.vx
    start = max(0, min(a, b))
    end = min(deadline, max(a, b))
    if start > end:
        return math.inf

    ceiling = top + r
    if shot.y(start) <= ceiling:
        return start

    crossing = descending_time(shot, ceiling)
    return crossing if start <= crossing <= end else math.inf


def first_contact(shot, tanks, wall_layers):
    """O tiro, o bot e o guia compartilham a mesma função de colisão."""
    time = descending_time(shot, PROJECTILE_RADIUS)
    kind = "ground"

    edge = WORLD_WIDTH if shot.side == 0 else 0
    boundary_time = (edge - shot.x0) / shot.vx
    if boundary_time < time:
        time, kind = boundary_time, "outside"

    if wall_layers:
        wall_time = contact_with_box(
            shot, WALL_LEFT, WALL_RIGHT, wall_layers * LAYER_HEIGHT, time
        )
        if wall_time <= time:
            time, kind = wall_time, "wall"

    target = tanks[1 - shot.side]
    target_time = contact_with_box(
        shot, target.x - 3, target.x + 3, TANK_HEIGHT, time
    )
    if target_time <= time:
        time, kind = target_time, "tank"

    x, y = shot.position(time)
    return Contact(kind, time, x, y)


def raw_damage(fall):
    return round(BASE_DAMAGE + min(MAX_BONUS, BONUS_PER_METER * fall))


def damage_to(shot, contact, tank, side):
    if contact.kind == "outside":
        return 0

    force = raw_damage(shot.fall(contact.time))
    direct = contact.kind == "tank" and side != shot.side
    if not direct:
        distance = math.hypot(tank.x - contact.x, 1.6 - contact.y)
        force *= 0.55 * max(0, 1 - distance / 7)

    if tank.armored:
        force *= ARMOR_MULTIPLIER
    return round(force)


class Game:
    def __init__(self, level=1):
        self.level = level
        self.rng = random.Random()
        self.tanks = [Tank(14), Tank(92)]
        self.layers = 3
        self.turn, self.number = 0, 1
        self.phase = "aim"
        self.timer = 0.0
        self.shot = None
        self.contact = None
        self.t = 0.0
        self.damage = [0, 0]
        self.moves = [0, 0]
        self.shots = [0, 0]
        self.hits = [0, 0]
        self.move_from = self.move_to = 0.0
        self.cpu_last_moved = False
        self.winner = None
        self.message = "Ajuste o canhão e escolha mover ou disparar."

    @property
    def ready(self):
        return self.turn == 0 and self.phase == "aim"

    def preview(self, side=0):
        tank = self.tanks[side]
        return launch(tank.x, side, tank.angle, tank.speed)

    def aim(self, angle, speed):
        if self.ready:
            self.tanks[0].angle = clamp(angle, ANGLE_MIN, ANGLE_MAX)
            self.tanks[0].speed = clamp(speed, SPEED_MIN, SPEED_MAX)

    def destination(self, side, direction):
        low, high = (8, 42) if side == 0 else (63, 98)
        return clamp(self.tanks[side].x + MOVE_DISTANCE * direction, low, high)

    def move(self, side, direction):
        if side != self.turn or self.phase not in ("aim", "cpu"):
            return False

        tank = self.tanks[side]
        destination = self.destination(side, direction)
        if destination == tank.x:
            self.message = "Limite de movimento deste lado da arena."
            return False

        self.move_from, self.move_to = tank.x, destination
        tank.armored = True
        self.moves[side] += 1
        self.phase, self.timer = "moving", 0.0
        name = "Você" if side == 0 else "A CPU"
        self.message = f"{name} reposicionou o tanque e ativou a blindagem."
        return True

    def fire(self, side):
        if side != self.turn or self.phase not in ("aim", "cpu"):
            return False

        self.shot = self.preview(side)
        self.contact = first_contact(self.shot, self.tanks, self.layers)
        self.shots[side] += 1
        self.t = 0.0
        self.damage = [0, 0]
        self.phase, self.timer = "flight", 0.0
        self.message = "Projétil em voo"
        return True

    def settle_impact(self):
        shot, contact = self.shot, self.contact
        for side, tank in enumerate(self.tanks):
            self.damage[side] = damage_to(shot, contact, tank, side)
            tank.hp = max(0, tank.hp - self.damage[side])

        target_side = 1 - shot.side
        if contact.kind == "tank":
            self.hits[shot.side] += 1
            self.message = f"Acerto direto  ·  {self.damage[target_side]} de dano"
            if self.tanks[target_side].armored:
                self.message += "  ·  blindagem absorveu parte"
        elif contact.kind == "wall":
            self.layers -= 1
            self.message = (
                f"Muralha atingida  ·  altura restante {self.layers * LAYER_HEIGHT:g} m"
                if self.layers else "Muralha demolida  ·  caminho aberto"
            )
        elif contact.kind == "outside":
            self.message = "Projétil saiu pela lateral da arena."
        elif any(self.damage):
            self.message = f"Explosão próxima  ·  {self.damage[target_side]} de dano no alvo"
        else:
            self.message = "Impacto no chão. Ajuste a mira na próxima vez."

        self.phase, self.timer = "impact", 0.0

    def end_turn(self):
        if min(tank.hp for tank in self.tanks) == 0:
            self.phase = "over"
            if self.tanks[0].hp > self.tanks[1].hp:
                self.winner = 0
            elif self.tanks[1].hp > self.tanks[0].hp:
                self.winner = 1
            return

        self.turn = 1 - self.turn
        self.number += 1
        self.tanks[self.turn].armored = False
        self.phase = "aim" if self.turn == 0 else "cpu"
        self.timer = 0.0
        self.message = (
            "Ajuste a mira ou se reposicione."
            if self.turn == 0 else "O adversário está escolhendo a jogada."
        )

    def cpu_action(self):
        profile = LEVELS[self.level]
        target, cpu = self.tanks
        choices = []

        for angle in range(26, int(ANGLE_MAX) + 1, profile.angle_step):
            theta = math.radians(angle)
            origin = launch(cpu.x, 1, angle, SPEED_MIN)
            dx = origin.x0 - target.x
            dy = 1.6 - origin.y0

            # Isola v₀ em y = y₀ + dx·tan(θ) − g·dx²/(2·v₀²·cos²(θ)).
            denominator = 2 * math.cos(theta) ** 2 * (dx * math.tan(theta) - dy)
            if denominator <= 0:
                continue

            speed = math.sqrt(GRAVITY * dx * dx / denominator)
            if not SPEED_MIN <= speed <= SPEED_MAX:
                continue

            shot = launch(cpu.x, 1, angle, speed)
            contact = first_contact(shot, self.tanks, self.layers)
            damage = damage_to(shot, contact, target, 0)
            self_damage = damage_to(shot, contact, cpu, 1)
            wall_value = 5 if contact.kind == "wall" else 0
            score = damage - 1.5 * self_damage + wall_value
            score -= profile.time_cost * contact.time
            choices.append((score, angle, speed))

        choices.sort(reverse=True)
        chance = profile.move_chance
        if cpu.hp <= 42 and self.damage[1] >= 30:
            chance = max(chance, 0.32)

        if not self.cpu_last_moved and self.rng.random() < chance:
            danger_x = self.contact.x if self.contact else target.x
            direction = max(
                (-1, 1),
                key=lambda d: abs(self.destination(1, d) - danger_x)
                if self.destination(1, d) != cpu.x else -1,
            )
            if self.move(1, direction):
                self.cpu_last_moved = True
                return

        if choices:
            _, angle, speed = self.rng.choice(choices[:profile.choice_pool])
        else:
            angle, speed = 52, 27.3

        angle_error = profile.angle_error * max(
            0.28, math.cos(math.radians(angle)) / 0.707
        )
        cpu.angle = clamp(
            angle + self.rng.uniform(-angle_error, angle_error),
            ANGLE_MIN, ANGLE_MAX,
        )
        cpu.speed = clamp(
            speed + self.rng.uniform(-profile.speed_error, profile.speed_error),
            SPEED_MIN, SPEED_MAX,
        )
        self.cpu_last_moved = False
        self.fire(1)

    def update(self, dt, playback):
        self.timer += dt
        if self.phase == "moving":
            progress = min(1, self.timer / 0.48)
            easing = progress ** 2 * (3 - 2 * progress)
            self.tanks[self.turn].x = self.move_from + (self.move_to - self.move_from) * easing
            if progress == 1:
                self.end_turn()
        elif self.phase == "cpu" and self.timer >= 0.65:
            self.cpu_action()
        elif self.phase == "flight":
            self.t = min(self.contact.time, self.t + dt * playback)
            if self.t == self.contact.time:
                self.settle_impact()
        elif self.phase == "impact" and self.timer >= 0.9:
            self.end_turn()


def fill(box, color):
    x, y, width, height = box
    if width > 0 and height > 0:
        arcade.draw_rect_filled(arcade.LBWH(x, y, width, height), color)


def panel(box, color=PANEL, border=LINE):
    x, y, width, height = box
    fill((x - 1, y - 1, width + 2, height + 2), border)
    fill(box, color)


def contains(box, x, y):
    left, bottom, width, height = box
    return left <= x <= left + width and bottom <= y <= bottom + height


def make_arena_texture():
    """Pinta o cenário uma vez e o reutiliza como uma textura."""
    width, height = ARENA[2:]
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    sky_top = (17, 25, 34)
    sky_bottom = (104, 70, 53)

    for y in range(height):
        weight = (y / height) ** 1.45
        shade = tuple(round(a + (b - a) * weight) for a, b in zip(sky_top, sky_bottom))
        draw.line((0, y, width, y), (*shade, 255))

    glow = Image.new("RGBA", image.size)
    lamp = ImageDraw.Draw(glow)
    lamp.ellipse((536, 60, 874, 384), fill=(246, 164, 97, 85))
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(46)))
    draw = ImageDraw.Draw(image)
    draw.ellipse((682, 113, 765, 196), fill=(233, 184, 121, 255))

    ridges = [
        ((72, 58, 54), [(0, 333), (86, 279), (119, 254), (191, 268),
                       (253, 314), (310, 291), (407, 241), (449, 248),
                       (519, 314), (607, 276), (688, 292), (773, 243), (888, 313)]),
        ((50, 50, 47), [(0, 346), (111, 353), (204, 307), (261, 321),
                       (311, 372), (392, 336), (480, 343), (571, 291),
                       (640, 317), (727, 366), (810, 313), (888, 340)]),
        ((35, 43, 42), [(0, 385), (159, 352), (241, 389), (355, 366),
                       (457, 379), (551, 350), (644, 385), (778, 362), (888, 384)]),
    ]
    for color, points in ridges:
        draw.polygon(points + [(width, height), (0, height)], fill=(*color, 255))

    floor = height - (GROUND_Y - ARENA[1])
    draw.rectangle((0, floor, width, height), fill=(37, 38, 34))
    draw.rectangle((0, floor, width, floor + 2), fill=(111, 94, 69))

    rng = random.Random(22)
    grain = Image.new("RGBA", image.size)
    dust = ImageDraw.Draw(grain)
    for _ in range(1200):
        x, y = rng.randrange(width), rng.randrange(65, height)
        alpha = rng.randint(5, 22)
        dust.line((x, y, x + rng.randint(0, 3), y), fill=(231, 187, 135, alpha))
    for x in range(36, width, 60):
        dust.line((x, floor + 12, x + 20, height), fill=(213, 169, 104, 18))

    return arcade.Texture(Image.alpha_composite(image, grain))


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    duration: float
    size: float
    color: tuple[int, int, int]


class TankLab(arcade.Window):
    def __init__(self):
        super().__init__(
            1088, 680, "Tank Math | Desfiladeiro",
            resizable=True, update_rate=1 / 60, draw_rate=1 / 60, vsync=True,
        )
        self.camera = arcade.Camera2D(
            position=(0, 0), projection=arcade.LRBT(0, WIDTH, 0, HEIGHT)
        )
        self.fit(self.width, self.height)
        self.backdrop = make_arena_texture()
        self.labels = {}
        self.held = set()
        self.pointer = (-1, -1)
        self.drag = None
        self.help_open = False
        self.paused = False
        self.show_guide = True
        self.playback = 2
        self.muted = False
        self.particles = []
        self.fx_rng = random.Random()
        self.audio_clips = {}
        for event, filename in (
            ("fire", "hit4.wav"),
            ("impact", "explosion1.wav"),
            ("wall", "rockHit2.wav"),
        ):
            try:
                self.audio_clips[event] = arcade.load_sound(f":resources:/sounds/{filename}")
            except Exception:
                pass
        self.new_game(1)

    def new_game(self, level):
        self.game = Game(level)
        self.hp_display = [100.0, 100.0]
        self.sky = 50.0
        self.paused = self.help_open = False
        self.particles.clear()
        self.held.clear()
        self.drag = None

    def fit(self, width, height):
        self.ratio = max(0.001, min(width / WIDTH, height / HEIGHT))
        self.ox = (width - WIDTH * self.ratio) / 2
        self.oy = (height - HEIGHT * self.ratio) / 2
        self.camera.viewport = arcade.LBWH(
            self.ox, self.oy, WIDTH * self.ratio, HEIGHT * self.ratio
        )

    def on_resize(self, width, height):
        super().on_resize(width, height)
        if hasattr(self, "camera"):
            self.fit(width, height)

    def text(
        self, key, value, x, y, size=12, color=WHITE,
        *, bold=False, anchor="left", font=FONT,
    ):
        value = str(value)
        if key not in self.labels:
            self.labels[key] = arcade.Text(
                value, x, y, color, size,
                bold=bold, anchor_x=anchor, font_name=font,
            )
        label = self.labels[key]
        if label.text != value:
            label.text = value
        if label.x != x:
            label.x = x
        if label.y != y:
            label.y = y
        label.color = color
        label.draw()

    @property
    def world_scale(self):
        return min(PIXELS_X, SKY_PIXELS / self.sky)

    def world(self, x, y):
        scale = self.world_scale
        center_x = WORLD_X + PIXELS_X * WORLD_WIDTH / 2
        return center_x + (x - WORLD_WIDTH / 2) * scale, GROUND_Y + y * scale

    def current_trajectory(self):
        game = self.game
        if game.phase in ("flight", "impact", "over") and game.shot:
            return game.shot, game.contact, game.t, False
        shot = game.preview()
        return shot, first_contact(shot, game.tanks, game.layers), 0.0, True

    @staticmethod
    def level_box(index):
        return 920 + index * 108, 722, 100, 34

    def draw_button(self, key, box, label, active=True, accent=False):
        hover = active and contains(box, *self.pointer)
        color = PANEL
        if accent and active:
            color = (255, 222, 157) if hover else GOLD
        elif hover:
            color = (43, 60, 59)
        panel(box, color)
        x, y, width, height = box
        self.text(
            key, label, x + width / 2, y + height / 2 - 5, 11,
            BG if accent and active else WHITE if active else (117, 132, 128),
            bold=True, anchor="center",
        )

    def on_draw(self):
        self.clear(BG)
        self.camera.use()
        shot, contact, t, preview = self.current_trajectory()
        self.draw_header()
        self.draw_arena(shot, contact, t, preview)
        self.draw_math(shot, contact, t, preview)
        self.draw_controls()
        if self.paused or self.help_open or self.game.phase == "over":
            self.draw_overlay()

    def draw_header(self):
        self.text("title", "TANK MATH", 24, 742, 33, GOLD, bold=True, font=TITLE_FONT)
        self.text("map", "DESFILADEIRO", 27, 716, 11, MUTED, bold=True)

        for side, x, name in ((0, 282, "SEU TANQUE"), (1, 574, "ADVERSÁRIO")):
            tank = self.game.tanks[side]
            color = TEAM_COLORS[side]
            self.text(f"name{side}", name, x, 763, 11, color, bold=True)
            self.text(
                f"hp{side}", f"{tank.hp:3d} / 100", x + 235, 763, 11,
                anchor="right", font=MONO,
            )
            fill((x, 737, 235, 12), LINE)
            fill((x, 737, 235 * self.hp_display[side] / 100, 12), color)
            self.text(
                f"armor{side}", "BLINDAGEM ATIVA  −35%" if tank.armored else "",
                x, 715, 9, color, font=MONO,
            )

        self.text("diff", "DIFICULDADE · NOVO DUELO", 920, 770, 10, MUTED, bold=True)
        for index, level in enumerate(LEVELS):
            self.draw_button(
                f"level{index}", self.level_box(index), f"{index + 1}  {level.label}",
                accent=self.game.level == index,
            )

    def draw_arena(self, shot, contact, t, preview):
        game = self.game
        panel(ARENA, INSET)
        arcade.draw_texture_rect(self.backdrop, arcade.LBWH(*ARENA))

        for mx in range(0, 101, 10):
            x, y = self.world(mx, 0)
            arcade.draw_line(x, y, x, y + SKY_PIXELS, (209, 220, 210, 28))
            self.text(f"gridx{mx}", f"{mx}", x, 226, 9, MUTED, anchor="center", font=MONO)

        step = 10 if self.sky <= 75 else 25 if self.sky <= 150 else 50
        for my in range(step, int(self.sky), step):
            _, y = self.world(0, my)
            arcade.draw_line(48, y, 888, y, (209, 220, 210, 28))
            self.text(f"gridy{my}", f"{my} m", 31, y + 4, 9, MUTED, font=MONO)

        fill((24, 656, 888, 38), (20, 28, 31, 242))
        turn = "SUA VEZ" if game.turn == 0 else "VEZ DA CPU"
        if game.phase == "over":
            turn = "FIM DO DUELO"
        self.text("turn", turn, 45, 669, 12, TEAM_COLORS[game.turn], bold=True)
        self.text("status", game.message, 199, 669, 11)
        self.text("round", f"TURNO {game.number:02d}", 888, 669, 9, MUTED,
                  anchor="right", font=MONO)

        self.draw_wall()
        if preview and game.ready and self.show_guide:
            portion = LEVELS[game.level].guide
            for i in range(1, 34):
                time = contact.time * portion * i / 33
                x, y = self.world(*shot.position(time))
                arcade.draw_circle_filled(x, y, 1.9, (*TEAL, 140))
            if portion == 1:
                x, y = self.world(contact.x, contact.y)
                arcade.draw_circle_outline(x, y, 8, TEAL, 1.5)
                arcade.draw_line(x - 11, y, x + 11, y, TEAL, 1)
                arcade.draw_line(x, y - 11, x, y + 11, TEAL, 1)
        elif not preview and t > 0:
            color = TEAM_COLORS[shot.side]
            points = [self.world(*shot.position(t * i / 76)) for i in range(77)]
            arcade.draw_line_strip(points, (*color, 55), 5)
            arcade.draw_line_strip(points, (*color, 198), 1.5)

        for side in (0, 1):
            self.draw_tank(side)

        if game.phase == "flight":
            x, y = self.world(*shot.position(t))
            arcade.draw_circle_filled(x, y, 9, (*GOLD, 60))
            arcade.draw_circle_filled(x, y, 4, (255, 247, 208))

        for spark in self.particles:
            x, y = self.world(spark.x, spark.y)
            if 31 < x < 904 and GROUND_Y - 14 < y < 653:
                fade = spark.life / spark.duration
                arcade.draw_circle_filled(
                    x, y, spark.size * (0.5 + fade / 2), (*spark.color, int(230 * fade))
                )

        if game.phase == "impact" and contact.kind != "outside":
            x, y = self.world(contact.x, contact.y)
            fade = max(0, 1 - game.timer / 0.9)
            arcade.draw_circle_outline(x, y, 7 + 56 * game.timer, (*GOLD, int(180 * fade)), 2)
            for side, amount in enumerate(game.damage):
                if amount:
                    tx, _ = self.world(game.tanks[side].x, 0)
                    self.text(
                        f"damage{side}", f"−{amount}", tx, 318 + game.timer * 22,
                        24, RED, bold=True, anchor="center", font=TITLE_FONT,
                    )

    def draw_wall(self):
        layers = self.game.layers
        if not layers:
            return

        scale = self.world_scale
        left, ground = self.world(WALL_LEFT, 0)
        width = (WALL_RIGHT - WALL_LEFT) * scale
        height = LAYER_HEIGHT * scale
        margin = 0.22 * scale

        for layer in range(layers):
            bottom = ground + layer * height
            fill((left, bottom, width, height), (39, 38, 32))
            fill((left + margin, bottom + margin,
                  width - 2 * margin, height - 2 * margin), (112, 106, 88))
            fill((left + width * 0.78, bottom + margin,
                  width * 0.22 - margin, height - 2 * margin), (78, 76, 63))
            fill((left + margin, bottom + height - 2 * margin,
                  width - 2 * margin, margin), (169, 155, 115))
            for bolt in (left + scale, left + width - scale):
                arcade.draw_circle_filled(bolt, bottom + height / 2, 0.25 * scale, (49, 48, 41))

        self.text("wall_hp", f"MURALHA  {layers}/3", left + width / 2,
                  ground + layers * height + 8, 9, GOLD, anchor="center", font=MONO)

    def draw_tank(self, side):
        tank = self.game.tanks[side]
        color = TEAM_COLORS[side]
        scale = self.world_scale
        x, ground = self.world(tank.x, 0)
        dark = (15, 20, 19)

        arcade.draw_ellipse_filled(x, ground - 0.35 * scale,
                                  8.2 * scale, 1.1 * scale, (13, 19, 18, 160))
        fill((x - 3 * scale, ground + 0.10 * scale, 6 * scale, 1.15 * scale), dark)
        fill((x - 2.75 * scale, ground + 0.25 * scale,
              5.5 * scale, 0.84 * scale), (48, 57, 53))
        for i in range(-2, 3):
            arcade.draw_circle_filled(x + i * 1.08 * scale, ground + 0.67 * scale,
                                      0.34 * scale, (122, 131, 114))

        hull = [self.world(tank.x + dx, y) for dx, y in
                ((-3, 1.15), (-2, 2.42), (2, 2.42), (3, 1.15))]
        arcade.draw_polygon_filled(hull, color)

        px, py = self.world(tank.x, BARREL_PIVOT)
        shot = self.game.preview(side)
        mx, my = self.world(shot.x0, shot.y0)
        arcade.draw_line(px, py, mx, my, dark, 0.88 * scale)
        arcade.draw_line(px, py, mx, my, color, 0.48 * scale)
        arcade.draw_circle_filled(px, py, 0.60 * scale, color)
        arcade.draw_circle_filled(mx, my, 0.25 * scale, WHITE)

        if tank.armored:
            arcade.draw_arc_outline(x, ground + 0.62 * scale, 8.7 * scale,
                                    4.9 * scale, (*color, 165), 12, 168, 0.25 * scale)
        self.text(f"unit{side}", "VOC\u00ca" if side == 0 else "CPU",
                  x, ground - 20, 9, color, bold=True, anchor="center")
        if side == 0 and self.game.ready:
            arcade.draw_line(px, py, px + 5.7 * scale, py, (*GOLD, 115), 1)

    def draw_math(self, shot, contact, t, preview):
        game = self.game
        panel((932, 202, 324, 492))
        x, y = shot.position(t)
        context = (
            "MIRA DO JOGADOR" if preview
            else "DISPARO DO JOGADOR" if shot.side == 0 else "DISPARO DA CPU"
        )
        self.text("math_title", "MIRA E IMPACTO", 951, 657, 20, GOLD,
                  bold=True, font=TITLE_FONT)
        self.text("math_context", context, 952, 633, 10, TEAM_COLORS[shot.side], font=MONO)
        self.text("angle_label", "ÂNGULO", 952, 608, 10, MUTED, bold=True)
        self.text("speed_label", "VELOCIDADE INICIAL", 1094, 608, 9, MUTED, bold=True)
        self.text("angle_value", f"{shot.angle:.1f}°", 952, 579, 22, font=MONO)
        self.text("speed_value", f"{shot.speed:.1f} m/s", 1094, 581, 16, font=MONO)

        numbers = (
            ("vx", "vx = sentido · v₀ cos(θ)", f"{shot.vx:+.1f} m/s"),
            ("vy", "vy = v₀ sen(θ) − gt", f"{shot.vy0 - GRAVITY * t:+.1f} m/s"),
            ("x", "x(t) = x₀ + vx·t", f"{x:.1f} m"),
            ("y", "y(t) = y₀ + vy₀·t − gt²/2", f"{y:.1f} m"),
        )
        for n, (key, formula, result) in enumerate(numbers):
            row = 549 - n * 26
            fill((948, row - 7, 293, 24), INSET)
            self.text(f"formula_{key}", formula, 955, row, 10, MUTED)
            self.text(f"value_{key}", result, 1232, row, 12, anchor="right", font=MONO)

        self.text("time", f"Tempo {t:.2f} s  ·  g = {GRAVITY:g} m/s²", 952, 438, 10, MUTED)
        self.text("peak", f"Altura do vértice livre  {shot.peak:.1f} m", 952, 414, 11)
        arcade.draw_line(950, 397, 1238, 397, LINE, 1)

        actual_contact = not preview and game.phase in ("impact", "over")
        if preview:
            fall = max(0, shot.peak - TANK_HEIGHT)
            title = "POTENCIAL DE DANO"
            note = "Projeção de acerto na descida, sem blindagem."
            amount = raw_damage(fall)
        else:
            fall = shot.fall(t)
            title = "DANO APLICADO NO ALVO" if actual_contact else "DANO BRUTO NO INSTANTE"
            amount = game.damage[1 - shot.side] if actual_contact else raw_damage(fall)
            note = "Queda medida desde o vértice da trajetória."

        self.text("damage_title", title, 952, 374, 10, GOLD, bold=True)
        self.text("fall", f"Altura de queda  {fall:.1f} m", 952, 350, 11)
        self.text(
            "damage_rule", f"{BASE_DAMAGE} + mín({MAX_BONUS}, {BONUS_PER_METER:g} × queda)",
            952, 326, 10, MUTED, font=MONO,
        )
        self.text("amount", f"{amount} HP", 952, 271, 30, GOLD, bold=True, font=TITLE_FONT)
        self.text("damage_note", note, 952, 224, 9, MUTED)

    def draw_controls(self):
        panel((24, 36, 888, 150))
        tank = self.game.tanks[0]
        self.text("aim_a", "ÂNGULO   [↑ ↓]", 46, 153, 11, MUTED, bold=True)
        self.text("aim_v", "VELOCIDADE   [← →]", 480, 153, 11, MUTED, bold=True)
        self.text("aim_a_v", f"{tank.angle:.1f}°", 426, 151, 14, TEAL,
                  anchor="right", font=MONO)
        self.text("aim_v_v", f"{tank.speed:.1f} m/s", 886, 151, 14, TEAL,
                  anchor="right", font=MONO)

        for (x, y, width), fraction in (
            (ANGLE_TRACK, (tank.angle - ANGLE_MIN) / (ANGLE_MAX - ANGLE_MIN)),
            (SPEED_TRACK, (tank.speed - SPEED_MIN) / (SPEED_MAX - SPEED_MIN)),
        ):
            fill((x, y - 2, width, 4), LINE)
            fill((x, y - 2, width * fraction, 4), TEAL)
            arcade.draw_circle_filled(x + width * fraction, y, 5, TEAL)

        active = self.game.ready and not self.paused and not self.help_open
        for action, (box, label) in BUTTONS.items():
            if action == "pause" and self.paused:
                label = "CONTINUAR  [P]"
            self.draw_button(
                action, box, label,
                active=active or action == "pause",
                accent=action == "fire",
            )

        self.text("rule", "Mover ou disparar encerra seu turno. Mover ativa a blindagem.",
                  46, 43, 10, MUTED)

        panel((932, 36, 324, 150))
        guide = "ligado" if self.show_guide else "desligado"
        sound = "mudo" if self.muted else "ligado"
        self.text("shortcut", "CONTROLES", 952, 152, 11, MUTED, bold=True)
        self.text("shortcut_a", f"T  Guia {guide}     V  Ritmo {self.playback}×", 952, 125, 11)
        self.text("shortcut_b", f"M  Som {sound}     H  Ajuda", 952, 100, 11)
        self.text("shortcut_c", "R  Reiniciar     F11  Tela cheia", 952, 74, 11)

    def draw_overlay(self):
        game = self.game
        if self.help_open:
            fill((0, 0, WIDTH, HEIGHT), (5, 10, 12, 190))
            panel((228, 211, 824, 388), BG, GOLD)
            self.text("help_title", "COMO JOGAR", 266, 552, 28, GOLD,
                      bold=True, font=TITLE_FONT)
            instructions = (
                "A / D movem até 8 m e consomem o turno.",
                "Ao mover, você reduz em 35% o dano recebido até sua próxima vez.",
                "↑ / ↓ ajustam ângulo. ← / → ajustam velocidade. Espaço dispara.",
                "Impactos derrubam camadas da muralha. Tiros altos ganham dano na descida.",
                "1 / 2 / 3 selecionam o nível e iniciam um novo duelo.",
                "P pausa a simulação. V alterna o ritmo. T alterna o guia de mira.",
                "H ou Esc fecham a ajuda.",
            )
            for i, line in enumerate(instructions):
                self.text(f"help{i}", line, 266, 503 - i * 40, 13)
        elif game.phase == "over":
            panel((206, 387, 524, 179), BG, GOLD)
            title = "VITÓRIA" if game.winner == 0 else "DERROTA" if game.winner == 1 else "EMPATE"
            self.text("final", title, 468, 503, 31, GOLD,
                      bold=True, anchor="center", font=TITLE_FONT)
            self.text(
                "stats",
                f"{game.shots[0]} disparos  ·  {game.hits[0]} acertos  ·  {game.moves[0]} movimentos",
                468, 461, 12, anchor="center",
            )
            self.text("replay", "R  JOGAR DE NOVO", 468, 421, 13,
                      TEAL, bold=True, anchor="center")
        elif self.paused:
            panel((270, 564, 396, 70), BG, GOLD)
            self.text("pause_title", "EM PAUSA  ·  P PARA CONTINUAR", 468, 591,
                      13, GOLD, bold=True, anchor="center")

    def play_sound(self, name, volume):
        if not self.muted and name in self.audio_clips:
            try:
                arcade.play_sound(self.audio_clips[name], volume=volume)
            except Exception:
                del self.audio_clips[name]

    def emit(self, x, y, count, color, rising):
        for _ in range(count):
            angle = self.fx_rng.uniform(0, math.pi if rising else math.tau)
            velocity = self.fx_rng.uniform(2.5, 13)
            life = self.fx_rng.uniform(0.19, 0.72)
            self.particles.append(
                Particle(x, y, math.cos(angle) * velocity, math.sin(angle) * velocity,
                         life, life, self.fx_rng.uniform(1.5, 4.2), color)
            )

    def shot_effect(self):
        shot = self.game.shot
        self.play_sound("fire", 0.38)
        self.emit(shot.x0, shot.y0, 15, GOLD, False)

    def impact_effect(self):
        contact = self.game.contact
        if contact.kind == "outside":
            return
        self.play_sound("wall" if contact.kind == "wall" else "impact", 0.48)
        self.emit(contact.x, contact.y, 36, GOLD, True)
        self.emit(contact.x, contact.y, 14, (181, 132, 91), True)

    def on_update(self, delta_time):
        if self.paused or self.help_open:
            return
        dt = min(delta_time, 0.08)
        game = self.game
        tank = game.tanks[0]
        da = (int(arcade.key.UP in self.held) - int(arcade.key.DOWN in self.held)) * 30 * dt
        dv = (int(arcade.key.RIGHT in self.held) - int(arcade.key.LEFT in self.held)) * 10 * dt
        game.aim(tank.angle + da, tank.speed + dv)

        previous_shot, previous_phase = game.shot, game.phase
        game.update(dt, self.playback)
        if game.shot is not previous_shot:
            self.shot_effect()
        if previous_phase == "flight" and game.phase == "impact":
            self.impact_effect()

        for side in (0, 1):
            difference = game.tanks[side].hp - self.hp_display[side]
            self.hp_display[side] += difference * min(1, 9 * dt)

        shot, contact, t, preview = self.current_trajectory()
        visible_peak = shot.y(min(shot.peak_time, contact.time))
        wanted_sky = max(50, visible_peak * 1.12 + 4)
        self.sky += (wanted_sky - self.sky) * min(1, 7 * dt)
        if not preview:
            self.sky = max(self.sky, shot.y(t) + 7)

        for spark in self.particles:
            spark.x += spark.vx * dt
            spark.y += spark.vy * dt
            spark.vy -= 20 * dt
            spark.life -= dt
        self.particles = [spark for spark in self.particles if spark.life > 0]

    def action(self, name):
        if self.help_open:
            return
        if name == "pause":
            self.paused = not self.paused
            self.held.clear()
            self.drag = None
        elif not self.paused and self.game.ready:
            if name == "fire":
                if self.game.fire(0):
                    self.shot_effect()
            else:
                self.game.move(0, -1 if name == "left" else 1)

    def on_key_press(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            if self.help_open:
                self.help_open = False
            elif self.paused:
                self.paused = False
            else:
                self.close()
        elif key == arcade.key.H:
            self.help_open = not self.help_open
            self.held.clear()
            self.drag = None
        elif key == arcade.key.F11:
            self.set_fullscreen(not self.fullscreen)
        elif self.help_open:
            return
        elif key == arcade.key.P:
            self.action("pause")
        elif key == arcade.key.M:
            self.muted = not self.muted
        elif key == arcade.key.T:
            self.show_guide = not self.show_guide
        elif key == arcade.key.V:
            self.playback = self.playback % 3 + 1
        elif key == arcade.key.R:
            self.new_game(self.game.level)
        elif key in (arcade.key.KEY_1, arcade.key.KEY_2, arcade.key.KEY_3):
            self.new_game((arcade.key.KEY_1, arcade.key.KEY_2, arcade.key.KEY_3).index(key))
        elif key in (arcade.key.A, arcade.key.D, arcade.key.SPACE):
            self.action({arcade.key.A: "left", arcade.key.D: "right", arcade.key.SPACE: "fire"}[key])
        elif key in (arcade.key.UP, arcade.key.DOWN, arcade.key.LEFT, arcade.key.RIGHT):
            if key not in self.held and not self.paused:
                tank = self.game.tanks[0]
                da = 0.5 if key == arcade.key.UP else -0.5 if key == arcade.key.DOWN else 0
                dv = 0.1 if key == arcade.key.RIGHT else -0.1 if key == arcade.key.LEFT else 0
                self.game.aim(tank.angle + da, tank.speed + dv)
                self.held.add(key)

    def on_key_release(self, key, modifiers):
        self.held.discard(key)

    def mouse_point(self, x, y):
        return (x - self.ox) / self.ratio, (y - self.oy) / self.ratio

    def on_mouse_motion(self, x, y, dx, dy):
        self.pointer = self.mouse_point(x, y)

    def on_mouse_press(self, x, y, button, modifiers):
        if button != arcade.MOUSE_BUTTON_LEFT or self.help_open:
            return
        x, y = self.mouse_point(x, y)
        self.pointer = (x, y)
        for index in range(len(LEVELS)):
            if contains(self.level_box(index), x, y):
                self.new_game(index)
                return
        for action, (box, _) in BUTTONS.items():
            if contains(box, x, y):
                self.action(action)
                return
        if self.game.ready and not self.paused:
            for name, (left, center, width) in (("angle", ANGLE_TRACK), ("speed", SPEED_TRACK)):
                if left - 7 <= x <= left + width + 7 and abs(y - center) <= 11:
                    self.drag = name
                    self.set_slider(x)
                    return

    def set_slider(self, x):
        if self.drag is None or self.paused or self.help_open or not self.game.ready:
            return
        tank = self.game.tanks[0]
        angle, speed = tank.angle, tank.speed
        left, _, width = ANGLE_TRACK if self.drag == "angle" else SPEED_TRACK
        fraction = clamp((x - left) / width, 0, 1)
        if self.drag == "angle":
            angle = round(ANGLE_MIN + fraction * (ANGLE_MAX - ANGLE_MIN), 1)
        else:
            speed = round(SPEED_MIN + fraction * (SPEED_MAX - SPEED_MIN), 1)
        self.game.aim(angle, speed)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.pointer = self.mouse_point(x, y)
        self.set_slider(self.pointer[0])

    def on_mouse_release(self, x, y, button, modifiers):
        self.drag = None

    def on_deactivate(self):
        self.held.clear()
        self.drag = None


if __name__ == "__main__":
    TankLab()
    arcade.run()