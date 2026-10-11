import pygame
import subprocess
import struct
import math
import os

# ============================================================
# RETRO VU METER V10
#
# Raspberry Pi
# Resolución de diseño: 480 x 320
#
# V10
# - Sin líneas circulares decorativas
# - Sin líneas horizontales decorativas
# - VU grande y centrado
# - Gonza pequeño, rojo y desplazado
# - Fondo vintage con iluminación desde abajo
# - Audio real mediante parec / PulseAudio
# ============================================================


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

BASE_WIDTH = 480
BASE_HEIGHT = 320

WIDTH = BASE_WIDTH
HEIGHT = BASE_HEIGHT

FPS = 30


# ============================================================
# PYGAME
# ============================================================

pygame.init()

# Pantalla completa
screen = pygame.display.set_mode(
    (WIDTH, HEIGHT),
    pygame.FULLSCREEN
)

pygame.display.set_caption("Gonza VU Meter")

# Ocultar cursor
pygame.mouse.set_visible(False)

# Superficie de dibujo
canvas = pygame.Surface(
    (BASE_WIDTH, BASE_HEIGHT)
)


# ============================================================
# FUENTES
# ============================================================

# Números de la escala
font_scale = pygame.font.Font(
    None,
    18
)

# VU central
font_vu = pygame.font.Font(
    None,
    34
)


# ------------------------------------------------------------
# Fuente para Gonza
#
# Intentamos utilizar una tipografía cursiva disponible
# en Raspberry Pi.
# ------------------------------------------------------------

gonza_font_path = None

possible_fonts = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf",
]

for path in possible_fonts:
    if os.path.exists(path):
        gonza_font_path = path
        break


if gonza_font_path:
    font_gonza = pygame.font.Font(
        gonza_font_path,
        20
    )
else:
    font_gonza = pygame.font.Font(
        None,
        20
    )


# ============================================================
# AUDIO
# ============================================================

audio = None

cmd = [
    "parec",
    "--device=alsa_output.platform-bcm2835_audio.analog-stereo.monitor",
    "--format=s16le",
    "--rate=44100",
    "--channels=2"
]

try:

    audio = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        bufsize=0
    )

    print("parec iniciado correctamente.")

except Exception as e:

    print("No se pudo iniciar parec:")
    print(e)

    audio = None


# ============================================================
# NIVEL
# ============================================================

level = 0.0
peak = 0.0


# ============================================================
# COLORES
# ============================================================

# ------------------------------------------------------------
# Fondo exterior metálico
# ------------------------------------------------------------

METAL_TOP = (
    120,
    122,
    120
)

METAL_BOTTOM = (
    45,
    47,
    47
)

METAL_EDGE = (
    185,
    188,
    184
)

METAL_DARK = (
    28,
    29,
    28
)


# ------------------------------------------------------------
# Panel vintage
# ------------------------------------------------------------

PANEL_TOP = (
    235,
    220,
    178
)

PANEL_BOTTOM = (
    210,
    174,
    95
)


# ------------------------------------------------------------
# Escala
# ------------------------------------------------------------

SCALE_COLOR = (
    42,
    36,
    28
)

TEXT_COLOR = (
    50,
    40,
    28
)


# ------------------------------------------------------------
# Gonza
# ------------------------------------------------------------

BRAND_RED = (
    150,
    28,
    24
)

BRAND_SHADOW = (
    85,
    15,
    14
)


# ------------------------------------------------------------
# Aguja
# ------------------------------------------------------------

NEEDLE = (
    65,
    28,
    20
)

NEEDLE_HIGHLIGHT = (
    245,
    210,
    140
)


# ------------------------------------------------------------
# Zona roja
# ------------------------------------------------------------

RED_ZONE = (
    165,
    35,
    28
)


# ============================================================
# PANEL
# ============================================================

PANEL_LEFT = 6
PANEL_RIGHT = 474

PANEL_TOP_Y = 6
PANEL_BOTTOM_Y = 314

PANEL_WIDTH = (
    PANEL_RIGHT -
    PANEL_LEFT
)

PANEL_HEIGHT = (
    PANEL_BOTTOM_Y -
    PANEL_TOP_Y
)


# ============================================================
# POSICIÓN DEL VU
# ============================================================

CENTER_X = 240
CENTER_Y = 270


# ============================================================
# ESCALA
# ============================================================

ARC_RADIUS = 215


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def clamp(value, minimum, maximum):

    return max(
        minimum,
        min(
            maximum,
            value
        )
    )


def lerp(a, b, t):

    return (
        a +
        (b - a) * t
    )


# ============================================================
# FONDO METÁLICO
# ============================================================

def draw_metal():

    for y in range(BASE_HEIGHT):

        p = y / float(
            BASE_HEIGHT - 1
        )

        r = int(
            lerp(
                METAL_TOP[0],
                METAL_BOTTOM[0],
                p
            )
        )

        g = int(
            lerp(
                METAL_TOP[1],
                METAL_BOTTOM[1],
                p
            )
        )

        b = int(
            lerp(
                METAL_TOP[2],
                METAL_BOTTOM[2],
                p
            )
        )

        pygame.draw.line(
            canvas,
            (r, g, b),
            (0, y),
            (BASE_WIDTH, y)
        )


# ============================================================
# PANEL INTERIOR
# ============================================================

def draw_panel():

    # --------------------------------------------------------
    # Marco oscuro exterior
    # --------------------------------------------------------

    pygame.draw.rect(
        canvas,
        METAL_DARK,
        (
            PANEL_LEFT,
            PANEL_TOP_Y,
            PANEL_WIDTH,
            PANEL_HEIGHT
        )
    )


    # --------------------------------------------------------
    # Borde metálico
    # --------------------------------------------------------

    pygame.draw.rect(
        canvas,
        METAL_EDGE,
        (
            PANEL_LEFT + 2,
            PANEL_TOP_Y + 2,
            PANEL_WIDTH - 4,
            PANEL_HEIGHT - 4
        ),
        2
    )


    inner_left = PANEL_LEFT + 7
    inner_right = PANEL_RIGHT - 7

    inner_top = PANEL_TOP_Y + 7
    inner_bottom = PANEL_BOTTOM_Y - 7


    # --------------------------------------------------------
    # FONDO VINTAGE
    #
    # Iluminación progresiva desde abajo.
    #
    # IMPORTANTE:
    # NO hay círculos.
    # NO hay líneas decorativas.
    # --------------------------------------------------------

    for y in range(
        inner_top,
        inner_bottom
    ):

        p = (
            y - inner_top
        ) / float(
            inner_bottom - inner_top
        )

        # Curva de iluminación:
        # arriba oscuro / abajo luminoso

        intensity = p * p

        r = int(
            lerp(
                PANEL_TOP[0],
                PANEL_BOTTOM[0],
                intensity
            )
        )

        g = int(
            lerp(
                PANEL_TOP[1],
                PANEL_BOTTOM[1],
                intensity
            )
        )

        b = int(
            lerp(
                PANEL_TOP[2],
                PANEL_BOTTOM[2],
                intensity
            )
        )


        # ----------------------------------------------------
        # Pequeño foco de luz hacia la zona inferior central.
        #
        # También es un gradiente, NO círculos.
        # ----------------------------------------------------

        distance_from_center = abs(
            (y - inner_top) /
            float(inner_bottom - inner_top)
            - 0.85
        )

        glow = max(
            0.0,
            1.0 - distance_from_center * 2.2
        )

        r = min(
            255,
            int(r + glow * 12)
        )

        g = min(
            255,
            int(g + glow * 9)
        )

        b = min(
            255,
            int(b + glow * 2)
        )


        pygame.draw.line(
            canvas,
            (r, g, b),
            (inner_left, y),
            (inner_right, y)
        )


    # --------------------------------------------------------
    # Brillo muy sutil del vidrio superior
    #
    # Una sola línea muy fina, sin decoración.
    # --------------------------------------------------------

    pygame.draw.line(
        canvas,
        (
            255,
            248,
            218
        ),
        (
            inner_left + 8,
            inner_top + 2
        ),
        (
            inner_right - 8,
            inner_top + 2
        ),
        1
    )


# ============================================================
# POSICIÓN SOBRE EL ARCO
# ============================================================

def angle_for_fraction(f):

    # 150° a 30°
    return math.radians(
        150 - f * 120
    )


def arc_point(angle, radius):

    x = (
        CENTER_X +
        math.cos(angle) * radius
    )

    y = (
        CENTER_Y -
        math.sin(angle) * radius
    )

    return (
        x,
        y
    )


# ============================================================
# ESCALA
# ============================================================

def draw_scale():

    # --------------------------------------------------------
    # Marcas
    # --------------------------------------------------------

    for i in range(31):

        f = i / 30.0

        angle = angle_for_fraction(f)


        if i % 5 == 0:

            inner = ARC_RADIUS - 28
            outer = ARC_RADIUS - 5
            width = 2

        else:

            inner = ARC_RADIUS - 18
            outer = ARC_RADIUS - 6
            width = 1


        # Último tramo rojo

        if f >= 0.84:

            color = RED_ZONE

        else:

            color = SCALE_COLOR


        x1, y1 = arc_point(
            angle,
            inner
        )

        x2, y2 = arc_point(
            angle,
            outer
        )


        pygame.draw.line(
            canvas,
            color,
            (
                int(x1),
                int(y1)
            ),
            (
                int(x2),
                int(y2)
            ),
            width
        )


    # --------------------------------------------------------
    # NÚMEROS
    #
    # Solamente tres.
    # --------------------------------------------------------

    labels = [
        ("-20", 0.0),
        ("-10", 0.50),
        ("0", 1.0)
    ]


    for text_value, f in labels:

        angle = angle_for_fraction(f)


        x, y = arc_point(
            angle,
            ARC_RADIUS - 52
        )


        if text_value == "0":

            color = RED_ZONE

        else:

            color = TEXT_COLOR


        text = font_scale.render(
            text_value,
            True,
            color
        )


        rect = text.get_rect(
            center=(
                int(x),
                int(y)
            )
        )


        canvas.blit(
            text,
            rect
        )


# ============================================================
# MARCA VU
# ============================================================

def draw_vu():

    # --------------------------------------------------------
    # VU negro.
    #
    # Centrado en pantalla y más grande.
    # --------------------------------------------------------

    text = font_vu.render(
        "VU",
        True,
        (
            30,
            28,
            24
        )
    )


    rect = text.get_rect(
        center=(
            CENTER_X,
            165
        )
    )


    canvas.blit(
        text,
        rect
    )


# ============================================================
# MARCA GONZA
# ============================================================

def draw_brand():

    # --------------------------------------------------------
    # Gonza
    #
    # Más pequeño.
    #
    # Aproximadamente:
    # +3 cm hacia la derecha
    # +1 cm hacia abajo
    #
    # respecto de la posición anterior.
    # --------------------------------------------------------

    brand_x = CENTER_X + 160
    brand_y = 273


    # --------------------------------------------------------
    # Sombra
    # --------------------------------------------------------

    shadow = font_gonza.render(
        "Gonza",
        True,
        BRAND_SHADOW
    )


    shadow_rect = shadow.get_rect(
        center=(
            brand_x + 1,
            brand_y + 1
        )
    )


    canvas.blit(
        shadow,
        shadow_rect
    )


    # --------------------------------------------------------
    # Marca roja
    # --------------------------------------------------------

    brand = font_gonza.render(
        "Gonza",
        True,
        BRAND_RED
    )


    brand_rect = brand.get_rect(
        center=(
            brand_x,
            brand_y
        )
    )


    canvas.blit(
        brand,
        brand_rect
    )


# ============================================================
# AGUJA
# ============================================================

def draw_needle():

    angle = angle_for_fraction(
        level
    )


    needle_length = 184


    nx, ny = arc_point(
        angle,
        needle_length
    )


    # --------------------------------------------------------
    # Sombra
    # --------------------------------------------------------

    pygame.draw.line(
        canvas,
        (
            90,
            65,
            40
        ),
        (
            CENTER_X + 2,
            CENTER_Y + 2
        ),
        (
            int(nx + 2),
            int(ny + 2)
        ),
        5
    )


    # --------------------------------------------------------
    # Aguja principal
    # --------------------------------------------------------

    pygame.draw.line(
        canvas,
        NEEDLE,
        (
            CENTER_X,
            CENTER_Y
        ),
        (
            int(nx),
            int(ny)
        ),
        2
    )


    # --------------------------------------------------------
    # Reflejo de la aguja
    # --------------------------------------------------------

    hx, hy = arc_point(
        angle,
        needle_length - 8
    )


    bx, by = arc_point(
        angle,
        25
    )


    pygame.draw.line(
        canvas,
        NEEDLE_HIGHLIGHT,
        (
            int(bx),
            int(by)
        ),
        (
            int(hx),
            int(hy)
        ),
        1
    )


    # --------------------------------------------------------
    # Contrapeso
    # --------------------------------------------------------

    back_angle = (
        angle +
        math.pi
    )


    bx, by = arc_point(
        back_angle,
        18
    )


    pygame.draw.line(
        canvas,
        NEEDLE,
        (
            CENTER_X,
            CENTER_Y
        ),
        (
            int(bx),
            int(by)
        ),
        3
    )


    # --------------------------------------------------------
    # Eje
    # --------------------------------------------------------

    pygame.draw.circle(
        canvas,
        (
            52,
            40,
            30
        ),
        (
            CENTER_X,
            CENTER_Y
        ),
        9
    )


    pygame.draw.circle(
        canvas,
        (
            185,
            160,
            105
        ),
        (
            CENTER_X,
            CENTER_Y
        ),
        5
    )


# ============================================================
# INDICADOR PEAK
# ============================================================

def draw_peak():

    angle = angle_for_fraction(
        peak
    )


    inner = ARC_RADIUS - 40
    outer = ARC_RADIUS - 5


    x1, y1 = arc_point(
        angle,
        inner
    )

    x2, y2 = arc_point(
        angle,
        outer
    )


    pygame.draw.line(
        canvas,
        RED_ZONE,
        (
            int(x1),
            int(y1)
        ),
        (
            int(x2),
            int(y2)
        ),
        2
    )


# ============================================================
# AUDIO → NIVEL
# ============================================================

def calculate_level(data):

    if len(data) < 4:

        return 0.0


    samples = struct.unpack(
        "<" + "h" * (len(data) // 2),
        data
    )


    total = 0


    for sample in samples:

        total += (
            sample *
            sample
        )


    rms = math.sqrt(
        total /
        len(samples)
    )


    db = (
        20 *
        math.log10(
            max(rms, 1) /
            32768.0
        )
    )


    minimum = -35
    maximum = -2


    f = (
        db - minimum
    ) / float(
        maximum - minimum
    )


    return clamp(
        f,
        0.0,
        1.0
    )


# ============================================================
# LOOP PRINCIPAL
# ============================================================

clock = pygame.time.Clock()

running = True


while running:

    # --------------------------------------------------------
    # EVENTOS
    # --------------------------------------------------------

    for event in pygame.event.get():

        if event.type == pygame.QUIT:

            running = False


        if event.type == pygame.KEYDOWN:

            if event.key == pygame.K_ESCAPE:

                running = False


    # --------------------------------------------------------
    # OBTENER NIVEL DEL AUDIO
    # --------------------------------------------------------

    if audio is not None:

        try:

            bytes_per_frame = (
                44100 *
                2 *
                2 //
                FPS
            )


            data = audio.stdout.read(
                bytes_per_frame
            )


            target = calculate_level(
                data
            )


        except Exception:

            target = 0.0

    else:

        target = 0.0


    # --------------------------------------------------------
    # MOVIMIENTO DE LA AGUJA
    # --------------------------------------------------------

    if target > level:

        # Ataque rápido

        level += (
            target - level
        ) * 0.40

    else:

        # Caída más lenta

        level += (
            target - level
        ) * 0.12


    level = clamp(
        level,
        0.0,
        1.0
    )


    # --------------------------------------------------------
    # PEAK
    # --------------------------------------------------------

    if level > peak:

        peak = level

    else:

        peak -= 0.004


    peak = clamp(
        peak,
        level,
        1.0
    )


    # --------------------------------------------------------
    # DIBUJAR
    # --------------------------------------------------------

    draw_metal()

    draw_panel()

    draw_scale()

    draw_vu()

    draw_brand()

    draw_peak()

    draw_needle()


    # --------------------------------------------------------
    # MOSTRAR
    # --------------------------------------------------------

    screen.blit(
        canvas,
        (
            0,
            0
        )
    )


    pygame.display.flip()


    clock.tick(FPS)


# ============================================================
# SALIDA
# ============================================================

if audio is not None:

    try:

        audio.terminate()

    except Exception:

        pass


pygame.quit()