import asyncio
import json
import urllib

from typing import Any, Callable, Self
from nicegui import ui
from nicegui.elements.interactive_image import InteractiveImage

from datatypes import Tile
from v9918 import DEFAULT_FG_COLOR, DEFAULT_BG_COLOR, PALETTE
from constants import GRID_PIXEL_SIZE
from common import get_text_color


class BoolStatus:
    _is_enabled: bool | None
    _explicit: bool
    function: Callable[[], bool] | None

    def __init__(self, inherent_state: bool | None = None, function: Callable[[], bool] | None = None, debug: bool = False):
        self._is_enabled = inherent_state
        self._explicit = False
        self.function = function
        self.debug = debug

    async def enable(self) -> None:
        self._is_enabled = True
        self._explicit = True
        await asyncio.sleep(0)

    async def disable(self) -> None:
        self._is_enabled = False
        self._explicit = True
        await asyncio.sleep(0)

    @property
    def is_enabled(self) -> bool | None:
        if self._explicit:
            return self._is_enabled
        if self.inherent_state:
            return self._is_enabled
        if not self.function is None:
            result = self.function()
            if not result is None:
                return result
        raise ValueError('not possible to determine status')

    @is_enabled.setter
    def is_enabled(self, b: bool) -> None:
        self._is_enabled = b

    @property
    def is_disabled(self) -> bool | None:
        if self._explicit:
            return not self._is_enabled
        if self.inherent_state:
            return not self._is_enabled
        if not self.function is None:
            result = self.function()
            if not result is None:
                return not result
        raise ValueError('not possible to determine status')

    @property
    def inherent_state(self) -> bool:
        return not self._is_enabled is None

    def __str__(self) -> str:
        return str(self.is_enabled)

    def __bool__(self) -> bool | None:
        return self.is_enabled


class UiPixel(ui.card):
    # attributes
    value: bool = False
    fg: int = DEFAULT_FG_COLOR
    bg: int = DEFAULT_BG_COLOR
    initialized: bool = False
    scale: int

    # ui elements
    inner: ui.card

    # CSS additions
    ui.add_css('''
        .transparent-uipixel {
            background-image: url('static/color0.png');
            background-size: 100% 100%;
            background-repeat: no-repeat;
            background-position: center;
            image-rendering: pixelated;
            image-rendering: crisp-edges;
        }
    ''', shared=True)


    def __init__(self, value: bool, fg: int | None = None, bg: int | None = None, scale: int | None = None):
        super().__init__()
        with self:
            # Just set values before initializing
            self.set_value(value)
            self.set_colors(fg, bg)
            self.set_scale(scale)
            self.initialized = True
            self.build_ui()


    def set_value(self, value: bool) -> None:
        self.value = value


    def set_colors(self, fg: int | None = None, bg: int | None = None) -> None:
        if not fg is None:
            self.fg = fg
        if not bg is None:
            self.bg = bg
        if self.initialized:
            self.repaint(False)


    def set_scale(self, scale: int | None = None, repaint: bool = False) -> None:
        if scale:
            self.scale = scale
        else:
            self.scale = GRID_PIXEL_SIZE
        if self.initialized and repaint:
            self.repaint(False)


    def set(self, value: bool, fg: int | None = None, bg: int | None = None) -> None:
        self.set_value(value)
        self.set_colors(fg, bg)


    def repaint(self, background_occlusion: bool) -> None:
        # if pixel is active, use foreground color, otherwise use background color
        index = self.fg if self.value else self.bg
        # grid gets poluted when scale is too small
        background_occlusion = self.scale < 8 or background_occlusion
        self.style(f'''
            box-shadow: none;
            width: {self.scale}px;
            height: {self.scale}px;
            background-image: none;
            background-color: {PALETTE[index if background_occlusion else self.bg]};
            border: 0px;
            border-radius: 0;
            cursor: pointer;
        ''')
        if self.bg == 0:
            self.classes('transparent-uipixel')
        self.inner.style(f'''
            width: {2/3 * self.scale}px;
            height: {2/3 * self.scale}px;
            background-image: none;
            background-color: {PALETTE[index]};
            border: 1px solid {PALETTE[self.fg]};
            visibility: {'hidden' if background_occlusion else 'visible'};
            border-radius: 0;
            cursor: pointer;
        ''')
        if self.fg == 0:
            self.inner.style(f'''
                border: 1px dashed {get_text_color(PALETTE[self.bg])};
            ''')
            self.inner.classes('transparent-uipixel')


    def build_ui(self) -> None:
        with self.tight().style('display: flex; justify-content: center; align-items: center;'):
            self.inner = ui.card().tight().classes('items-center justify-center')
        self.repaint(False)


class UiMetatile(InteractiveImage):
    """Represents a metatile in the UI, allowing to display and select/unselect it."""
    grid: Any
    scale: int
    palette: list[str]

    def __init__(self, data: Tile | str | bytes | list[list[int]], palette: list[str], scale: int = 5):
        grid: Any
        super().__init__()
        self.palette = palette
        self.scale = scale
        if isinstance(data, list):
            grid = data
        elif isinstance(data, str) or isinstance(data, bytes):
            # Convert from json string
            grid = json.loads(data)
        else:
            grid = data
        self.reload(grid)


    def reload(self, grid: Tile | list[list[int]]) -> None:
        self.grid = grid
        data = grid_to_svg(grid, self.palette, self.scale)
        self.ui = self.set_source('data:image/svg+xml;utf8,' + urllib.parse.quote(data))


def grid_to_svg(grid: Tile | list[list[int]], palette: list[str], scale: int = 20) -> str:
    """Create SVG image to be used by canvas."""
    width = len(grid[0])
    height = len(grid)

    svg = [ f'''<svg xmlns="http://www.w3.org/2000/svg"
            width="{width * scale}"
            height="{height * scale}">''' ]
    for y in range(height):
        for x in range(width):
            svg.append(
                f'<rect '
                f'x="{x * scale}" '
                f'y="{y * scale}" '
                f'width="{scale}" '
                f'height="{scale}" '
                f'fill="{palette[grid[y][x]]}" '
                f'stroke="#444"/>'
            )
    svg.append('</svg>')
    return ''.join(svg)


async def show_message_dialog(message: str) -> str:
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row():
            ui.button('OK', on_click=lambda: dialog.submit('OK'))
    return str(await dialog)
