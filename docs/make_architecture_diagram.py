"""Generate docs/architecture.png from the layout in docs/architecture.md.

Checked in as a script rather than only as a binary so the diagram can be
regenerated and diffed when the architecture changes.

    python docs/make_architecture_diagram.py

The diagram deliberately carries its own honesty marker: the OpenShell layer
is drawn as AUTHored but NOT EXECUTED, because it has never been run on any
host. A diagram that showed the sandbox as a working control would be the
single most misleading artefact in the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1700, 1080

BG = (15, 17, 23)
CARD = (26, 29, 39)
CARD_ALT = (34, 37, 58)
BORDER = (42, 45, 62)
TEXT = (228, 231, 236)
DIM = (139, 143, 163)
ACCENT = (108, 92, 231)
GREEN = (0, 214, 143)
AMBER = (255, 217, 61)
RED = (255, 107, 107)
BLUE = (78, 205, 196)

FONT_CANDIDATES = {
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "mono": ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf"],
}


def load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES[kind]:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    # DejaVu ships with Pillow and is the last resort; never fail to render.
    for name in ("DejaVuSans-Bold.ttf" if kind == "bold" else "DejaVuSans.ttf",
                 "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


F = {
    "title": load_font("bold", 40),
    "subtitle": load_font("regular", 20),
    "box": load_font("bold", 22),
    "label": load_font("regular", 17),
    "small": load_font("regular", 15),
    "mono": load_font("mono", 15),
    "note": load_font("bold", 18),
}


def box(draw, xy, *, fill=CARD, outline=BORDER, radius=14, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def text(draw, x, y, value, font, fill=TEXT, anchor="la"):
    draw.text((x, y), value, font=font, fill=fill, anchor=anchor)


def arrow(draw, start, end, *, fill=ACCENT, width=3, head=12):
    draw.line([start, end], fill=fill, width=width)
    x0, y0 = start
    x1, y1 = end
    if x1 == x0:  # vertical
        direction = 1 if y1 > y0 else -1
        draw.polygon(
            [(x1, y1), (x1 - head, y1 - direction * head), (x1 + head, y1 - direction * head)],
            fill=fill,
        )
    else:  # horizontal
        direction = 1 if x1 > x0 else -1
        draw.polygon(
            [(x1, y1), (x1 - direction * head, y1 - head), (x1 - direction * head, y1 + head)],
            fill=fill,
        )


def build() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # ── Title ──────────────────────────────────────────────────────────
    text(draw, 48, 36, "Haven — architecture", F["title"])
    text(
        draw,
        48,
        88,
        "Family data-exposure agent · Nebius Token Factory (Nemotron tiers) + Tavily, "
        "inside an NVIDIA OpenShell boundary",
        F["subtitle"],
        DIM,
    )

    # ── Host ───────────────────────────────────────────────────────────
    box(draw, (40, 130, 1660, 1010), fill=(19, 21, 30), outline=BORDER)
    text(draw, 64, 146, "HOST", F["box"], DIM)
    text(draw, 132, 150, "owns the network boundary and the keys", F["small"], DIM)

    # ── Sandbox ────────────────────────────────────────────────────────
    box(draw, (70, 195, 1180, 742), fill=CARD, outline=ACCENT, width=3)
    text(draw, 96, 212, "NVIDIA OpenShell sandbox", F["box"], ACCENT)
    text(
        draw,
        400,
        218,
        "policy-enforced · AUTHORED, NOT EXECUTED",
        F["note"],
        AMBER,
    )
    text(
        draw,
        96,
        244,
        "Deny-by-default. Everything not listed below returns 403.",
        F["small"],
        DIM,
    )

    # Hermes harness
    box(draw, (96, 280, 700, 712), fill=CARD_ALT, outline=BORDER)
    text(draw, 118, 296, "Hermes agent harness", F["box"], TEXT)

    box(draw, (118, 334, 678, 396), fill=CARD, outline=BORDER)
    text(draw, 134, 346, "skills/  (SKILL.md)", F["label"], BLUE)
    text(
        draw,
        134,
        368,
        "discover_exposure · extract_optout_procedure · draft_removal_request",
        F["small"],
        DIM,
    )

    box(draw, (118, 410, 678, 462), fill=CARD, outline=BORDER)
    text(draw, 134, 420, "memory", F["label"], BLUE)
    text(draw, 214, 422, "state lives in $HERMES_HOME, not in the repo", F["small"], DIM)

    box(draw, (118, 476, 678, 700), fill=CARD, outline=GREEN)
    text(draw, 134, 486, "tools — the only two ways out", F["label"], GREEN)
    text(draw, 134, 510, "Tavily Search   POST /search", F["mono"], TEXT)
    text(draw, 134, 530, "Tavily Extract  POST /extract", F["mono"], TEXT)
    text(draw, 134, 550, "Token Factory   POST /v1/chat/completions", F["mono"], TEXT)
    text(draw, 134, 570, "                GET  /v1/models", F["mono"], TEXT)
    text(draw, 134, 598, "nano  → extraction, classification, routing", F["small"], DIM)
    text(draw, 134, 616, "super → reasoning, drafting, planning", F["small"], DIM)
    text(draw, 134, 634, "ultra → multi-site strategy, long context", F["small"], DIM)
    text(
        draw,
        134,
        660,
        "per-tier tokens + latency logged → dashboard chart",
        F["small"],
        GREEN,
    )

    # Policy panel
    box(draw, (724, 280, 1152, 700), fill=CARD, outline=RED, width=2)
    text(draw, 746, 296, "policy.yaml", F["box"], RED)
    text(draw, 746, 328, "network_policies", F["label"], TEXT)
    text(draw, 762, 352, "allow → Token Factory (2 hosts), Tavily", F["small"], GREEN)
    text(draw, 762, 372, "enforcement: enforce", F["mono"], DIM)
    text(draw, 746, 400, "landlock", F["label"], TEXT)
    text(draw, 762, 424, "compatibility: hard_requirement", F["mono"], GREEN)
    text(draw, 762, 444, "best_effort would void the FS rules", F["small"], DIM)
    text(draw, 746, 472, "filesystem_policy", F["label"], TEXT)
    text(draw, 762, 496, "read_write: /sandbox, /tmp", F["mono"], GREEN)
    text(draw, 762, 516, "read_only:  /usr, /lib, /etc, /proc", F["mono"], DIM)
    text(draw, 746, 544, "binaries", F["label"], TEXT)
    text(draw, 762, 568, "resolved interpreter path, not a symlink", F["small"], DIM)
    text(draw, 746, 600, "network_middlewares", F["label"], BLUE)
    text(draw, 762, 624, "openshell/regex · mode: redact", F["mono"], BLUE)
    text(draw, 762, 644, "on_error: fail_closed", F["mono"], BLUE)
    text(draw, 746, 668, "→ in policy.hardened.yaml only", F["small"], AMBER)

    # Credential brokering note (right column of the host)
    box(draw, (1210, 195, 1634, 400), fill=CARD, outline=AMBER)
    text(draw, 1232, 212, "Credential brokering", F["box"], AMBER)
    text(draw, 1232, 246, "OpenShell injects the Tavily and Nebius keys", F["small"], TEXT)
    text(draw, 1232, 266, "at the proxy boundary, so the agent process", F["small"], TEXT)
    text(draw, 1232, 286, "never holds them.", F["small"], TEXT)
    text(draw, 1232, 318, "NOT IN FORCE HERE", F["note"], RED)
    text(draw, 1232, 346, "with no sandbox, llm.py and research.py", F["small"], DIM)
    text(draw, 1232, 366, "read the keys from os.environ.", F["small"], DIM)

    # Evidence + dashboard
    box(draw, (1210, 430, 1634, 730), fill=CARD, outline=BLUE)
    text(draw, 1232, 446, "Host-side evidence service", F["box"], BLUE)
    text(draw, 1232, 480, "reads OpenShell OCSF JSONL audit logs", F["small"], TEXT)
    text(draw, 1232, 500, "class_uid 4001/4002 · dst_endpoint.domain", F["mono"], DIM)
    text(draw, 1232, 520, "disposition_id → allowed | denied", F["mono"], DIM)
    text(draw, 1232, 540, "firewall_rule.name → matched policy", F["mono"], DIM)
    text(draw, 1232, 572, "Never self-reported by the agent.", F["small"], GREEN)
    text(draw, 1232, 592, "Only disposition_id 1 counts as allowed.", F["small"], GREEN)
    text(draw, 1232, 626, "Dashboard", F["box"], TEXT)
    text(draw, 1232, 660, "exposure board · action tracker", F["small"], DIM)
    text(draw, 1232, 680, "tier usage chart · boundary panel", F["small"], DIM)
    text(draw, 1232, 700, "(allowed vs denied, labelled on screen)", F["small"], DIM)

    # ── Arrows ─────────────────────────────────────────────────────────
    arrow(draw, (320, 742), (320, 790), fill=BLUE)
    arrow(draw, (400, 742), (1420, 790), fill=BLUE)

    # Evidence panel (below the sandbox)
    box(draw, (96, 790, 700, 900), fill=CARD, outline=GREEN)
    text(draw, 118, 806, "Evidence: OCSF egress records", F["box"], GREEN)
    text(draw, 118, 840, "Enforcement layer → dashboard. The agent cannot", F["small"], TEXT)
    text(draw, 118, 860, "fabricate or suppress what appears here.", F["small"], TEXT)

    box(draw, (740, 790, 1180, 900), fill=CARD, outline=ACCENT)
    text(draw, 762, 806, "Dashboard", F["box"], ACCENT)
    text(draw, 762, 840, "N listings found · M requests sent", F["small"], TEXT)
    text(draw, 762, 860, "K confirmed removed · J pending", F["small"], TEXT)

    # ── Boundary status banner ─────────────────────────────────────────
    box(draw, (96, 916, 1606, 998), fill=(38, 26, 26), outline=RED, width=2)
    text(draw, 120, 928, "BOUNDARY NOT PROVEN", F["note"], RED)
    text(
        draw,
        120,
        956,
        "policy/boundary_test.sh has never been run. OpenShell needs Linux with Landlock ABI v3 "
        "(Linux 6.2+) and Docker 28.0+.",
        F["small"],
        TEXT,
    )
    text(
        draw,
        120,
        976,
        "This host is Windows 11 with no WSL and no Docker. Nothing here demonstrates that a "
        "non-allowlisted destination is blocked.",
        F["small"],
        DIM,
    )
    return image


def main() -> int:
    target = Path(__file__).resolve().parent / "architecture.png"
    image = build()
    image.save(target, "PNG", optimize=True)
    print(f"wrote {target} ({target.stat().st_size:,} bytes, {WIDTH}x{HEIGHT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
