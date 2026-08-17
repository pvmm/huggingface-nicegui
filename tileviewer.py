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
from datatypes import Tile, from_105_to_metatile, TILE_SIZE, TileRow
from tileeditor import TileEditor
from imageslider import ImageSliderWidget
from romwriter import overwrite_rom_file

from bmpto105 import Engine, MSXBitmap, MSXBitmapRow, MSXBitmapUnit, RGBColor, ScreenSectionState


# send debug message to stdout when running locally?
debug: Callable[..., Any] = print # lambda *args, **kwargs: None


ALL_SECTIONS = 7
PALETTE = [
    (0, 0, 0), (0, 0, 0), (0x24, 0xda, 0x24), (0x68, 0xff, 0x68), (0x24, 0x24, 0xff), (0x48, 0x68, 0xff),
    (0xb6, 0x24, 0x24), (0x48, 0xda, 0xff), (0xff, 0x24, 0x24), (0xff, 0x68, 0x68), (0xda, 0xda, 0x24),
    (0xda, 0xda, 0x91), (0x24, 0x91, 0x24), (0xda, 0x48, 0xb6), (0xb6, 0xb6, 0xb6), (0xff, 0xff, 0xff)
]


class TileViewer:
    loaded_status: BoolStatus
    dirty_status: BoolStatus
    despeckle_status: BoolStatus
    waiting_tile_editor: BoolStatus

    reuse_tiles: list[int]
    total_tiles: list[int]
    @property
    def display_tile_info0(self) -> str:
        return f'Reused tiles: {self.reuse_tiles[0]} / Distinct tiles: {self.total_tiles[0]}'
    @property
    def display_tile_info1(self) -> str:
        return f'Reused tiles: {self.reuse_tiles[1]} / Distinct tiles: {self.total_tiles[1]}'
    @property
    def display_tile_info2(self) -> str:
        return f'Reused tiles: {self.reuse_tiles[2]} / Distinct tiles: {self.total_tiles[2]}'

    threshold: int
    zoom: int
    grid_width: int
    grid_height: int
    selected_pos: tuple[int, int]
    msx: MSXBitmap | None
    images64: list[str]
    current_frame: int
    allow_export: BoolStatus
    vram: list[ScreenSectionState | None]
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
    min_neighbors_number: ui.number
    frame_toggle: ui.toggle
    threshold_dropdown: ui.dropdown_button
    context_menu: ui.context_menu

    def __init__(self) -> None:
        self.msx = None

        b0 = BoolStatus(function=lambda: (not self.msx is None))
        self.load_status = b0

        b1 = BoolStatus(
                inherent_state=False,
                function=lambda: (not self.msx is None))
        self.dirty_status = b1

        b2 = BoolStatus(
                #inherent_state=False,
                function=lambda: all(self.vram))
        self.despeckle_status = b2

        b3 = BoolStatus(
                inherent_state=False,
                function=lambda: (not self.msx is None))
        self.waiting_tile_editor = b3

        b4 = BoolStatus(
                function=lambda: (not self.msx is None) and all([n < 256 for n in self.total_tiles]))
        self.allow_export = b4

        self.engine = Engine(PALETTE)
        self.vram = [None, None, None]
        self.reuse_tiles = [0, 0, 0]
        self.total_tiles = [0, 0, 0]
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
                    ui.item('ROM file', on_click=self.on_export_to_rom_clicked).bind_enabled_from(self.allow_export, 'is_enabled')

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


    async def on_menu_invoked(self, e: events.GenericEventArguments) -> None:
        # ignore multiple events
        if self.opened_contextmenu:
            return

        debug('on_contextmenu_invoked called')
        self.opened_contextmenu = True

        # update active screen section
        section = 1 << (int(e.args.get('offsetY')) // self.zoom // 64)
        if self.active_section != section:
            ui.run_javascript(f'window.tileViewer.hoverSection({section // 2});')
            self.active_section = section

        # update selected tile
        self.selected_pos = (int(e.args.get('offsetX')) // self.zoom, int(e.args.get('offsetY')) // self.zoom)
        ui.run_javascript(f'window.tileViewer.setSelection({self.selected_pos[0]}, {self.selected_pos[1]});')

        # display context dialog
        self.opened_contextmenu = False
        with ui.dialog().props('transition-show=none transition-hide=none') as dialog:
            with ui.card().style(f'''
                                 position: absolute;
                                 width: 510px;
                                 left: {e.args.get('clientX')}px;
                                 top: {e.args.get('clientY')}px;
                                 max-width: None;''').classes('w-full flex-nowrap'):
                with ui.column().classes('w-full justify-start'):
                    ui.label().bind_text_from(self, f'display_tile_info{self.active_section // 2}')
                    #ui.button('Copy metatile')
                    #ui.button('Paste metatile')
                    with ui.card().classes('items-start flex-nowrap w-full'):
                        with ui.row().classes('items-center w-full'):
                            ui.button('Despeckle', on_click=self.on_despeckle_clicked) \
                                .bind_enabled_from(self.despeckle_status, 'is_enabled')
                            self.threshold_number = (
                                    ui.number(label='Color threshold', min=0, value=30, step=1, max=128, format='%d',
                                              validation={'not a number': lambda val: val is not None}
                                    ).classes('w-[100px]').props('debounce=500')
                                    .bind_enabled_from(self.despeckle_status, 'is_enabled')
                            )
                            self.min_neighbors_number = (
                                    ui.number(label='Max neighbors', min=1, value=4, step=1, max=4, format='%d',
                                              validation={'not a number': lambda val: val is not None}
                                    ).classes('w-[100px]').props('debounce=500')
                                    .bind_enabled_from(self.despeckle_status, 'is_enabled')
                            )
                            ui.button('Update', on_click=self.on_update_clicked).tooltip('Apply filter to image') \
                                .bind_enabled_from(self.dirty_status, 'is_enabled')

                    with ui.row().classes('items-start flex-nowrap w-full'):
                        ui.button('Edit even frame')
                        ui.button('Edit odd frame')
        await dialog

        # deselect metatile
        ui.run_javascript(f'window.tileViewer.unsetSelection({self.selected_pos[0]}, {self.selected_pos[1]});')


    def on_mouseover_canvas(self, e: events.GenericEventArguments) -> None:
        '''update active screen section'''
        section = 1 << (int(e.args.get('offsetY')) // self.zoom // 64)
        if self.active_section == section:
            return
        elif not self.active_section is None: # and self.context_menu.visible:
            #self.context_menu.close()
            self.active_section = None
        else:
            ui.run_javascript(f'window.tileViewer.hoverSection({section // 2});')
            self.active_section = section


    def on_mouseout_canvas(self, e: events.GenericEventArguments) -> None:
        debug('on_mouseout_canvas called')
        if self.active_section is None:
            ui.run_javascript('window.tileViewer.unhoverSection();')


    async def load_image(self, data: bytes) -> None:
        try:
            image = Image.open(BytesIO(data)).convert("RGB")
            if image.size != (256, 192):
                raise AttributeError('wrong image size')
            await self.set_image(image, frame=3)
        except Exception as e:
            traceback.print_exc()
            ui.notify(e)


    async def set_image(self, image: Image.Image, frame: int = 3) -> None:
        try:
            #self.msx = await run.io_bound(self.engine.convert, image)
            self.msx = self.engine.convert(image)
        except Exception as e:
            traceback.print_exc()
            ui.notify(e)
            return

        # update tile info and render it
        await self.process_tiles(ALL_SECTIONS, 'NUL', threshold=0.0)
        self.render_images(frame)

        # enable all widgets
        self.grid_width_number.set_value(8);
        enable(self.grid_width_number)
        self.grid_height_number.set_value(8);
        enable(self.grid_height_number)
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
        if not self.msx:
            raise AttributeError('source image not found')
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


    async def on_despeckle_clicked(self) -> None:
        if self.active_section is None:
            raise AttributeError('no section was selected')
        try:
            self.despeckle_status.disable()
            self.threshold_number.disable()
            self.min_neighbors_number.disable()
            threshold = self.threshold_number.value or 0
            min_neighbors = self.min_neighbors_number.value or 0
            await self.process_tiles(self.active_section, 'DKL', threshold=threshold, min_neightbors=min_neighbors)
            self.dirty_status.enable()
        except Exception as e:
            traceback.print_exc()
        finally:
            self.threshold_number.enable()
            self.min_neighbors_number.enable()
            self.despeckle_status.enable()


    def on_export_to_msx_clicked(self) -> None:
        if not all(self.vram):
            raise AttributeError('source image not completely processed')
        buffer = BytesIO()
        slackspaces = self.engine.save(cast(list[ScreenSectionState], self.vram), buffer)
        ui.download.content(buffer.getvalue(), 'image.s2i')


    def on_export_to_png_clicked(self) -> None:
        if not self.msx:
            raise AttributeError('source image not found')
        if not all(self.vram):
            raise AttributeError('source image not completely processed')
        buffer = BytesIO()
        image = self.msx.to_image(3)
        if image:
            image.save(buffer, format='PNG')
            ui.download.content(buffer.getvalue(), 'image.png')


    def on_export_to_rom_clicked(self) -> None:
        if not all(self.vram):
            raise AttributeError('source image not completely processed')
        buffer = BytesIO()
        slackspaces = self.engine.save(cast(list[ScreenSectionState], self.vram), buffer)
        file = overwrite_rom_file('image105.rom', 0x5c, buffer)
        ui.download.content(file.read(), 'image105.rom')


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
            await self.process_tiles(ALL_SECTIONS, 'NUL', threshold=0.0)
            self.render_images(self.current_frame)
        self.waiting_tile_editor.disable()


    async def process_tiles(self, section: int = 7, algorithm: str = 'DKL', **kwargs: float | int) -> None:
        """Run outside class so we don't have to pickle it."""
        if not self.msx: raise AttributeError('source image not found')
        debug(f'process_tiles({section}, {algorithm}, {kwargs.get("threshold", 0.0)})')

        if section & 1:
            self.vram[0] = await run.io_bound(self.engine.stats, self.msx, 0, 64, algorithm, **kwargs)
            if self.vram[0] is None: raise AttributeError('VRAM section 0 is incomplete')
            self.reuse_tiles[0] = len(self.vram[0]['pcl0']) + len(self.vram[0]['pcl1'])
            self.total_tiles[0] = len(self.vram[0]['pgt'])
        if section & 2:
            self.vram[1] = await run.io_bound(self.engine.stats, self.msx, 64, 128, algorithm, **kwargs)
            if self.vram[1] is None: raise AttributeError('VRAM section 0 is incomplete')
            self.reuse_tiles[1] = len(self.vram[1]['pcl0']) + len(self.vram[1]['pcl1'])
            self.total_tiles[1] = len(self.vram[1]['pgt'])
        if section & 4:
            self.vram[2] = await run.io_bound(self.engine.stats, self.msx, 128, 192, algorithm, **kwargs)
            if self.vram[2] is None: raise AttributeError('VRAM section 0 is incomplete')
            self.reuse_tiles[2] = len(self.vram[2]['pcl0']) + len(self.vram[2]['pcl1'])
            self.total_tiles[2] = len(self.vram[2]['pgt'])

        debug(f'reuse_tiles = {self.reuse_tiles[0]}, {self.reuse_tiles[1]}, {self.reuse_tiles[2]}')
        debug(f'total_tiles = {self.total_tiles[0]}, {self.total_tiles[1]}, {self.total_tiles[2]}')


    async def on_update_clicked(self) -> None:
        self.dirty_status.disable()
        self.process_image()


    def process_image(self) -> None:
        '''write result back to MSX image'''
        if not self.msx: raise AttributeError('source image not found')
        if self.active_section is None: raise AttributeError('no section was selected')
        if self.vram[self.active_section] is None:
            raise AttributeError('Missing image information')
        vram = cast(ScreenSectionState, self.vram[self.active_section])
        for x, y, hash_ in vram['pcl0']:
            for n, (p0, c0) in enumerate(zip(vram['pgt'][hash_], vram['pct'][hash_])):
                tile0: MSXBitmapUnit = cast(MSXBitmapUnit, self.msx[self.active_section * 64 + y * TILE_SIZE + n][x])
                tile0.c0 = c0
                tile0.p0 = p0
        for x, y, hash_ in vram['pcl1']:
            for n, (p1, c1) in enumerate(zip(vram['pgt'][hash_], vram['pct'][hash_])):
                tile1: MSXBitmapUnit = cast(MSXBitmapUnit, self.msx[self.active_section * 64 + y * TILE_SIZE + n][x])
                tile1.c1 = c1
                tile1.p1 = p1

        self.render_images(self.current_frame)
