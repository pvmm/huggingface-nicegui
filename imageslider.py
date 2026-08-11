import glob
import os

from typing import Callable, cast
from nicegui import ui, events
from pathlib import Path
from fileloader import FileLoader
from sessionbroker import display_task_dialog


class ImageSliderWidget:
    image_paths: list[str] | str
    on_loaded_callback: Callable[[bytes], None]
    on_removed_callback: Callable[[], None]
    current_index: int | None
    width: int
    height: int
    old_thumbnail: ui.card | None

    def __init__(self, image_paths: list[str] | str, width: int, height: int, on_loaded: Callable[[bytes], None], on_removed: Callable[[], None]) -> None:
        """
        Initialize the image slider widget

        Args:
            image_paths: List of image file paths or directory path containing images
            width: Image width
            height: Image height
        """
        self.image_paths = []
        self.on_loaded_callback = on_loaded
        self.on_removed_callback = on_removed
        self.current_index = None
        self.width = width
        self.height = height
        self.old_thumbnail = None

        # Load images
        if isinstance(image_paths, str) and os.path.isdir(image_paths):
            # Load all images from directory
            extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.bmp']
            for ext in extensions:
                self.image_paths.extend(glob.glob(os.path.join(image_paths, ext)))
            self.image_paths.sort()
        else:
            self.image_paths = list(image_paths)

        if not self.image_paths:
            ui.notify('No images found!', type='negative')
            return

        # Create the UI
        self.build_ui()

    def build_ui(self) -> None:
        """Create the widget UI"""
        with ui.card().classes('w-full items-center p-4'):
            # Counter
            with ui.row().classes('items-center justify-between w-full'):
                self.counter = (
                        ui.label(f'Sample images: {len(self.image_paths)}')
                            .classes('text-h6 font-bold')
                )

            # Thumbnail slider
            with ui.row().classes('w-full overflow-x-auto items-end flex-nowrap') as parent:
                FileLoader(parent, '256x192 image', 266, 240, self.on_loaded_callback, self.on_removed_callback)
                for i, path in enumerate(self.image_paths):
                    with ui.card().classes(f'm-1 flex-shrink-0 cursor-pointer hover:shadow-md w-[{self.width + 12}px] h-[{self.height + 48}px] items-center overflow-hidden text-ellipsis') \
                            .on('click', lambda event, i=i: self.go_to_image(event, i)):
                        ui.image(path).props(f'width="{self.width}px" height="{self.height}px"')
                        ui.label(Path(path).name).classes('w-full truncate text-center text-xs whitespace-nowrap text-ellipsis nowrap')


    @display_task_dialog("Loading image...")
    async def on_loaded(self) -> None:
        if not self.current_index is None:
            await self.on_loaded_callback(open(self.image_paths[self.current_index], 'rb').read())


    async def go_to_image(self, event: events.GenericEventArguments, index: int) -> None:
        """Go to specific image by index"""
        if self.old_thumbnail:
            self.old_thumbnail._style.clear()
        self.old_thumbnail = cast(ui.card, event.sender)
        event.sender.style('outline: 2px solid black;')
        if 0 <= index < len(self.image_paths):
            self.current_index = index
            await self.on_loaded()


    def set_on_select_callback(self, callback: Callable[[int, str], None]) -> None:
        """Set callback function when an image is selected"""
        self.on_select_callback = callback


    def get_all_images(self) -> list[str] | str:
        """Get all image paths"""
        return self.image_paths

