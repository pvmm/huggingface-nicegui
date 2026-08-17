from collections.abc import Callable, Coroutine
from typing import Any
from nicegui import ui, events

from sessionbroker import display_task_dialog


# supported image types
SUPPORTED_TYPES = '.png,.bmp,.gif'


class FileLoader(ui.column):
    width: int
    height: int
    message: str
    parent: ui.element
    on_loaded: Callable[[bytes], Coroutine[Any, Any, None]]
    on_removed: Callable[[], None]

    def __init__(self, parent: ui.element, message: str, width: int, height: int, on_loaded: Callable[[bytes], Coroutine[Any, Any, None]], on_removed: Callable[[], None]) -> None:
        with parent:
            super().__init__()
            self.width = width
            self.height = height
            self.message = message
            self.parent = parent
            self.on_loaded = on_loaded
            self.on_removed = on_removed
            self.build_ui()


    def build_ui(self) -> None:
        with self:
            with (
                ui.upload(
                    on_upload=self.handle_upload,
                    on_rejected=lambda e: print('file was rejected'),
                    max_files=1)
                .classes('m-1')
                .style(f'width: {self.width}px; height: {self.height}px;')
                .props(f'auto-upload hide-upload-btn w-full accept={SUPPORTED_TYPES}')
                .on('removed', lambda e: self.on_removed())
            ).add_slot('list'):
                with ui.column().classes('h-full items-center justify-center').style('justify-content: center;'):
                    ui.icon('cloud_upload', size='lg')
                    ui.label(self.message)


    @display_task_dialog('Loading local image...')
    async def handle_upload(self, e: events.UploadEventArguments) -> None:
        """Processes the dropped/uploaded image file."""
        await self.on_loaded(await e.file.read())
