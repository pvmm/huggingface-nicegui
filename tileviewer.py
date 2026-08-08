from typing import cast, Callable, Any
from nicegui import ui, app, events, run
from PIL import Image
from io import BytesIO

import sys
import base64
import traceback

import common

from common import add_handlers, file_to_base64, disable, enable, get_text_color

from ui import BoolStatus
from constants import GRID_PIXEL_MAX
from fileloader import FileLoader
from datatypes import Tile, from_105_to_metatile, TILE_SIZE, TileRow
from tileeditor import TileEditor
from imageslider import ImageSliderWidget

from bmpto105 import Engine, MSXBitmap, MSXBitmapRow, MSXBitmapUnit, RGBColor, ScreenSectionState


# send debug message to stdout when running locally?
debug: Callable[..., Any] = print # lambda *args, **kwargs: None


PALETTE = [
    (0, 0, 0), (0, 0, 0), (0x24, 0xda, 0x24), (0x68, 0xff, 0x68), (0x24, 0x24, 0xff), (0x48, 0x68, 0xff),
    (0xb6, 0x24, 0x24), (0x48, 0xda, 0xff), (0xff, 0x24, 0x24), (0xff, 0x68, 0x68), (0xda, 0xda, 0x24),
    (0xda, 0xda, 0x91), (0x24, 0x91, 0x24), (0xda, 0x48, 0xb6), (0xb6, 0xb6, 0xb6), (0xff, 0xff, 0xff)
]


class TileViewer:
    loaded_status: BoolStatus
    dirty_status: BoolStatus
    threshold_status: BoolStatus
    waiting_tile_editor: BoolStatus
    reuse_tiles: tuple[int, int, int]
    total_tiles: tuple[int, int, int]
    threshold: float
    zoom: int
    grid_width: int
    grid_height: int
    selected_pos: tuple[int, int]
    msx: MSXBitmap | None
    images64: list[str]
    current_frame: int
    allow_export: BoolStatus
    vram: tuple[ScreenSectionState, ScreenSectionState, ScreenSectionState]
    active_section: int | None
    opened_contextmenu: bool

    ui.add_css('''
        .pixelated {
            image-rendering: pixelated;
            image-rendering: crisp-edges;
        }
    ''', shared=True)

    # widgets
    grid_width_number: ui.number
    grid_height_number: ui.number
    threshold_number: ui.number
    reuse_badges: list[ui.badge]
    total_badges: list[ui.badge]
    frame_toggle: ui.toggle
    threshold_dropdown: ui.dropdown_button
    context_menu: ui.context_menu

    def __init__(self, image: Image.Image | None = None) -> None:
        self.msx = None
        if image: self.set_image(image)

        b0 = BoolStatus(function=lambda: (not self.msx is None))
        self.load_status = b0

        b1 = BoolStatus(
                inherent_state=False,
                function=lambda: (not self.msx is None))
        self.dirty_status = b1

        b2 = BoolStatus(
                inherent_state=False,
                function=lambda: (not self.msx is None))
        self.threshold_status = b2

        b3 = BoolStatus(
                inherent_state=False,
                function=lambda: (not self.msx is None))
        self.waiting_tile_editor = b3

        b4 = BoolStatus(
                function=lambda: (not self.msx is None) and all([n < 256 for n in self.total_tiles]))
        self.allow_export = b4

        self.engine = Engine(PALETTE)
        self.reuse_tiles = (0, 0, 0)
        self.total_tiles = (0, 0, 0)
        self.threshold = 0.0
        self.zoom = 4
        self.grid_width = 8
        self.grid_height = 8
        self.selected_pos = (-1, -1)
        self.opened_contextmenu = False
        self.active_section = None
        self.build_ui()


    def build_ui(self) -> None:
        ui.add_head_html('<script src="/static/tileviewer.js"></script>', shared=True)
        with ui.column().classes('w-full h-screen items-center'):
            ImageSliderWidget('./samples', 256, 192, on_loaded=self.load_image, on_removed=self.remove_image)

            with ui.row().classes('items-start flex-nowrap w-full'):
                self.frame_toggle = cast(
                        ui.toggle,
                        disable(ui.toggle({1: 'even frame', 2: 'odd frame', 3: 'combined'}, value=3,
                                          on_change=lambda e: self.draw_frame(int(e.value))))
                )

                (
                    ui.slider(min=1, max=16, value=self.zoom, step=1,
                              on_change=lambda e: self.set_zoom(int(e.value)))
                        .props('reverse').classes('w-[100px]')
                )

                with ui.dropdown_button('export as', auto_close=True).bind_enabled_from(self.load_status, 'is_enabled') as self.export_dropdown:
                    ui.item('PNG image', on_click=self.on_export_to_png_clicked)
                    ui.item('MSX VRAM layout file', on_click=self.on_export_to_msx_clicked).bind_enabled_from(self.allow_export, 'is_enabled')
                    ui.item('C code', on_click=self.on_export_to_c_clicked).bind_enabled_from(self.allow_export, 'is_enabled')

                ui.space()

                self.grid_width_number = cast(ui.number, disable(
                    ui.number(label='Metatile Width', min=8, value=8, step=8, format='%i',
                              on_change=lambda e: self.on_change_grid_size('w', e),
                              validation={'metatile size mismatch': lambda value: (self.msx.width * TILE_SIZE % value == 0) if self.msx else False})
                ))
                self.grid_height_number = cast(ui.number, disable(
                    ui.number(label='Metatile Height', min=8, value=8, step=8, format='%i',
                              on_change=lambda e: self.on_change_grid_size('h', e),
                              validation={'metatile size mismatch': lambda value: (self.msx.width * TILE_SIZE % value == 0) if self.msx else False})
                ))

            with ui.scroll_area().classes('w-full flex-1 border bg-gray-200').on('contextmenu.prevent', lambda: None):
                canvas = (
                    ui.element('canvas').props('id=tile_canvas')
                        .on('click', self.on_menu_invoked, args=['offsetX', 'offsetY', 'clientX', 'clientY'])
                        .on('mousemove', self.on_mouseover_canvas, args=['offsetX', 'offsetY'], throttle=0.05)
                        .on('mouseleave', self.on_mouseout_canvas)
                )

            with ui.column().classes('items-start flex-nowrap w-full'):
                self.reuse_badges = []
                self.total_badges = []
                with ui.row().classes('flex-nowrap items-center'):
                    ui.label('Tiles reused:')
                    self.reuse_badges.append(ui.badge('0', color='purple').tooltip('top 64x8 tiles'))
                    ui.label('/')
                    self.reuse_badges.append(ui.badge('0', color='purple').tooltip('middle 64x8 tiles'))
                    ui.label('/')
                    self.reuse_badges.append(ui.badge('0', color='purple').tooltip('bottom 64x8 tiles'))
                    ui.label('Tiles total:')
                    self.total_badges.append(ui.badge('0', color='purple').tooltip('top 64x8 tiles'))
                    ui.label('/')
                    self.total_badges.append(ui.badge('0', color='purple').tooltip('middle 64x8 tiles'))
                    ui.label('/')
                    self.total_badges.append(ui.badge('0', color='purple').tooltip('bottom 64x8 tiles'))

                with ui.row().classes('flex-nowrap items-center'):
                    ui.label('Compression type:')
                    with ui.dropdown_button('DCT', auto_close=True) as self.threshold_dropdown:
                        ui.item('DCT', on_click=lambda: self.threshold_dropdown.set_text('DCT'))
                        ui.item('SVD', on_click=lambda: self.threshold_dropdown.set_text('SVD'))
                        ui.item('KMC', on_click=lambda: self.threshold_dropdown.set_text('KMC'))
                    self.threshold_number = (
                            ui.number(label='Threshold', min=0.0, value=0.0, step=0.1, max=1.0, format='%0.1f',
                                      on_change=self.on_change_threshold,
                                      validation={'not a number': lambda val: val is not None}
                                  ).classes('w-[170px]').props('debounce=500')
                            .bind_enabled_from(self.threshold_status, 'is_enabled')
                    )
                    ui.button('update image', on_click=self.on_update_clicked) \
                            .bind_enabled_from(self.dirty_status, 'is_enabled')

        #ui.on("tile_clicked", self.on_tile_clicked)


    async def on_menu_invoked(self, e: events.GenericEventArguments) -> None:
        # ignore multiple events
        if self.opened_contextmenu:
            return

        debug('on_contextmenu_invoked called')
        self.opened_contextmenu = True

        # update active screen section
        section = int(e.args.get('offsetY')) // self.zoom // 64
        if self.active_section != section:
            ui.run_javascript(f'window.tileViewer.hoverSection({section});')
            self.active_section = section

        # update selected tile
        self.selected_pos = (int(e.args.get('offsetX')) // self.zoom, int(e.args.get('offsetY')) // self.zoom)
        ui.run_javascript(f'window.tileViewer.setSelection({self.selected_pos[0]}, {self.selected_pos[1]});')

        # display context dialog
        self.opened_contextmenu = False
        with ui.dialog().props('transition-show=none transition-hide=none') as dialog:
            with ui.card().style(f'''
                                 position: absolute;
                                 width: 400px;
                                 left: {e.args.get('clientX')}px;
                                 top: {e.args.get('clientY')}px;
                                 max-width: None;'''):
                with ui.column().classes('w-full justify-start'):
                    ui.label(f'Reused tiles: {self.reuse_tiles[self.active_section]} / Distinct tiles: {self.total_tiles[self.active_section]}')
                    ui.button('Copy metatile')
                    ui.button('Paste metatile')
                    ui.button('Edit even frame metatile')
                    ui.button('Edit odd frame metatile')
        await dialog

        # deselect metatile
        ui.run_javascript(f'window.tileViewer.unsetSelection({self.selected_pos[0]}, {self.selected_pos[1]});')


    def on_mouseover_canvas(self, e: events.GenericEventArguments) -> None:
        '''update active screen section'''
        section = int(e.args.get('offsetY')) // self.zoom // 64
        if self.active_section == section:
            return
        elif not self.active_section is None: # and self.context_menu.visible:
            #self.context_menu.close()
            self.active_section = None
        else:
            ui.run_javascript(f'window.tileViewer.hoverSection({section});')
            self.active_section = section


    def on_mouseout_canvas(self, e: events.GenericEventArguments) -> None:
        debug('on_mouseout_canvas called')
        if self.active_section is None:
            ui.run_javascript('window.tileViewer.unhoverSection();')


    def update_tile_info(self) -> None:
        for n in range(3):
            self.reuse_badges[n].set_text(str(self.reuse_tiles[n]))
            if self.total_tiles[n] > 255:
                bg = 'red'
            elif self.total_tiles[n] > 200:
                bg = 'yellow'
            else:
                bg = 'green'
            self.total_badges[n].set_text_color(get_text_color(bg))
            self.total_badges[n].set_background_color(bg)
            self.total_badges[n].set_text(str(self.total_tiles[n]))
        self.threshold_status.enable()


    def load_image(self, data: bytes) -> None:
        try:
            image = Image.open(BytesIO(data)).convert("RGB")
            self.set_image(image, frame=3)
        except Exception as e:
            traceback.print_exc()
            ui.notify(e)


    def set_image(self, image: Image.Image, frame: int = 3) -> None:
        try:
            self.msx = self.engine.convert(image)
        except Exception as e:
            traceback.print_exc()
            ui.notify(e)
            return

        # update tile info
        self.process_tiles(self.threshold_dropdown.text)
        self.update_tile_info()

        # reset visible images
        self.render_images(frame)

        # enable all widgets
        self.grid_width_number.set_value(8);
        enable(self.grid_width_number)
        self.grid_height_number.set_value(8);
        enable(self.grid_height_number)
        self.threshold_number.set_value(0.0);
        enable(self.frame_toggle)


    def render_images(self, frame: int) -> None:
        # create all frames (1 = even, 2 = odd, 3 = combined) at once
        if self.msx:
            self.images64 = ['']
            for n in range(1, 4):
                buffer = BytesIO()
                image = self.msx.to_image(n)
                image.save(buffer, format='PNG')
                image64 = file_to_base64(buffer)
                self.images64.append(image64)
            self.draw_frame(frame)


    def draw_frame(self, frame: int = 3) -> None:
        self.current_frame = frame
        ui.run_javascript(f'''
            window.tileViewer.initialize({{
                canvasId: "tile_canvas",
                image: "{self.images64[frame]}",
                selectedX: {self.selected_pos[0]},
                selectedY: {self.selected_pos[1]},
                gridWidth: {self.grid_width},
                gridHeight: {self.grid_height},
                zoom: {self.zoom},
            }});
        ''')
        self.redraw()


    def remove_image(self) -> None:
        if self.msx:
            self.msx = None
            disable(self.grid_width_number)
            disable(self.grid_height_number)
            ui.run_javascript('window.tileViewer.reset();');


    def on_remove_image(self, event: events.GenericEventArguments) -> None:
        self.remove_image()


    def on_change_grid_size(self, type_: str, event: events.ValueChangeEventArguments[float | None]) -> None:
        if self.msx and type(event.value) == float:
            if type_ == 'w': self.grid_width = int(event.value)
            if type_ == 'h': self.grid_height = int(event.value)
            self.redraw()


    def on_change_threshold(self, event: events.ValueChangeEventArguments[float | None]) -> None:
        if event.value is None:
            return
        try:
            self.threshold_status.disable()
            self.process_tiles(self.threshold_dropdown.text, 0.0)
            self.threshold = event.value
            self.update_tile_info()
            self.dirty_status.enable()
        except Exception as e:
            traceback.print_exc()
        finally:
            self.threshold_status.enable()


    def on_export_to_msx_clicked(self) -> None:
        if not 'pgt' in self.vram[0]:
            raise AttributeError('source image not processed')
        buffer = BytesIO()
        slackspaces = self.engine.save(list(self.vram), buffer)
        ui.download.content(buffer.getvalue(), 'image.s2i')


    def on_export_to_png_clicked(self) -> None:
        if self.msx:
            buffer = BytesIO()
            image = self.msx.to_image(3)
            image.save(buffer, format='PNG')
            ui.download.content(buffer.getvalue(), 'image.png')


    def on_export_to_c_clicked(self) -> None:
        pass


    def redraw(self) -> None:
        ui.run_javascript(f'''
            window.tileViewer.setState({{
                selectedX: {self.selected_pos[0]},
                selectedY: {self.selected_pos[1]},
                gridWidth: {self.grid_width},
                gridHeight: {self.grid_height},
                zoom: {self.zoom},
            }});
            window.tileViewer.draw();
        ''')


    def set_zoom(self, zoom: int) -> None:
        self.zoom = zoom
        self.redraw()


    async def on_tile_clicked(self, e: events.GenericEventArguments) -> None:
        if not self.msx:
            return
        if self.waiting_tile_editor:
            return
        self.waiting_tile_editor.enable()
        self.selected_pos = (int(e.args['x'] // self.grid_width) * self.grid_width, int(e.args['y'] // self.grid_height) * self.grid_height)
        self.redraw()

        frame = 1 + int(e.args['button'] // 2)
        data = self.msx.to_metatile(int(self.selected_pos[0] // TILE_SIZE), int(self.selected_pos[1] // TILE_SIZE * TILE_SIZE),
                                    int(self.grid_width // TILE_SIZE), self.grid_height, frame)
        # Fix here
        metatile = from_105_to_metatile(data, self.grid_width, self.grid_height)

        width = min(common.SCREEN_WIDTH * 0.90, 260 + self.msx.width * GRID_PIXEL_MAX)
        with ui.dialog() as dialog, ui.card().style(f'max-width: None; width: {width}px;'):
            editor = TileEditor(dialog, metatile)
            with ui.row().classes('w-full justify-end'):
                ui.button('OK', on_click=lambda: dialog.submit(True))
                ui.button('Cancel', on_click=lambda: dialog.submit(False))
        if await dialog:
            # update MSX image with changed tile
            y: int
            row: TileRow
            for y, row in enumerate(editor.grid):
                fg, bg = 0, 0
                for x in range(len(row)):
                    if x % TILE_SIZE == 0:
                        fg, bg = row.get_fg(x), row.get_bg(x)
                    bit = True if row[x] == fg else False
                    bpu: MSXBitmapUnit = cast(MSXBitmapUnit, self.msx[y + self.selected_pos[1]][(x + self.selected_pos[0]) // TILE_SIZE])
                    bpu.from_rgb(x % TILE_SIZE, bit, fg, bg, frame)
            # update PGT and PNT structures (TODO: update only the affected region)
            self.process_tiles(self.threshold_dropdown.text, 0.0)
            self.render_images(self.current_frame)
        self.waiting_tile_editor.disable()


    def process_tiles(self, algorithm: str = 'DCT', threshold: float = 0.0) -> None:
        """Run outside class so we don't have to pickle it."""
        if not self.msx: raise AttributeError('source image not found')

        self.dirty_status.disable()

        self.vram = (
             self.engine.stats(self.msx, 0, 64, threshold, algorithm),
             self.engine.stats(self.msx, 64, 128, threshold, algorithm),
             self.engine.stats(self.msx, 128, 192, threshold, algorithm)
        )

        self.reuse_tiles = (len(self.vram[0]['pcl0']) + len(self.vram[0]['pcl1']),
                            len(self.vram[1]['pcl0']) + len(self.vram[1]['pcl1']),
                            len(self.vram[2]['pcl0']) + len(self.vram[2]['pcl1']))
        debug(f'reuse_tiles = {self.reuse_tiles[0]}, {self.reuse_tiles[1]}, {self.reuse_tiles[2]}')
        self.total_tiles = (len(self.vram[0]['pgt']), len(self.vram[1]['pgt']), len(self.vram[2]['pgt']))
        debug(f'total_tiles = {self.total_tiles}')

        self.update_tile_info()


    def on_update_clicked(self) -> None:
        self.process_image()
        self.dirty_status.disable()


    def process_image(self) -> None:
        if not self.msx: raise AttributeError('source image not found')
        for region in range(3):
            for frame in range(2):
                for x, y, hash_ in self.vram[region]['pcl0']:
                    for n, (p0, c0) in enumerate(zip(self.vram[region]['pgt'][hash_], self.vram[region]['pct'][hash_])):
                        tile0: MSXBitmapUnit = cast(MSXBitmapUnit, self.msx[region * 64 + y * TILE_SIZE + n][x])
                        tile0.c0 = c0
                        tile0.p0 = p0
                for x, y, hash_ in self.vram[region]['pcl1']:
                    for n, (p1, c1) in enumerate(zip(self.vram[region]['pgt'][hash_], self.vram[region]['pct'][hash_])):
                        tile1: MSXBitmapUnit = cast(MSXBitmapUnit, self.msx[region * 64 + y * TILE_SIZE + n][x])
                        tile1.c1 = c1
                        tile1.p1 = p1

        self.render_images(self.current_frame)
